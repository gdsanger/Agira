"""
Tests for GitHub issue creation with mail handling integration.
"""

from unittest.mock import Mock, patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model

from core.models import (
    GitHubConfiguration,
    Project,
    Item,
    ItemType,
    ItemStatus,
    ExternalIssueMapping,
    ExternalIssueKind,
    MailTemplate,
    MailActionMapping,
)

User = get_user_model()


class GitHubIssueCreationWithMailTestCase(TestCase):
    """Test GitHub issue creation with mail handling."""
    
    def setUp(self):
        """Set up test data."""
        # Configure GitHub
        self.config = GitHubConfiguration.load()
        self.config.enable_github = True
        self.config.github_token = 'test_token_123'
        self.config.github_api_base_url = 'https://api.github.com'
        self.config.save()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        # Create Copilot user
        self.copilot_user = User.objects.create_user(
            username='Copilot',
            email='copilot@example.com',
            password='copilot123',
            name='GitHub Copilot Agent'
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
        
        # Create mail template
        self.mail_template = MailTemplate.objects.create(
            key='working_status',
            from_name='Agira System',
            from_address='agira@example.com',
            subject='Item {{ issue.title }} is now in Working status',
            message='The item {{ issue.title }} has been moved to Working status.',
            is_active=True,
        )
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_github_issue_creation_triggers_mail_preview(self, mock_create_issue):
        """Test that creating GitHub issue for Backlog item triggers mail preview."""
        # Create MailActionMapping for WORKING status
        MailActionMapping.objects.create(
            item_status=ItemStatus.WORKING,
            item_type=self.item_type,
            mail_template=self.mail_template,
            is_active=True,
        )
        
        # Create item in BACKLOG status
        item = Item.objects.create(
            project=self.project,
            title='Backlog Feature',
            description='A new feature in backlog',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        mock_create_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
            'title': 'Backlog Feature',
            'assignees': [],
        }
        
        # Make request to create GitHub issue
        client = Client()
        client.force_login(self.user)
        response = client.post(f'/items/{item.id}/create-github-issue/')
        
        # Verify response is JSON with mail_preview
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        import json
        data = json.loads(response.content)
        
        self.assertTrue(data['success'])
        self.assertIn('mail_preview', data)
        self.assertIn('github_tab_html', data)
        
        # Verify mail preview content
        mail_preview = data['mail_preview']
        self.assertIn('subject', mail_preview)
        self.assertIn('message', mail_preview)
        self.assertIn('Backlog Feature', mail_preview['subject'])
        
        # Verify item was updated
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.WORKING)
        self.assertEqual(item.assigned_to, self.copilot_user)
        
        # Verify GitHub issue was created
        mapping = ExternalIssueMapping.objects.filter(item=item).first()
        self.assertIsNotNone(mapping)
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_github_issue_creation_no_mail_trigger_when_no_mapping(self, mock_create_issue):
        """Test that creating GitHub issue without MailActionMapping doesn't trigger mail."""
        # No MailActionMapping created
        
        # Create item in BACKLOG status
        item = Item.objects.create(
            project=self.project,
            title='Backlog Feature',
            description='A new feature in backlog',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        mock_create_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
            'title': 'Backlog Feature',
            'assignees': [],
        }
        
        # Make request to create GitHub issue
        client = Client()
        client.force_login(self.user)
        response = client.post(f'/items/{item.id}/create-github-issue/')
        
        # Verify response is HTML (no mail preview)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response['Content-Type'], 'application/json')
        
        # Verify item was updated
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.WORKING)
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_github_issue_creation_no_mail_when_already_working(self, mock_create_issue):
        """Test that creating GitHub issue for WORKING item doesn't trigger mail (no status change)."""
        # Create MailActionMapping for WORKING status
        MailActionMapping.objects.create(
            item_status=ItemStatus.WORKING,
            item_type=self.item_type,
            mail_template=self.mail_template,
            is_active=True,
        )
        
        # Create item already in WORKING status
        item = Item.objects.create(
            project=self.project,
            title='Working Feature',
            description='A feature already in working',
            type=self.item_type,
            status=ItemStatus.WORKING,
        )
        
        mock_create_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
            'title': 'Working Feature',
            'assignees': [],
        }
        
        # Make request to create GitHub issue
        client = Client()
        client.force_login(self.user)
        response = client.post(f'/items/{item.id}/create-github-issue/')
        
        # Verify response is HTML (no mail preview, status didn't change)
        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(response['Content-Type'], 'application/json')
        
        # Verify item status remains WORKING
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.WORKING)
