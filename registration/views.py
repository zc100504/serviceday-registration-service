import requests
from rest_framework.decorators import api_view, permission_classes
from .permissions import IsEmployee, IsAdministrator, IsEmployeeOrAdmin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.db import transaction
from .models import Registration
from django.core.cache import cache
from django.conf import settings
from .serializers import RegistrationSerializer

# Where your other services run
NGO_SERVICE_URL = "http://localhost:8002"           # ← fix
NOTIFICATION_SERVICE_URL = "http://localhost:8004"  # ← fix

def _internal_headers():
    return {
        'Authorization': f'Bearer {settings.INTERNAL_SERVICE_TOKEN}',
        'Content-Type':  'application/json',
    }

def get_ngo(ngo_id):
    """Fetch NGO data from ngo-service via HTTP"""
    try:
        response = requests.get(
            f"{NGO_SERVICE_URL}/api/v1/activities/{ngo_id}/",
            headers=_internal_headers()  # ← add internal token
        )
        if response.status_code == 200:
            data = response.json()
            return data.get('data', data)
        return None
    except requests.RequestException as e:
        return None


def notify(endpoint, payload):
    """Fire and forget — call notification-service with internal token"""
    try:
        requests.post(
            f"{NOTIFICATION_SERVICE_URL}/api/v1/notifications/{endpoint.strip('/')}/" ,
            json    = payload,
            headers = _internal_headers(),  # ← add internal token
            timeout = 3
        )
    except requests.RequestException:
        pass


# ─────────────────────────────────────────────
# GET /api/v1/registrations/my/
# ─────────────────────────────────────────────
@api_view(['GET'])
@permission_classes([IsEmployee])
def my_registration(request):
    employee_id = int(request.user.get('user_id'))
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
    employee_id = int(request.user.get('user_id'))

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

    cache.delete(f'participants_ngo_{ngo_id}')
    cache.delete(f'participants_ngo_{ngo_id}_completed_None')
    cache.delete(f'participants_ngo_{ngo_id}_completed_false')
    notify('confirmation', {'employee_id': employee_id, 'ngo_id': ngo_id, 'registration_id': reg.id})
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
    employee_id = int(request.user.get('user_id'))

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

    cache.delete(f'participants_ngo_{ngo_id}')
    cache.delete(f'participants_ngo_{ngo_id}_completed_None')
    cache.delete(f'participants_ngo_{ngo_id}_completed_false')

    notify('cancellation', {'employee_id': employee_id, 'ngo_id': ngo_id})
    return Response({'message': 'Registration cancelled.'})

