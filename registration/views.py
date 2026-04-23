import requests
from rest_framework.decorators import api_view, permission_classes
from .permissions import IsEmployee, IsAdministrator, IsEmployeeOrAdmin
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from .models import Registration
from django.core.cache import cache
from django.conf import settings
from .serializers import RegistrationSerializer

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
@permission_classes([IsEmployee])
def my_registration(request):
    employee_id = request.user.get('user_id')
    try:
        reg = Registration.objects.get(employee_id=employee_id, completed=False)
        return Response(RegistrationSerializer(reg).data)      # ← serializer
    except Registration.DoesNotExist:
        return Response({'registration': None})


# ─────────────────────────────────────────────
# POST /api/v1/registrations/register/<ngo_id>/
# ─────────────────────────────────────────────
@api_view(['POST'])
@permission_classes([IsEmployee])
def register_activity(request, ngo_id):
    employee_id = request.user.get('user_id')

    ngo = get_ngo(ngo_id)
    if not ngo:
        return Response({'error': 'Activity not found.'}, status=status.HTTP_404_NOT_FOUND)

    if ngo.get('is_ended'):
        return Response({'error': 'This activity has already ended.'}, status=status.HTTP_400_BAD_REQUEST)
    if ngo.get('is_closed'):
        return Response({'error': 'Registration is closed.'}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        current_count = Registration.objects.filter(ngo_id=ngo_id).count()
        if current_count >= ngo.get('max_slots', 0):
            return Response({'error': 'Activity is full.'}, status=status.HTTP_400_BAD_REQUEST)

        existing = Registration.objects.filter(employee_id=employee_id, completed=False).first()
        if existing:
            existing_ngo = get_ngo(existing.ngo_id)
            if existing_ngo and not existing_ngo.get('is_ended'):
                return Response({'error': 'You already registered. Please switch instead.'}, status=status.HTTP_400_BAD_REQUEST)
            existing.completed = True
            existing.save()

        reg = Registration.objects.create(employee_id=employee_id, ngo_id=ngo_id)

    notify('confirmation/', {'employee_id': employee_id, 'ngo_id': ngo_id, 'registration_id': reg.id})
    return Response(
        {'message': 'Registered successfully.', 'registration': RegistrationSerializer(reg).data},  # ← serializer
        status=status.HTTP_201_CREATED
    )


# ─────────────────────────────────────────────
# DELETE /api/v1/registrations/cancel/
# ─────────────────────────────────────────────
@api_view(['DELETE'])
@permission_classes([IsEmployee])
def cancel_registration(request):
    employee_id = request.user.get('user_id')

    reg = Registration.objects.filter(employee_id=employee_id, completed=False).first()
    if not reg:
        return Response({'error': 'No registration found.'}, status=status.HTTP_404_NOT_FOUND)

    ngo = get_ngo(reg.ngo_id)
    if ngo:
        if ngo.get('is_ended'):
            return Response({'error': 'This event has already started and cannot be cancelled.'}, status=status.HTTP_400_BAD_REQUEST)
        if ngo.get('is_closed'):
            return Response({'error': 'Cannot cancel after cut-off date.'}, status=status.HTTP_400_BAD_REQUEST)

    ngo_id = reg.ngo_id
    reg.delete()

    notify('cancellation/', {'employee_id': employee_id, 'ngo_id': ngo_id})
    return Response({'message': 'Registration cancelled.'})

# ─────────────────────────────────────────────
# PUT /api/v1/registrations/switch/<ngo_id>/
# ─────────────────────────────────────────────
@api_view(['PUT'])
@permission_classes([IsEmployee])
def switch_registration(request, ngo_id):
    employee_id = request.user.get('user_id')

    with transaction.atomic():
        reg = Registration.objects.filter(employee_id=employee_id, completed=False).first()
        if not reg:
            return Response({'error': 'You must register first.'}, status=status.HTTP_400_BAD_REQUEST)

        old_ngo = get_ngo(reg.ngo_id)
        if old_ngo:
            if old_ngo.get('is_ended'):
                return Response({'error': 'Your event has already started. Please register for a new activity instead.'}, status=status.HTTP_400_BAD_REQUEST)
            if old_ngo.get('is_closed'):
                return Response({'error': 'Cannot switch after cut-off date.'}, status=status.HTTP_400_BAD_REQUEST)

        new_ngo = get_ngo(ngo_id)
        if not new_ngo:
            return Response({'error': 'New activity not found.'}, status=status.HTTP_404_NOT_FOUND)
        if new_ngo.get('is_closed'):
            return Response({'error': 'Selected activity is no longer open.'}, status=status.HTTP_400_BAD_REQUEST)
        if new_ngo.get('is_ended'):
            return Response({'error': 'Selected activity has already ended.'}, status=status.HTTP_400_BAD_REQUEST)

        current_count = Registration.objects.filter(ngo_id=ngo_id).count()
        if current_count >= new_ngo.get('max_slots', 0):
            return Response({'error': 'New activity is full.'}, status=status.HTTP_400_BAD_REQUEST)

        old_ngo_id = reg.ngo_id
        reg.ngo_id = ngo_id
        reg.save()

    notify('switch/', {'employee_id': employee_id, 'old_ngo_id': old_ngo_id, 'new_ngo_id': ngo_id})
    return Response({
        'message': 'Switched successfully.',
        'registration': RegistrationSerializer(reg).data      # ← serializer
    })

# ─────────────────────────────────────────────────────
# GET /api/v1/registrations/participants/<ngo_id>/
# Cached participants list for an NGO activity
# ─────────────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([IsEmployeeOrAdmin])
def participants_list(request, ngo_id):
    cache_key = f'participants_ngo_{ngo_id}'

    cached_data = cache.get(cache_key)
    if cached_data is not None:
        return Response({
            'source': 'cache',
            'ngo_id': ngo_id,
            'count': len(cached_data),
            'participants': cached_data
        })

    registrations = Registration.objects.filter(ngo_id=ngo_id, completed=False)
    serializer = RegistrationSerializer(registrations, many=True)   # ← serializer

    cache.set(cache_key, serializer.data, timeout=settings.CACHE_TTL)

    return Response({
        'source': 'database',
        'ngo_id': ngo_id,
        'count': len(serializer.data),
        'participants': serializer.data
    })

