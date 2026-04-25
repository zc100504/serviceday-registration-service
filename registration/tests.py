from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
from django.core.cache import cache
from .models import Registration
from .serializers import RegistrationSerializer, RegisterRequestSerializer
from .models import Registration

# ─────────────────────────────────────────────
# Mock helpers
# ─────────────────────────────────────────────

def mock_ngo_open(max_slots=20):
    return {
        'id': 1,
        'name': 'Beach Cleanup',
        'is_ended': False,
        'is_closed': False,
        'max_slots': max_slots,
    }

def mock_ngo_closed():
    return {
        'id': 1,
        'name': 'Beach Cleanup',
        'is_ended': False,
        'is_closed': True,
        'max_slots': 20,
    }

def mock_ngo_ended():
    return {
        'id': 1,
        'name': 'Beach Cleanup',
        'is_ended': True,
        'is_closed': False,
        'max_slots': 20,
    }


# ─────────────────────────────────────────────
# Topic 13.1 — Unit Tests: Registration Model
# ─────────────────────────────────────────────

class RegistrationModelTest(TestCase):
    """
    Unit tests for the Registration model.
    Tests model fields, constraints, and methods in isolation.
    """

    def test_registration_created(self):
        """Registration object is created with correct fields."""
        reg = Registration.objects.create(employee_id=1, ngo_id=1)
        self.assertEqual(reg.employee_id, 1)
        self.assertEqual(reg.ngo_id, 1)
        self.assertFalse(reg.completed)
        self.assertIsNotNone(reg.registered_at)

    def test_registration_str(self):
        """Registration string representation is correct."""
        reg = Registration.objects.create(employee_id=1, ngo_id=1)
        self.assertEqual(str(reg), "Employee 1 - NGO 1")

    def test_duplicate_registration_blocked(self):
        """Same employee cannot register for same NGO twice."""
        Registration.objects.create(employee_id=1, ngo_id=1)
        with self.assertRaises(Exception):
            Registration.objects.create(employee_id=1, ngo_id=1)

    def test_registration_default_not_completed(self):
        """Registration defaults to completed=False."""
        reg = Registration.objects.create(employee_id=2, ngo_id=1)
        self.assertFalse(reg.completed)

    def test_registration_can_be_marked_completed(self):
        """Registration can be marked as completed."""
        reg = Registration.objects.create(employee_id=3, ngo_id=1)
        reg.completed = True
        reg.save()
        reg.refresh_from_db()
        self.assertTrue(reg.completed)

    def test_different_employees_same_ngo(self):
        """Different employees can register for same NGO."""
        Registration.objects.create(employee_id=1, ngo_id=1)
        Registration.objects.create(employee_id=2, ngo_id=1)
        self.assertEqual(Registration.objects.filter(ngo_id=1).count(), 2)

    def test_same_employee_different_ngos(self):
        """Same employee can have registrations for different NGOs
        if first is completed."""
        Registration.objects.create(employee_id=1, ngo_id=1, completed=True)
        Registration.objects.create(employee_id=1, ngo_id=2)
        self.assertEqual(Registration.objects.filter(employee_id=1).count(), 2)




class RegistrationSerializerTest(TestCase):
    """
    Topic 13.1 — Unit tests for Registration serializers.
    """

    def test_serializer_contains_expected_fields(self):
        """Serializer returns all required fields."""
        reg = Registration.objects.create(
            employee_id=1,
            ngo_id=1
        )
        serializer = RegistrationSerializer(reg)
        fields = serializer.data.keys()
        for field in ['id', 'employee_id', 'ngo_id', 'registered_at', 'completed']:
            self.assertIn(field, fields)

    def test_serializer_data_matches_model(self):
        """Serializer data matches model fields exactly."""
        reg = Registration.objects.create(
            employee_id=1,
            ngo_id=2
        )
        serializer = RegistrationSerializer(reg)
        self.assertEqual(serializer.data['employee_id'], 1)
        self.assertEqual(serializer.data['ngo_id'], 2)
        self.assertFalse(serializer.data['completed'])

    def test_register_request_serializer_valid(self):
        """RegisterRequestSerializer validates positive ngo_id."""
        serializer = RegisterRequestSerializer(data={'ngo_id': 1})
        self.assertTrue(serializer.is_valid())

    def test_register_request_serializer_invalid_negative(self):
        """RegisterRequestSerializer rejects negative ngo_id."""
        serializer = RegisterRequestSerializer(data={'ngo_id': -1})
        self.assertFalse(serializer.is_valid())
        self.assertIn('ngo_id', serializer.errors)

    def test_register_request_serializer_invalid_zero(self):
        """RegisterRequestSerializer rejects zero ngo_id."""
        serializer = RegisterRequestSerializer(data={'ngo_id': 0})
        self.assertFalse(serializer.is_valid())
        self.assertIn('ngo_id', serializer.errors)
# ─────────────────────────────────────────────
# Topic 13.2 + 13.3 — API + Integration Tests
# ─────────────────────────────────────────────