# ─────────────────────────────────────────────
# PUT /api/v1/registrations/switch/<ngo_id>/
# ─────────────────────────────────────────────
@api_view(['PUT'])
@permission_classes([IsEmployee])
def switch_registration(request, ngo_id):
    employee_id = int(request.user.get('user_id'))
    print("SWITCH employee_id:", employee_id, "ngo_id:", ngo_id)

    with transaction.atomic():
        reg = Registration.objects.filter(employee_id=employee_id, completed=False).first()
        print("SWITCH reg:", reg)

        if not reg:
            print("SWITCH FAIL: no registration")
            return Response({'error': 'You must register first.'}, status=status.HTTP_400_BAD_REQUEST)

        old_ngo = get_ngo(reg.ngo_id)
        print("SWITCH old_ngo is_ended:", old_ngo.get('is_ended') if old_ngo else None)
        print("SWITCH old_ngo is_closed:", old_ngo.get('is_closed') if old_ngo else None)

        if old_ngo:
            if old_ngo.get('is_ended'):
                print("SWITCH FAIL: old event ended")
                return Response({'error': 'Your event has already started.'}, status=status.HTTP_400_BAD_REQUEST)
            if old_ngo.get('is_closed'):
                print("SWITCH FAIL: old event closed")
                return Response({'error': 'Cannot switch after cut-off date.'}, status=status.HTTP_400_BAD_REQUEST)

        new_ngo = get_ngo(ngo_id)
        print("SWITCH new_ngo:", new_ngo.get('name') if new_ngo else None)
        print("SWITCH new is_closed:", new_ngo.get('is_closed') if new_ngo else None)
        print("SWITCH new is_ended:", new_ngo.get('is_ended') if new_ngo else None)

        if not new_ngo:
            print("SWITCH FAIL: new ngo not found")
            return Response({'error': 'New activity not found.'}, status=status.HTTP_404_NOT_FOUND)
        if new_ngo.get('is_closed'):
            print("SWITCH FAIL: new ngo closed")
            return Response({'error': 'Selected activity is no longer open.'}, status=status.HTTP_400_BAD_REQUEST)
        if new_ngo.get('is_ended'):
            print("SWITCH FAIL: new ngo ended")
            return Response({'error': 'Selected activity has already ended.'}, status=status.HTTP_400_BAD_REQUEST)

        current_count = Registration.objects.filter(ngo_id=ngo_id).count()
        max_slots = new_ngo.get('max_slots', 0)
        
        if current_count >= max_slots:
            print("SWITCH FAIL: new ngo full")
            return Response({'error': 'New activity is full.'}, status=status.HTTP_400_BAD_REQUEST)

        old_ngo_id = reg.ngo_id
        reg.ngo_id = ngo_id
        reg.save()

        cache.delete(f'participants_ngo_{old_ngo_id}')
        cache.delete(f'participants_ngo_{old_ngo_id}_completed_None')
        cache.delete(f'participants_ngo_{ngo_id}')
        cache.delete(f'participants_ngo_{ngo_id}_completed_None')
        notify('switch', {'employee_id': employee_id, 'old_ngo_id': old_ngo_id, 'new_ngo_id': ngo_id})
        return Response({
            'message': 'Switched successfully.',
            'registration': RegistrationSerializer(reg).data
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

@api_view(['GET'])
@permission_classes([IsEmployeeOrAdmin])
def registrations_by_date(request):
    service_date = request.query_params.get('service_date')
    if not service_date:
        return Response({'error': 'service_date is required.'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        ngo_resp = requests.get(
            f"{NGO_SERVICE_URL}/api/v1/activities/",
            params={'service_date': service_date},
            headers=_internal_headers(),
        )
        ngo_resp.raise_for_status()
        ngos = ngo_resp.json().get('results', [])
        ngo_map = {ngo['id']: ngo for ngo in ngos}
        ngo_ids = list(ngo_map.keys())
    except Exception as e:
        return Response({'error': f'Failed to fetch NGOs: {e}'}, status=status.HTTP_502_BAD_GATEWAY)

    registrations = Registration.objects.filter(ngo_id__in=ngo_ids, completed=False)

    results = []
    for reg in registrations:
        ngo  = ngo_map.get(reg.ngo_id, {})
        try:
            user_resp = requests.get(
                f"{settings.USER_SERVICE_URL}/api/v1/users/{reg.employee_id}/",
                headers=_internal_headers(),
            )
            user = user_resp.json() if user_resp.status_code == 200 else {}
        except Exception as e:
            user = {}

        results.append({
            'employee_id':    reg.employee_id,
            'employee_email': user.get('email', ''),
            'employee_name':  f"{user.get('first_name', '')} {user.get('last_name', '')}".strip(),
            'ngo_id':         reg.ngo_id,
            'ngo_name':       ngo.get('name', ''),
            'service_date':   ngo.get('service_date', ''),
            'start_time':     ngo.get('start_time', ''),
            'end_time':       ngo.get('end_time', ''),
            'location':       ngo.get('location', ''),
        })

    return Response({'results': results})

# GET /api/v1/registrations/counts/?ngo_ids=1,2,3
@api_view(['GET'])
@permission_classes([IsEmployeeOrAdmin])
def registration_counts(request):
    # handle both formats: ?ngo_ids=1&ngo_ids=2 or ?ngo_ids=1,2,3
    ngo_ids_list = request.query_params.getlist('ngo_ids')

    if len(ngo_ids_list) == 1 and ',' in ngo_ids_list[0]:
        ngo_ids_list = ngo_ids_list[0].split(',')

    if not ngo_ids_list:
        return Response({})

    try:
        ngo_ids = [int(x.strip()) for x in ngo_ids_list]
    except ValueError:
        return Response({'error': 'Invalid ngo_ids'}, status=status.HTTP_400_BAD_REQUEST)

    counts = {}
    for ngo_id in ngo_ids:
        counts[str(ngo_id)] = Registration.objects.filter(
            ngo_id=ngo_id,
            completed=False
        ).count()

    return Response(counts)

@api_view(['GET'])
@permission_classes([IsEmployeeOrAdmin])
def registration_emails(request):
    ngo_ids = request.query_params.getlist('ngo_ids')
    if not ngo_ids:
        return Response({'emails': [], 'user_map': {}})

    employee_ids = list(
        Registration.objects.filter(
            ngo_id__in=ngo_ids,
            completed=False
        ).values_list('employee_id', flat=True).distinct()
    )

    if not employee_ids:
        return Response({'emails': [], 'user_map': {}})

    try:
        headers  = _internal_headers()
        response = requests.get(
            f"{settings.USER_SERVICE_URL}/api/v1/users/employees/emails/",
            params  = {'ids': employee_ids},
            headers = headers,
            timeout = 10,
        )
        data     = response.json()
        emails   = data.get('emails', [])
        user_map = data.get('user_map', {})  # ← get user map
    except Exception:
        emails   = []
        user_map = {}

    return Response({'emails': emails, 'user_map': user_map})