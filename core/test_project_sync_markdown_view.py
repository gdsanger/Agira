"""
Tests for project sync markdown view endpoint.
"""

from unittest.mock import MagicMock, patch
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import Project, ProjectStatus

User = get_user_model()


class ProjectSyncMarkdownViewTestCase(TestCase):
    """Test cases for project markdown sync endpoint"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        
        # Login the user
        self.client.login(username="testuser", password="testpass123")
        
        # Create project with GitHub repo configured
        self.project_with_repo = Project.objects.create(
            name="Test Project with Repo",
            status=ProjectStatus.WORKING,
            github_owner="testowner",
            github_repo="testrepo"
        )
        
        # Create project without GitHub repo
        self.project_without_repo = Project.objects.create(
            name="Test Project without Repo",
            status=ProjectStatus.WORKING
        )
    
    def test_sync_markdown_requires_authentication(self):
        """Test that sync endpoint requires authentication"""
        # Logout
        self.client.logout()
        
        url = reverse('project-sync-markdown', kwargs={'id': self.project_with_repo.id})
        response = self.client.post(url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_sync_markdown_without_github_repo(self):
        """Test sync markdown for project without GitHub repo configured"""
        url = reverse('project-sync-markdown', kwargs={'id': self.project_without_repo.id})
        response = self.client.post(url)
        
        # Should return 400 error
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('does not have a GitHub repository', data['error'])
    
    def test_sync_markdown_with_nonexistent_project(self):
        """Test sync markdown for non-existent project"""
        url = reverse('project-sync-markdown', kwargs={'id': 99999})
        response = self.client.post(url)
        
        # Should return 404
        self.assertEqual(response.status_code, 404)
    
    @patch('core.services.github_sync.markdown_sync.MarkdownSyncService')
    @patch('core.services.github.service.GitHubService')
    def test_sync_markdown_success(self, mock_github_service, mock_markdown_service):
        """Test successful markdown sync"""
        # Mock GitHub service
        mock_service_instance = MagicMock()
        mock_client = MagicMock()
        mock_service_instance._get_client.return_value = mock_client
        mock_github_service.return_value = mock_service_instance
        
        # Mock markdown sync service
        mock_sync_instance = MagicMock()
        mock_sync_instance.sync_project_markdown_files.return_value = {
            'files_found': 3,
            'files_created': 2,
            'files_updated': 1,
            'files_skipped': 0,
            'errors': []
        }
        mock_markdown_service.return_value = mock_sync_instance
        
        url = reverse('project-sync-markdown', kwargs={'id': self.project_with_repo.id})
        response = self.client.post(url)
        
        # Should return success
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('Successfully synced', data['message'])
        self.assertEqual(data['stats']['files_found'], 3)
        self.assertEqual(data['stats']['files_created'], 2)
        self.assertEqual(data['stats']['files_updated'], 1)
        
        # Verify service was called
        mock_sync_instance.sync_project_markdown_files.assert_called_once_with(
            self.project_with_repo
        )
    
    @patch('core.services.github_sync.markdown_sync.MarkdownSyncService')
    @patch('core.services.github.service.GitHubService')
    def test_sync_markdown_no_files_found(self, mock_github_service, mock_markdown_service):
        """Test sync when no markdown files are found"""
        # Mock GitHub service
        mock_service_instance = MagicMock()
        mock_client = MagicMock()
        mock_service_instance._get_client.return_value = mock_client
        mock_github_service.return_value = mock_service_instance
        
        # Mock markdown sync service with no files
        mock_sync_instance = MagicMock()
        mock_sync_instance.sync_project_markdown_files.return_value = {
            'files_found': 0,
            'files_created': 0,
            'files_updated': 0,
            'files_skipped': 0,
            'errors': []
        }
        mock_markdown_service.return_value = mock_sync_instance
        
        url = reverse('project-sync-markdown', kwargs={'id': self.project_with_repo.id})
        response = self.client.post(url)
        
        # Should return success but with appropriate message
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('No markdown files found', data['message'])
    
    @patch('core.services.github_sync.markdown_sync.MarkdownSyncService')
    @patch('core.services.github.service.GitHubService')
    def test_sync_markdown_all_up_to_date(self, mock_github_service, mock_markdown_service):
        """Test sync when all files are already up to date"""
        # Mock GitHub service
        mock_service_instance = MagicMock()
        mock_client = MagicMock()
        mock_service_instance._get_client.return_value = mock_client
        mock_github_service.return_value = mock_service_instance
        
        # Mock markdown sync service with all files skipped
        mock_sync_instance = MagicMock()
        mock_sync_instance.sync_project_markdown_files.return_value = {
            'files_found': 5,
            'files_created': 0,
            'files_updated': 0,
            'files_skipped': 5,
            'errors': []
        }
        mock_markdown_service.return_value = mock_sync_instance
        
        url = reverse('project-sync-markdown', kwargs={'id': self.project_with_repo.id})
        response = self.client.post(url)
        
        # Should return success
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('all were up to date', data['message'])
    
    @patch('core.services.github_sync.markdown_sync.MarkdownSyncService')
    @patch('core.services.github.service.GitHubService')
    def test_sync_markdown_with_errors(self, mock_github_service, mock_markdown_service):
        """Test sync with some errors during processing"""
        # Mock GitHub service
        mock_service_instance = MagicMock()
        mock_client = MagicMock()
        mock_service_instance._get_client.return_value = mock_client
        mock_github_service.return_value = mock_service_instance
        
        # Mock markdown sync service with errors
        mock_sync_instance = MagicMock()
        mock_sync_instance.sync_project_markdown_files.return_value = {
            'files_found': 3,
            'files_created': 1,
            'files_updated': 1,
            'files_skipped': 0,
            'errors': ['Error syncing file1.md', 'Error syncing file2.md']
        }
        mock_markdown_service.return_value = mock_sync_instance
        
        url = reverse('project-sync-markdown', kwargs={'id': self.project_with_repo.id})
        response = self.client.post(url)
        
        # Should still return success (partial success)
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('2 error(s) occurred', data['message'])
    
    @patch('core.services.github.service.GitHubService')
    def test_sync_markdown_integration_disabled(self, mock_github_service):
        """Test sync when GitHub integration is disabled"""
        from core.services.integrations.base import IntegrationDisabled
        
        # Mock GitHub service to raise IntegrationDisabled
        mock_service_instance = MagicMock()
        mock_service_instance._get_client.side_effect = IntegrationDisabled("GitHub integration is not enabled")
        mock_github_service.return_value = mock_service_instance
        
        url = reverse('project-sync-markdown', kwargs={'id': self.project_with_repo.id})
        response = self.client.post(url)
        
        # Should return 400 error
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not enabled', data['error'])
    
    @patch('core.services.github.service.GitHubService')
    def test_sync_markdown_integration_not_configured(self, mock_github_service):
        """Test sync when GitHub integration is not configured"""
        from core.services.integrations.base import IntegrationNotConfigured
        
        # Mock GitHub service to raise IntegrationNotConfigured
        mock_service_instance = MagicMock()
        mock_service_instance._get_client.side_effect = IntegrationNotConfigured("GitHub token not configured")
        mock_github_service.return_value = mock_service_instance
        
        url = reverse('project-sync-markdown', kwargs={'id': self.project_with_repo.id})
        response = self.client.post(url)
        
        # Should return 400 error
        self.assertEqual(response.status_code, 400)
        
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not configured', data['error'])
    
    def test_sync_markdown_requires_post_method(self):
        """Test that sync endpoint only accepts POST requests"""
        url = reverse('project-sync-markdown', kwargs={'id': self.project_with_repo.id})
        
        # Try GET request
        response = self.client.get(url)
        
        # Should return 405 Method Not Allowed
        self.assertEqual(response.status_code, 405)
