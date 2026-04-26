from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
from django.core.cache import cache
from .models import Registration
from .serializers import RegistrationSerializer, RegisterRequestSerializer


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

def make_auth_client():
    user = User.objects.create_user(username='testemployee', password='testpass123')
    client = APIClient()
    client.force_authenticate(user={
        'user_id': str(user.id),
        'username': 'testemployee',
        'groups': ['Employee']
    })
    return client, user


# ─────────────────────────────────────────────
# Topic 13.1 — Unit Tests: Registration Model
# ─────────────────────────────────────────────

class RegistrationModelTest(TestCase):
    """Unit tests for the Registration model fields, constraints, and methods."""

    def test_registration_created(self):
        reg = Registration.objects.create(employee_id=1, ngo_id=1)
        self.assertEqual(reg.employee_id, 1)
        self.assertEqual(reg.ngo_id, 1)
        self.assertFalse(reg.completed)
        self.assertIsNotNone(reg.registered_at)

    def test_registration_str(self):
        reg = Registration.objects.create(employee_id=1, ngo_id=1)
        self.assertEqual(str(reg), "Employee 1 - NGO 1")

    def test_duplicate_registration_blocked(self):
        Registration.objects.create(employee_id=1, ngo_id=1)
        with self.assertRaises(Exception):
            Registration.objects.create(employee_id=1, ngo_id=1)

    def test_registration_default_not_completed(self):
        reg = Registration.objects.create(employee_id=2, ngo_id=1)
        self.assertFalse(reg.completed)

    def test_registration_can_be_marked_completed(self):
        reg = Registration.objects.create(employee_id=3, ngo_id=1)
        reg.completed = True
        reg.save()
        reg.refresh_from_db()
        self.assertTrue(reg.completed)

    def test_different_employees_same_ngo(self):
        Registration.objects.create(employee_id=1, ngo_id=1)
        Registration.objects.create(employee_id=2, ngo_id=1)
        self.assertEqual(Registration.objects.filter(ngo_id=1).count(), 2)

    def test_same_employee_different_ngos(self):
        Registration.objects.create(employee_id=1, ngo_id=1, completed=True)
        Registration.objects.create(employee_id=1, ngo_id=2)
        self.assertEqual(Registration.objects.filter(employee_id=1).count(), 2)


# ─────────────────────────────────────────────
# Topic 13.1 — Unit Tests: Serializers
# ─────────────────────────────────────────────

class RegistrationSerializerTest(TestCase):
    """Unit tests for Registration serializers."""

    def test_serializer_contains_expected_fields(self):
        reg = Registration.objects.create(employee_id=1, ngo_id=1)
        serializer = RegistrationSerializer(reg)
        for field in ['id', 'employee_id', 'ngo_id', 'registered_at', 'completed']:
            self.assertIn(field, serializer.data.keys())

    def test_serializer_data_matches_model(self):
        reg = Registration.objects.create(employee_id=1, ngo_id=2)
        serializer = RegistrationSerializer(reg)
        self.assertEqual(serializer.data['employee_id'], 1)
        self.assertEqual(serializer.data['ngo_id'], 2)
        self.assertFalse(serializer.data['completed'])

    def test_register_request_serializer_valid(self):
        serializer = RegisterRequestSerializer(data={'ngo_id': 1})
        self.assertTrue(serializer.is_valid())

    def test_register_request_serializer_invalid_negative(self):
        serializer = RegisterRequestSerializer(data={'ngo_id': -1})
        self.assertFalse(serializer.is_valid())
        self.assertIn('ngo_id', serializer.errors)

    def test_register_request_serializer_invalid_zero(self):
        serializer = RegisterRequestSerializer(data={'ngo_id': 0})
        self.assertFalse(serializer.is_valid())
        self.assertIn('ngo_id', serializer.errors)


# ─────────────────────────────────────────────
# Topic 13.2 — API Tests (response only, no DB checks)
# ─────────────────────────────────────────────

