"""
Tests for the 'create new user in organisation' feature (Issue #468).
"""

from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse

from core.models import Organisation, User, UserOrganisation, UserRole


class OrganisationCreateUserTestCase(TestCase):
    """Tests for the organisation_create_user view."""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='adminpass',
            name='Admin User',
        )
        self.client.login(username='admin', password='adminpass')
        self.org = Organisation.objects.create(name='Test Org', short='TORG')
        self.url = reverse('organisation-create-user', args=[self.org.id])

    def _post(self, data):
        return self.client.post(self.url, data)

    # ------------------------------------------------------------------
    # Successful creation
    # ------------------------------------------------------------------
    def test_successful_create_user(self):
        """A new User and UserOrganisation are created with correct values."""
        response = self._post({
            'username': 'newuser',
            'email': 'newuser@example.com',
            'name': 'New User',
            'role': UserRole.USER,
        })

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # User exists
        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.username, 'newuser')
        self.assertEqual(user.name, 'New User')
        self.assertEqual(user.role, UserRole.USER)

        # Unusable password (no random password set)
        self.assertFalse(user.has_usable_password())

        # UserOrganisation with is_primary=True and correct role
        uo = UserOrganisation.objects.get(user=user, organisation=self.org)
        self.assertTrue(uo.is_primary)
        self.assertEqual(uo.role, UserRole.USER)

    def test_role_stored_correctly(self):
        """Role from modal is stored in both User and UserOrganisation."""
        response = self._post({
            'username': 'agentuser',
            'email': 'agent@example.com',
            'name': 'Agent User',
            'role': UserRole.AGENT,
        })
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(email='agent@example.com')
        self.assertEqual(user.role, UserRole.AGENT)
        uo = UserOrganisation.objects.get(user=user, organisation=self.org)
        self.assertEqual(uo.role, UserRole.AGENT)

    def test_no_usable_password_set(self):
        """No usable password is generated for the new user."""
        self._post({
            'username': 'nopassuser',
            'email': 'nopass@example.com',
            'name': 'No Pass User',
            'role': UserRole.USER,
        })
        user = User.objects.get(email='nopass@example.com')
        self.assertFalse(user.has_usable_password())

    # ------------------------------------------------------------------
    # Duplicate email check (case-insensitive)
    # ------------------------------------------------------------------
    def test_duplicate_email_returns_global_error(self):
        """Duplicate email returns a global error and no DB changes are made."""
        User.objects.create_user(
            username='existing',
            email='existing@example.com',
            password='pass',
            name='Existing User',
        )
        user_count_before = User.objects.count()

        response = self._post({
            'username': 'newuser2',
            'email': 'existing@example.com',
            'name': 'New User 2',
            'role': UserRole.USER,
        })

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('global_error', data)
        # No new user created
        self.assertEqual(User.objects.count(), user_count_before)

    def test_duplicate_email_case_insensitive(self):
        """Duplicate email check is case-insensitive (lowercasing)."""
        User.objects.create_user(
            username='caseuser',
            email='case@example.com',
            password='pass',
            name='Case User',
        )
        user_count_before = User.objects.count()

        response = self._post({
            'username': 'newuser3',
            'email': 'CASE@EXAMPLE.COM',
            'name': 'New User 3',
            'role': UserRole.USER,
        })

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('global_error', data)
        self.assertEqual(User.objects.count(), user_count_before)

    # ------------------------------------------------------------------
    # Validation errors → no DB changes
    # ------------------------------------------------------------------
    def test_validation_error_missing_username(self):
        """Missing username causes validation error; no User is created."""
        user_count_before = User.objects.count()
        response = self._post({
            'username': '',
            'email': 'valid@example.com',
            'name': 'Valid Name',
            'role': UserRole.USER,
        })
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(User.objects.count(), user_count_before)

    def test_validation_error_duplicate_username(self):
        """Duplicate username causes validation error; no new User is created."""
        User.objects.create_user(
            username='dupuser',
            email='dup@example.com',
            password='pass',
            name='Dup User',
        )
        user_count_before = User.objects.count()
        response = self._post({
            'username': 'dupuser',
            'email': 'other@example.com',
            'name': 'Other User',
            'role': UserRole.USER,
        })
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertEqual(User.objects.count(), user_count_before)

    # ------------------------------------------------------------------
    # Atomicity: if UserOrganisation creation fails, User must not persist
    # ------------------------------------------------------------------
    def test_transaction_rollback_on_user_organisation_failure(self):
        """If UserOrganisation.objects.create raises, the User is rolled back."""
        user_count_before = User.objects.count()

        with patch(
            'core.models.UserOrganisation.objects.create',
            side_effect=Exception('Simulated DB failure'),
        ):
            response = self._post({
                'username': 'rollbackuser',
                'email': 'rollback@example.com',
                'name': 'Rollback User',
                'role': UserRole.USER,
            })

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])
        # User must NOT have been persisted
        self.assertEqual(User.objects.count(), user_count_before)
        self.assertFalse(User.objects.filter(email='rollback@example.com').exists())

    # ------------------------------------------------------------------
    # Authentication required
    # ------------------------------------------------------------------
    def test_requires_login(self):
        """Unauthenticated requests are redirected."""
        self.client.logout()
        response = self._post({
            'username': 'anon',
            'email': 'anon@example.com',
            'name': 'Anon',
            'role': UserRole.USER,
        })
        # Django redirects to login page
        self.assertIn(response.status_code, [302, 403])