class RegistrationAPITest(TestCase):
    """
    Integration tests for Registration API endpoints.
    Tests API + database interaction together.
    """

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            username='testemployee',
            password='testpass123'
        )
        self.payload = {
            'user_id': str(self.user.id),
            'username': 'testemployee',
            'groups': ['Employee']
        }
        self.client.force_authenticate(user=self.payload)
        cache.clear()

    # ── my_registration ───────────────────────

    def test_my_registration_empty(self):
        """Returns null when employee has no registration."""
        response = self.client.get('/api/v1/registrations/my/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data.get('registration'))

    def test_my_registration_returns_data(self):
        """Returns registration data when employee is registered."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        response = self.client.get('/api/v1/registrations/my/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['ngo_id'], 1)
        self.assertFalse(response.data['completed'])

    def test_my_registration_only_active(self):
        """Returns only non-completed registration."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1,
            completed=True
        )
        response = self.client.get('/api/v1/registrations/my/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data.get('registration'))

    # ── register_activity ─────────────────────

    def test_register_activity_success(self):
        """Employee successfully registers for an activity."""
        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify') as mock_notify:
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.post(
                '/api/v1/registrations/register/1/'
            )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Registration.objects.count(), 1)
        self.assertEqual(
            Registration.objects.first().employee_id,
            self.user.id
        )
        mock_notify.assert_called_once()

    def test_register_activity_already_registered(self):
        """Returns error when employee already has active registration."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.post(
                '/api/v1/registrations/register/1/'
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already registered', response.data['error'])

    def test_register_activity_full(self):
        """Returns error when activity is full."""
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_open(max_slots=0)
            response = self.client.post(
                '/api/v1/registrations/register/1/'
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('full', response.data['error'].lower())

    def test_register_activity_closed(self):
        """Returns error when activity registration is closed."""
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_closed()
            response = self.client.post(
                '/api/v1/registrations/register/1/'
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('closed', response.data['error'].lower())

    def test_register_activity_ended(self):
        """Returns error when activity has already ended."""
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_ended()
            response = self.client.post(
                '/api/v1/registrations/register/1/'
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ended', response.data['error'].lower())

    def test_register_activity_not_found(self):
        """Returns 404 when NGO service cannot find activity."""
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = None
            response = self.client.post(
                '/api/v1/registrations/register/1/'
            )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ── cancel_registration ───────────────────

    def test_cancel_no_registration_returns_404(self):
        """Returns 404 when employee has no registration to cancel."""
        response = self.client.delete('/api/v1/registrations/cancel/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_existing_registration(self):
        """Successfully cancels an existing registration."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify') as mock_notify:
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.delete('/api/v1/registrations/cancel/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Registration.objects.count(), 0)
        mock_notify.assert_called_once()

    def test_cancel_ended_activity_blocked(self):
        """Cannot cancel registration for an activity that has ended."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_ended()
            response = self.client.delete('/api/v1/registrations/cancel/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('started', response.data['error'].lower())

    def test_cancel_closed_activity_blocked(self):
        """Cannot cancel registration after cutoff date."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_closed()
            response = self.client.delete('/api/v1/registrations/cancel/')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cut-off', response.data['error'].lower())

    # ── switch_registration ───────────────────

    def test_switch_registration_success(self):
        """Successfully switches from one NGO to another."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify') as mock_notify:
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.put(
                '/api/v1/registrations/switch/2/'
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        reg = Registration.objects.get(employee_id=self.user.id)
        self.assertEqual(reg.ngo_id, 2)
        mock_notify.assert_called_once()

    def test_switch_without_existing_registration(self):
        """Cannot switch if no existing registration."""
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.put(
                '/api/v1/registrations/switch/2/'
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('must register first', response.data['error'])

    def test_switch_to_full_activity_blocked(self):
        """Cannot switch to a full activity."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_open(max_slots=0)
            response = self.client.put(
                '/api/v1/registrations/switch/2/'
            )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ── participants_list ─────────────────────

    def test_participants_list_empty(self):
        """Returns empty list when no registrations for NGO."""
        response = self.client.get(
            '/api/v1/registrations/participants/1/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['participants'], [])

    def test_participants_list_with_data(self):
        """Returns correct count when registrations exist."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        response = self.client.get(
            '/api/v1/registrations/participants/1/'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_participants_list_source_database_first_hit(self):
        """First call returns data from database."""
        response = self.client.get(
            '/api/v1/registrations/participants/1/'
        )
        self.assertEqual(response.data['source'], 'database')

    def test_participants_list_source_cache_second_hit(self):
        """Second call returns data from cache."""
        self.client.get('/api/v1/registrations/participants/1/')
        response = self.client.get(
            '/api/v1/registrations/participants/1/'
        )
        self.assertEqual(response.data['source'], 'cache')

    # ── cache invalidation ────────────────────

    def test_cache_invalidated_after_register(self):
        """Cache is cleared when new registration is created."""
        cache.set('participants_ngo_1', [], timeout=300)

        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify'):
            mock_ngo.return_value = mock_ngo_open()
            self.client.post('/api/v1/registrations/register/1/')

        cached = cache.get('participants_ngo_1')
        self.assertIsNone(cached)

    def test_cache_invalidated_after_cancel(self):
        """Cache is cleared when registration is cancelled."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        cache.set('participants_ngo_1', ['old_data'], timeout=300)

        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify'):
            mock_ngo.return_value = mock_ngo_open()
            self.client.delete('/api/v1/registrations/cancel/')

        cached = cache.get('participants_ngo_1')
        self.assertIsNone(cached)

    # ── registration_counts ───────────────────

    def test_registration_counts_endpoint(self):
        """Returns correct counts per NGO."""
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        response = self.client.get(
            '/api/v1/registrations/counts/?ngo_ids=1,2'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['1'], 1)
        self.assertEqual(response.data['2'], 0)

    def test_registration_counts_empty(self):
        """Returns zero counts when no registrations."""
        response = self.client.get(
            '/api/v1/registrations/counts/?ngo_ids=1,2,3'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['1'], 0)
        self.assertEqual(response.data['2'], 0)
        self.assertEqual(response.data['3'], 0)

    # ── permissions ───────────────────────────

    def test_unauthenticated_access_blocked(self):
        """Unauthenticated requests are rejected."""
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/v1/registrations/my/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN
        ])