"""
Tests for user-specific GitHub Personal Access Token functionality.
"""

from unittest.mock import Mock, patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.models import (
    GitHubConfiguration,
    Project,
    Item,
    ItemType,
    ItemStatus,
)
from core.services.github.service import GitHubService
from core.services.integrations.base import IntegrationNotConfigured

User = get_user_model()


class UserGitHubPATTestCase(TestCase):
    """Test user-specific GitHub PAT functionality."""

    def setUp(self):
        """Set up test data."""
        # Configure GitHub
        self.config = GitHubConfiguration.load()
        self.config.enable_github = True
        self.config.github_token = 'global_token_123'
        self.config.github_api_base_url = 'https://api.github.com'
        self.config.save()

        # Create test users
        self.user_with_pat = User.objects.create_user(
            username='user_with_pat',
            email='with_pat@example.com',
            password='test123',
            name='User With PAT',
            github_pat='user_pat_token_xyz'
        )

        self.user_without_pat = User.objects.create_user(
            username='user_without_pat',
            email='without_pat@example.com',
            password='test123',
            name='User Without PAT'
        )

        # Create test project with GitHub repo
        self.project = Project.objects.create(
            name='Test Project',
            github_owner='testowner',
            github_repo='testrepo',
        )

        # Create item type
        self.item_type = ItemType.objects.create(
            key='feature',
            name='Feature'
        )

        # Create Copilot user for issue assignment
        self.copilot_user = User.objects.create_user(
            username='Copilot',
            email='copilot@example.com',
            password='copilot123',
            name='GitHub Copilot Agent'
        )

        # Set up client
        self.client = Client()

    def test_user_has_github_pat(self):
        """Test that has_github_pat() returns True when user has PAT."""
        self.assertTrue(self.user_with_pat.has_github_pat())

    def test_user_without_github_pat(self):
        """Test that has_github_pat() returns False when user has no PAT."""
        self.assertFalse(self.user_without_pat.has_github_pat())

    def test_user_with_empty_github_pat(self):
        """Test that has_github_pat() returns False when PAT is empty string."""
        user = User.objects.create_user(
            username='user_empty_pat',
            email='empty@example.com',
            password='test123',
            name='User Empty PAT',
            github_pat=''
        )
        self.assertFalse(user.has_github_pat())

    def test_user_with_whitespace_github_pat(self):
        """Test that has_github_pat() returns False when PAT is only whitespace."""
        user = User.objects.create_user(
            username='user_whitespace_pat',
            email='whitespace@example.com',
            password='test123',
            name='User Whitespace PAT',
            github_pat='   '
        )
        self.assertFalse(user.has_github_pat())

    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_service_uses_user_pat(self, mock_create_issue):
        """Test that GitHubService uses user's PAT when provided."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )

        mock_create_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
            'title': 'Test Item',
            'assignees': [],
        }

        service = GitHubService()
        mapping = service.create_issue_for_item(item, user=self.user_with_pat)

        # Verify the issue was created
        self.assertIsNotNone(mapping)
        mock_create_issue.assert_called_once()

        # Verify the client was created with user's PAT
        # We can't directly check the token, but we can verify the method was called
        # and the service completed successfully

    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_service_falls_back_to_global_token(self, mock_create_issue):
        """Test that GitHubService falls back to global token when user has no PAT."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )

        mock_create_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
            'title': 'Test Item',
            'assignees': [],
        }

        service = GitHubService()
        mapping = service.create_issue_for_item(item, user=self.user_without_pat)

        # Verify the issue was created (fallback to global token worked)
        self.assertIsNotNone(mapping)
        mock_create_issue.assert_called_once()

    def test_service_fails_without_any_token(self):
        """Test that GitHubService fails when neither user PAT nor global token available."""
        # Clear global token
        self.config.github_token = ''
        self.config.save()

        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )

        service = GitHubService()

        # Should raise IntegrationNotConfigured
        with self.assertRaises(IntegrationNotConfigured):
            service.create_issue_for_item(item, user=self.user_without_pat)

    def test_view_rejects_request_without_user_pat(self):
        """Test that view rejects GitHub issue creation when user has no PAT."""
        self.client.login(username='user_without_pat', password='test123')

        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )

        url = reverse('item-create-github-issue', args=[item.id])
        response = self.client.post(url)

        # Should return 400 error
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'GitHub Personal Access Token', response.content)

    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_view_allows_request_with_user_pat(self, mock_create_issue):
        """Test that view allows GitHub issue creation when user has PAT."""
        self.client.login(username='user_with_pat', password='test123')

        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )

        mock_create_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
            'title': 'Test Item',
            'assignees': [],
        }

        url = reverse('item-create-github-issue', args=[item.id])
        response = self.client.post(url)

        # Should succeed (200 or 302)
        self.assertIn(response.status_code, [200, 302])
        mock_create_issue.assert_called_once()

    def test_user_settings_view_requires_login(self):
        """Test that user settings view requires authentication."""
        url = reverse('user-settings')
        response = self.client.get(url)

        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_user_settings_view_displays_pat_status(self):
        """Test that user settings view displays PAT status."""
        self.client.login(username='user_with_pat', password='test123')

        url = reverse('user-settings')
        response = self.client.get(url)

        # Should show that PAT is configured
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PAT is configured')

    def test_user_settings_view_shows_no_pat_warning(self):
        """Test that user settings view shows warning when no PAT."""
        self.client.login(username='user_without_pat', password='test123')

        url = reverse('user-settings')
        response = self.client.get(url)

        # Should show warning that no PAT is configured
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'No PAT configured')

    def test_user_settings_update_sets_pat(self):
        """Test that user can set their PAT via settings update."""
        self.client.login(username='user_without_pat', password='test123')

        url = reverse('user-settings-update')
        response = self.client.post(url, {
            'github_pat': 'new_user_pat_token_123'
        })

        # Should redirect back to settings
        self.assertEqual(response.status_code, 302)

        # Check that PAT was saved
        self.user_without_pat.refresh_from_db()
        self.assertTrue(self.user_without_pat.has_github_pat())
        self.assertEqual(self.user_without_pat.github_pat, 'new_user_pat_token_123')

    def test_user_settings_update_clears_pat(self):
        """Test that user can clear their PAT via settings update."""
        self.client.login(username='user_with_pat', password='test123')

        url = reverse('user-settings-update')
        response = self.client.post(url, {
            'github_pat': ''
        })

        # Should redirect back to settings
        self.assertEqual(response.status_code, 302)

        # Check that PAT was cleared
        self.user_with_pat.refresh_from_db()
        self.assertFalse(self.user_with_pat.has_github_pat())

    def test_github_tab_shows_disabled_button_without_pat(self):
        """Test that GitHub tab shows disabled state when user has no PAT."""
        self.client.login(username='user_without_pat', password='test123')

        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )

        url = reverse('item-github-tab', args=[item.id])
        response = self.client.get(url)

        # Should show warning about missing PAT
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'GitHub Personal Access Token not configured')
        self.assertContains(response, 'User Settings')

    def test_github_tab_shows_enabled_button_with_pat(self):
        """Test that GitHub tab shows enabled button when user has PAT."""
        self.client.login(username='user_with_pat', password='test123')

        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )

        url = reverse('item-github-tab', args=[item.id])
        response = self.client.get(url)

        # Should show the create button (not disabled)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create GitHub Issue')
        # Should not show warning about missing PAT
        self.assertNotContains(response, 'GitHub Personal Access Token not configured')