class RegistrationAPITest(TestCase):
    """
    Pure API tests — checks HTTP status codes and response shape only.
    Does NOT verify database state changes.
    """

    def setUp(self):
        self.client, self.user = make_auth_client()
        cache.clear()

    # ── my_registration ───────────────────────

    def test_my_registration_empty(self):
        """Returns null when employee has no registration."""
        response = self.client.get('/api/v1/registrations/my/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data.get('registration'))

    def test_my_registration_returns_data(self):
        """Returns registration data when employee is registered."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1)
        response = self.client.get('/api/v1/registrations/my/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['ngo_id'], 1)
        self.assertFalse(response.data['completed'])

    def test_my_registration_only_active(self):
        """Returns only non-completed registration."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1, completed=True)
        response = self.client.get('/api/v1/registrations/my/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data.get('registration'))

    # ── register_activity ─────────────────────

    def test_register_activity_success_returns_201(self):
        """Returns 201 Created when registration is successful."""
        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify'):
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.post('/api/v1/registrations/register/1/')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_register_activity_already_registered(self):
        """Returns 400 when employee already has active registration."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1)
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.post('/api/v1/registrations/register/1/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('already registered', response.data['error'])

    def test_register_activity_full(self):
        """Returns 400 when activity is full."""
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_open(max_slots=0)
            response = self.client.post('/api/v1/registrations/register/1/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('full', response.data['error'].lower())

    def test_register_activity_closed(self):
        """Returns 400 when activity registration is closed."""
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_closed()
            response = self.client.post('/api/v1/registrations/register/1/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('closed', response.data['error'].lower())

    def test_register_activity_ended(self):
        """Returns 400 when activity has already ended."""
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_ended()
            response = self.client.post('/api/v1/registrations/register/1/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('ended', response.data['error'].lower())

    def test_register_activity_not_found(self):
        """Returns 404 when NGO service cannot find activity."""
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = None
            response = self.client.post('/api/v1/registrations/register/1/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # ── cancel_registration ───────────────────

    def test_cancel_no_registration_returns_404(self):
        """Returns 404 when employee has no registration to cancel."""
        response = self.client.delete('/api/v1/registrations/cancel/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_ended_activity_blocked(self):
        """Returns 400 when activity has already ended."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1)
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_ended()
            response = self.client.delete('/api/v1/registrations/cancel/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('started', response.data['error'].lower())

    def test_cancel_closed_activity_blocked(self):
        """Returns 400 when cancelling after cutoff date."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1)
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_closed()
            response = self.client.delete('/api/v1/registrations/cancel/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('cut-off', response.data['error'].lower())

    # ── switch_registration ───────────────────

    def test_switch_without_existing_registration(self):
        """Returns 400 when switching with no existing registration."""
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.put('/api/v1/registrations/switch/2/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('must register first', response.data['error'])

    def test_switch_to_full_activity_blocked(self):
        """Returns 400 when switching to a full activity."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1)
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = mock_ngo_open(max_slots=0)
            response = self.client.put('/api/v1/registrations/switch/2/')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # ── participants_list ─────────────────────

    def test_participants_list_empty(self):
        """Returns empty list when no registrations for NGO."""
        response = self.client.get('/api/v1/registrations/participants/1/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)
        self.assertEqual(response.data['participants'], [])

    def test_participants_list_with_data(self):
        """Returns correct count when registrations exist."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1)
        response = self.client.get('/api/v1/registrations/participants/1/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    # ── permissions ───────────────────────────

    def test_unauthenticated_access_blocked(self):
        """Unauthenticated requests are rejected."""
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/v1/registrations/my/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN
        ])

    # ── registration_counts ───────────────────

    def test_registration_counts_empty(self):
        """Returns zero counts when no registrations."""
        response = self.client.get('/api/v1/registrations/counts/?ngo_ids=1,2,3')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['1'], 0)
        self.assertEqual(response.data['2'], 0)
        self.assertEqual(response.data['3'], 0)


# ─────────────────────────────────────────────
# Topic 13.3 — Integration Tests (API + DB + Cache)
# ─────────────────────────────────────────────

class RegistrationIntegrationTest(TestCase):
    """
    Integration tests — verifies the full chain:
    API request → business logic → database write/read → cache behavior.
    """

    def setUp(self):
        self.client, self.user = make_auth_client()
        cache.clear()

    # ── register saves to DB ──────────────────

    def test_register_saves_to_db(self):
        """Successful register creates exactly one DB record."""
        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify') as mock_notify:
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.post('/api/v1/registrations/register/1/')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Registration.objects.count(), 1)
        self.assertEqual(Registration.objects.first().employee_id, self.user.id)
        mock_notify.assert_called_once()

    def test_register_correct_employee_saved(self):
        """DB record belongs to the authenticated employee."""
        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify'):
            mock_ngo.return_value = mock_ngo_open()
            self.client.post('/api/v1/registrations/register/1/')

        reg = Registration.objects.get(employee_id=self.user.id)
        self.assertEqual(reg.ngo_id, 1)
        self.assertFalse(reg.completed)

    # ── cancel removes from DB ────────────────

    def test_cancel_removes_from_db(self):
        """Successful cancel deletes the DB record."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1)
        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify') as mock_notify:
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.delete('/api/v1/registrations/cancel/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Registration.objects.count(), 0)
        mock_notify.assert_called_once()

    # ── switch updates DB ─────────────────────

    def test_switch_updates_ngo_id_in_db(self):
        """Switch changes the ngo_id in the existing DB record."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1)
        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify') as mock_notify:
            mock_ngo.return_value = mock_ngo_open()
            response = self.client.put('/api/v1/registrations/switch/2/')

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        reg = Registration.objects.get(employee_id=self.user.id)
        self.assertEqual(reg.ngo_id, 2)
        mock_notify.assert_called_once()

    # ── participants cache ────────────────────

    def test_participants_first_hit_from_database(self):
        """First participants request is served from the database."""
        response = self.client.get('/api/v1/registrations/participants/1/')
        self.assertEqual(response.data['source'], 'database')

    def test_participants_second_hit_from_cache(self):
        """Second participants request is served from cache."""
        self.client.get('/api/v1/registrations/participants/1/')
        response = self.client.get('/api/v1/registrations/participants/1/')
        self.assertEqual(response.data['source'], 'cache')

    # ── cache invalidation ────────────────────

    def test_cache_invalidated_after_register(self):
        """Cache is cleared when a new registration is created."""
        cache.set('participants_ngo_1', [], timeout=300)
        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify'):
            mock_ngo.return_value = mock_ngo_open()
            self.client.post('/api/v1/registrations/register/1/')
        self.assertIsNone(cache.get('participants_ngo_1'))

    def test_cache_invalidated_after_cancel(self):
        """Cache is cleared when a registration is cancelled."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1)
        cache.set('participants_ngo_1', ['old_data'], timeout=300)
        with patch('registration.views.get_ngo') as mock_ngo, \
             patch('registration.views.notify'):
            mock_ngo.return_value = mock_ngo_open()
            self.client.delete('/api/v1/registrations/cancel/')
        self.assertIsNone(cache.get('participants_ngo_1'))

    # ── registration counts ───────────────────

    def test_registration_counts_reflect_db(self):
        """Counts endpoint returns correct count from DB."""
        Registration.objects.create(employee_id=self.user.id, ngo_id=1)
        response = self.client.get('/api/v1/registrations/counts/?ngo_ids=1,2')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['1'], 1)
        self.assertEqual(response.data['2'], 0)