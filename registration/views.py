import requests
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from .models import Registration
from django.core.cache import cache
from django.conf import settings

# Where your other services run
NGO_SERVICE_URL = "http://localhost:8004"
NOTIFICATION_SERVICE_URL = "http://localhost:8005"


def get_ngo(ngo_id):
    """Fetch NGO data from ngo-service via HTTP"""
    try:
        response = requests.get(f"{NGO_SERVICE_URL}/api/v1/ngos/{ngo_id}/")
        if response.status_code == 200:
            return response.json()
        return None
    except requests.RequestException:
        return None


def notify(endpoint, payload):
    """Fire and forget — call notification-service"""
    try:
        requests.post(
            f"{NOTIFICATION_SERVICE_URL}/api/v1/notifications/{endpoint}/",
            json=payload,
            timeout=3
        )
    except requests.RequestException:
        pass  # notification failure should NOT block registration


# ─────────────────────────────────────────────
# GET /api/v1/registrations/my/
# ─────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def my_registration(request):
    employee_id = request.user.id

    try:
        reg = Registration.objects.get(employee_id=employee_id, completed=False)
        return Response({
            'id': reg.id,
            'ngo_id': reg.ngo_id,
            'registered_at': reg.registered_at,
            'completed': reg.completed,
        })
    except Registration.DoesNotExist:
        return Response({'registration': None})


# ─────────────────────────────────────────────
# POST /api/v1/registrations/register/<ngo_id>/
# ─────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsAuthenticated])
def register_activity(request, ngo_id):
    employee_id = request.user.id

    # 1. Fetch NGO details from ngo-service
    ngo = get_ngo(ngo_id)
    if not ngo:
        return Response(
            {'error': 'Activity not found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    # 2. Same business logic as your monolith
    if ngo.get('is_ended'):
        return Response(
            {'error': 'This activity has already ended.'},
            status=status.HTTP_400_BAD_REQUEST
        )
    if ngo.get('is_closed'):
        return Response(
            {'error': 'Registration is closed.'},
            status=status.HTTP_400_BAD_REQUEST
        )

    with transaction.atomic():
        # 3. Check slot availability
        current_count = Registration.objects.filter(ngo_id=ngo_id).count()
        if current_count >= ngo.get('max_slots', 0):
            return Response(
                {'error': 'Activity is full.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 4. Check existing registration (same logic as your monolith)
        existing = Registration.objects.filter(
            employee_id=employee_id, completed=False
        ).first()

        if existing:
            existing_ngo = get_ngo(existing.ngo_id)
            if existing_ngo and not existing_ngo.get('is_ended'):
                return Response(
                    {'error': 'You already registered. Please switch instead.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            # Old activity ended — mark completed, allow new registration
            existing.completed = True
            existing.save()

        # 5. Create registration
        reg = Registration.objects.create(
            employee_id=employee_id,
            ngo_id=ngo_id,
        )

    # 6. Notify (outside transaction — same as your monolith)
    notify('confirmation/', {
        'employee_id': employee_id,
        'ngo_id': ngo_id,
        'registration_id': reg.id,
    })

    return Response(
        {'message': 'Registered successfully.'},
        status=status.HTTP_201_CREATED
    )


# ─────────────────────────────────────────────
# DELETE /api/v1/registrations/cancel/
# ─────────────────────────────────────────────
@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def cancel_registration(request):
    employee_id = request.user.id

    reg = Registration.objects.filter(
        employee_id=employee_id, completed=False
    ).first()

    if not reg:
        return Response(
            {'error': 'No registration found.'},
            status=status.HTTP_404_NOT_FOUND
        )

    # Fetch NGO to check is_ended / is_closed
    ngo = get_ngo(reg.ngo_id)
    if ngo:
        if ngo.get('is_ended'):
            return Response(
                {'error': 'This event has already started and cannot be cancelled.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if ngo.get('is_closed'):
            return Response(
                {'error': 'Cannot cancel after cut-off date.'},
                status=status.HTTP_400_BAD_REQUEST
            )

    ngo_id = reg.ngo_id
    reg.delete()  # cancelled = deleted, same as your monolith

    notify('cancellation/', {
        'employee_id': employee_id,
        'ngo_id': ngo_id,
    })

    return Response({'message': 'Registration cancelled.'})


# ─────────────────────────────────────────────
# PUT /api/v1/registrations/switch/<ngo_id>/
# ─────────────────────────────────────────────
@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def switch_registration(request, ngo_id):
    employee_id = request.user.id

    with transaction.atomic():
        # 1. Must have existing registration
        reg = Registration.objects.filter(
            employee_id=employee_id, completed=False
        ).first()

        if not reg:
            return Response(
                {'error': 'You must register first.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 2. Check old NGO
        old_ngo = get_ngo(reg.ngo_id)
        if old_ngo:
            if old_ngo.get('is_ended'):
                return Response(
                    {'error': 'Your event has already started. Please register for a new activity instead.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if old_ngo.get('is_closed'):
                return Response(
                    {'error': 'Cannot switch after cut-off date.'},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # 3. Check new NGO
        new_ngo = get_ngo(ngo_id)
        if not new_ngo:
            return Response(
                {'error': 'New activity not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        if new_ngo.get('is_closed'):
            return Response(
                {'error': 'Selected activity is no longer open.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if new_ngo.get('is_ended'):
            return Response(
                {'error': 'Selected activity has already ended.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 4. Check slots on new NGO
        current_count = Registration.objects.filter(ngo_id=ngo_id).count()
        if current_count >= new_ngo.get('max_slots', 0):
            return Response(
                {'error': 'New activity is full.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        old_ngo_id = reg.ngo_id
        reg.ngo_id = ngo_id
        reg.save()

    notify('switch/', {
        'employee_id': employee_id,
        'old_ngo_id': old_ngo_id,
        'new_ngo_id': ngo_id,
    })

    return Response({'message': 'Switched successfully.'})

# ─────────────────────────────────────────────────────
# GET /api/v1/registrations/participants/<ngo_id>/
# Cached participants list for an NGO activity
# ─────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([IsAuthenticated])
def participants_list(request, ngo_id):
    cache_key = f'participants_ngo_{ngo_id}'

    # Try to get from cache first
    cached_data = cache.get(cache_key)
    if cached_data is not None:
        return Response({
            'source': 'cache',       # ← shows it came from cache
            'ngo_id': ngo_id,
            'count': len(cached_data),
            'participants': cached_data
        })

    # Not in cache — fetch from database
    registrations = Registration.objects.filter(
        ngo_id=ngo_id,
        completed=False
    ).values('id', 'employee_id', 'registered_at', 'completed')

    data = list(registrations)

    # Save to cache
    cache.set(cache_key, data, timeout=settings.CACHE_TTL)

    return Response({
        'source': 'database',        # ← shows it came from database
        'ngo_id': ngo_id,
        'count': len(data),
        'participants': data
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def clear_cache(request):
    cache.clear()
    return Response({'message': 'Cache cleared!'})