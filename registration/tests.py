from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status
from unittest.mock import patch
from .models import Registration


class RegistrationModelTest(TestCase):
    """Topic 13.1 — Unit Testing: Model"""

    def test_registration_created(self):
        reg = Registration.objects.create(
            employee_id=1,
            ngo_id=1
        )
        self.assertEqual(reg.employee_id, 1)
        self.assertEqual(reg.ngo_id, 1)
        self.assertFalse(reg.completed)

    def test_registration_str(self):
        reg = Registration.objects.create(
            employee_id=1,
            ngo_id=1
        )
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


class RegistrationAPITest(TestCase):
    """Topic 13.3 — Integration Testing: API + Database"""

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

        # clear cache before each test
        from django.core.cache import cache
        cache.clear()

    def test_my_registration_empty(self):
        response = self.client.get('/api/v1/registrations/my/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data.get('registration'))

    def test_my_registration_returns_data(self):
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        response = self.client.get('/api/v1/registrations/my/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['ngo_id'], 1)

    def test_cancel_no_registration_returns_404(self):
        response = self.client.delete('/api/v1/registrations/cancel/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cancel_existing_registration(self):
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        with patch('registration.views.get_ngo') as mock_ngo:
            mock_ngo.return_value = {
                'id': 1,
                'is_ended': False,
                'is_closed': False,
                'max_slots': 20
            }
            response = self.client.delete('/api/v1/registrations/cancel/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(Registration.objects.count(), 0)

    def test_unauthenticated_access_blocked(self):
        self.client.force_authenticate(user=None)
        response = self.client.get('/api/v1/registrations/my/')
        self.assertIn(response.status_code, [
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN
        ])

    def test_participants_list_empty(self):
        response = self.client.get('/api/v1/registrations/participants/1/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 0)

    def test_participants_list_with_data(self):
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        response = self.client.get('/api/v1/registrations/participants/1/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['count'], 1)

    def test_registration_counts_endpoint(self):
        Registration.objects.create(
            employee_id=self.user.id,
            ngo_id=1
        )
        response = self.client.get(
            '/api/v1/registrations/counts/?ngo_ids=1,2'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['1'], 1)   # ← string key
        self.assertEqual(response.data['2'], 0)   # ← string key