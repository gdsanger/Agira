"""
Tests for GitHub issue creation from Item admin action.
"""

from unittest.mock import Mock, patch
from django.test import TestCase
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model

from core.models import (
    GitHubConfiguration,
    Project,
    Item,
    ItemType,
    ItemStatus,
    ExternalIssueMapping,
    ExternalIssueKind,
)
from core.admin import ItemAdmin
from core.services.github.service import GitHubService

User = get_user_model()


class MockRequest:
    """Mock request for admin action testing."""
    
    def __init__(self, user):
        self.user = user
        # Use a simple list for messages instead of FallbackStorage
        self._messages_list = []
    
    def _get_messages(self):
        return self._messages_list


class GitHubIssueCreationTestCase(TestCase):
    """Test GitHub issue creation from admin action."""
    
    def setUp(self):
        """Set up test data."""
        # Configure GitHub
        self.config = GitHubConfiguration.load()
        self.config.enable_github = True
        self.config.github_token = 'test_token_123'
        self.config.github_api_base_url = 'https://api.github.com'
        self.config.save()
        
        # Create test user
        self.user = User.objects.create_superuser(
            username='admin',
            email='admin@example.com',
            password='admin123',
            name='Admin User'
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
        
        # Set up admin
        self.site = AdminSite()
        self.admin = ItemAdmin(Item, self.site)
        
        # Set up request
        self.request = MockRequest(self.user)
    
    def test_can_create_issue_for_backlog_item(self):
        """Test that service allows issue creation for Backlog status."""
        item = Item.objects.create(
            project=self.project,
            title='Backlog Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        service = GitHubService()
        self.assertTrue(service.can_create_issue_for_item(item))
    
    def test_can_create_issue_for_working_item(self):
        """Test that service allows issue creation for Working status."""
        item = Item.objects.create(
            project=self.project,
            title='Working Item',
            type=self.item_type,
            status=ItemStatus.WORKING,
        )
        
        service = GitHubService()
        self.assertTrue(service.can_create_issue_for_item(item))
    
    def test_can_create_issue_for_testing_item(self):
        """Test that service allows issue creation for Testing status."""
        item = Item.objects.create(
            project=self.project,
            title='Testing Item',
            type=self.item_type,
            status=ItemStatus.TESTING,
        )
        
        service = GitHubService()
        self.assertTrue(service.can_create_issue_for_item(item))
    
    def test_cannot_create_issue_for_inbox_item(self):
        """Test that service rejects issue creation for Inbox status."""
        item = Item.objects.create(
            project=self.project,
            title='Inbox Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
        
        service = GitHubService()
        self.assertFalse(service.can_create_issue_for_item(item))
    
    def test_cannot_create_issue_for_ready_item(self):
        """Test that service rejects issue creation for Ready for Release status."""
        item = Item.objects.create(
            project=self.project,
            title='Ready Item',
            type=self.item_type,
            status=ItemStatus.READY_FOR_RELEASE,
        )
        
        service = GitHubService()
        self.assertFalse(service.can_create_issue_for_item(item))
    
    def test_cannot_create_issue_for_closed_item(self):
        """Test that service rejects issue creation for Closed status."""
        item = Item.objects.create(
            project=self.project,
            title='Closed Item',
            type=self.item_type,
            status=ItemStatus.CLOSED,
        )
        
        service = GitHubService()
        self.assertFalse(service.can_create_issue_for_item(item))
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    @patch.object(ItemAdmin, 'message_user')
    def test_admin_action_creates_issue_for_backlog_item(self, mock_message_user, mock_create_issue):
        """Test that admin action creates GitHub issue for Backlog item."""
        # Create Copilot user for local assignment
        copilot_user = User.objects.create_user(
            username='Copilot',
            email='copilot@example.com',
            password='copilot123',
            name='GitHub Copilot Agent'
        )
        
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
            'assignees': [],  # No GitHub assignees
        }
        
        queryset = Item.objects.filter(id=item.id)
        self.admin.create_github_issue(self.request, queryset)
        
        # Check that issue was created WITHOUT GitHub assignees
        mock_create_issue.assert_called_once()
        call_kwargs = mock_create_issue.call_args[1]
        self.assertNotIn('assignees', call_kwargs)
        
        # Check that mapping was created
        mapping = ExternalIssueMapping.objects.filter(item=item).first()
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.github_id, 12345)
        self.assertEqual(mapping.number, 42)
        self.assertEqual(mapping.kind, ExternalIssueKind.ISSUE)
        self.assertEqual(mapping.state, 'open')
        
        # Check that item was assigned locally to Copilot user
        item.refresh_from_db()
        self.assertEqual(item.assigned_to, copilot_user)
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    @patch.object(ItemAdmin, 'message_user')
    def test_admin_action_skips_inbox_item(self, mock_message_user, mock_create_issue):
        """Test that admin action skips Inbox items."""
        item = Item.objects.create(
            project=self.project,
            title='Inbox Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
        
        queryset = Item.objects.filter(id=item.id)
        self.admin.create_github_issue(self.request, queryset)
        
        # Check that issue was NOT created
        mock_create_issue.assert_not_called()
        
        # Check that no mapping was created
        self.assertEqual(ExternalIssueMapping.objects.filter(item=item).count(), 0)
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    @patch.object(ItemAdmin, 'message_user')
    def test_admin_action_skips_item_with_existing_issue(self, mock_message_user, mock_create_issue):
        """Test that admin action skips items that already have a GitHub issue."""
        item = Item.objects.create(
            project=self.project,
            title='Item With Issue',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        # Create existing mapping
        ExternalIssueMapping.objects.create(
            item=item,
            github_id=99999,
            number=99,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testowner/testrepo/issues/99',
        )
        
        queryset = Item.objects.filter(id=item.id)
        self.admin.create_github_issue(self.request, queryset)
        
        # Check that issue was NOT created
        mock_create_issue.assert_not_called()
        
        # Check that still only one mapping exists
        self.assertEqual(ExternalIssueMapping.objects.filter(item=item).count(), 1)
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    @patch.object(ItemAdmin, 'message_user')
    def test_admin_action_creates_multiple_issues(self, mock_message_user, mock_create_issue):
        """Test that admin action can create multiple issues."""
        # Create Copilot user for local assignment
        copilot_user = User.objects.create_user(
            username='Copilot',
            email='copilot@example.com',
            password='copilot123',
            name='GitHub Copilot Agent'
        )
        
        item1 = Item.objects.create(
            project=self.project,
            title='Backlog Item 1',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        item2 = Item.objects.create(
            project=self.project,
            title='Working Item 2',
            type=self.item_type,
            status=ItemStatus.WORKING,
        )
        item3 = Item.objects.create(
            project=self.project,
            title='Testing Item 3',
            type=self.item_type,
            status=ItemStatus.TESTING,
        )
        
        def create_issue_side_effect(owner, repo, title, body, labels=None):
            # Simulate different issue numbers
            if 'Item 1' in title:
                number = 101
            elif 'Item 2' in title:
                number = 102
            else:
                number = 103
            
            return {
                'id': 10000 + number,
                'number': number,
                'state': 'open',
                'html_url': f'https://github.com/{owner}/{repo}/issues/{number}',
                'title': title,
                'assignees': [],  # No GitHub assignees
            }
        
        mock_create_issue.side_effect = create_issue_side_effect
        
        queryset = Item.objects.filter(id__in=[item1.id, item2.id, item3.id])
        self.admin.create_github_issue(self.request, queryset)
        
        # Check that all three issues were created
        self.assertEqual(mock_create_issue.call_count, 3)
        
        # Check that all three mappings were created
        self.assertEqual(ExternalIssueMapping.objects.filter(item__in=[item1, item2, item3]).count(), 3)
        
        # Verify each mapping
        mapping1 = ExternalIssueMapping.objects.get(item=item1)
        self.assertEqual(mapping1.number, 101)
        
        mapping2 = ExternalIssueMapping.objects.get(item=item2)
        self.assertEqual(mapping2.number, 102)
        
        mapping3 = ExternalIssueMapping.objects.get(item=item3)
        self.assertEqual(mapping3.number, 103)
        
        # Verify that all items were assigned locally to Copilot user
        item1.refresh_from_db()
        item2.refresh_from_db()
        item3.refresh_from_db()
        self.assertEqual(item1.assigned_to, copilot_user)
        self.assertEqual(item2.assigned_to, copilot_user)
        self.assertEqual(item3.assigned_to, copilot_user)
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    @patch.object(ItemAdmin, 'message_user')
    def test_admin_action_handles_mixed_statuses(self, mock_message_user, mock_create_issue):
        """Test that admin action creates issues for valid statuses and skips others."""
        # Create Copilot user for local assignment
        copilot_user = User.objects.create_user(
            username='Copilot',
            email='copilot@example.com',
            password='copilot123',
            name='GitHub Copilot Agent'
        )
        
        valid_item = Item.objects.create(
            project=self.project,
            title='Valid Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        invalid_item = Item.objects.create(
            project=self.project,
            title='Invalid Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
        
        mock_create_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
            'title': 'Valid Item',
            'assignees': [],  # No GitHub assignees
        }
        
        queryset = Item.objects.filter(id__in=[valid_item.id, invalid_item.id])
        self.admin.create_github_issue(self.request, queryset)
        
        # Check that only one issue was created
        mock_create_issue.assert_called_once()
        
        # Check that only one mapping was created (for valid item)
        self.assertEqual(ExternalIssueMapping.objects.filter(item=valid_item).count(), 1)
        self.assertEqual(ExternalIssueMapping.objects.filter(item=invalid_item).count(), 0)
    
    @patch.object(ItemAdmin, 'message_user')
    def test_admin_action_requires_github_enabled(self, mock_message_user):
        """Test that admin action fails when GitHub is disabled."""
        self.config.enable_github = False
        self.config.save()
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        queryset = Item.objects.filter(id=item.id)
        self.admin.create_github_issue(self.request, queryset)
        
        # Check that no mapping was created
        self.assertEqual(ExternalIssueMapping.objects.filter(item=item).count(), 0)
    
    @patch.object(ItemAdmin, 'message_user')
    def test_admin_action_requires_github_configured(self, mock_message_user):
        """Test that admin action fails when GitHub is not configured."""
        self.config.github_token = ''
        self.config.save()
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        queryset = Item.objects.filter(id=item.id)
        self.admin.create_github_issue(self.request, queryset)
        
        # Check that no mapping was created
        self.assertEqual(ExternalIssueMapping.objects.filter(item=item).count(), 0)
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    @patch.object(ItemAdmin, 'message_user')
    def test_admin_action_handles_project_without_github_repo(self, mock_message_user, mock_create_issue):
        """Test that admin action handles items from projects without GitHub configuration."""
        project_no_github = Project.objects.create(
            name='Project Without GitHub',
        )
        item = Item.objects.create(
            project=project_no_github,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        queryset = Item.objects.filter(id=item.id)
        self.admin.create_github_issue(self.request, queryset)
        
        # Check that issue was NOT created
        mock_create_issue.assert_not_called()
        
        # Check that no mapping was created
        self.assertEqual(ExternalIssueMapping.objects.filter(item=item).count(), 0)
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    @patch.object(ItemAdmin, 'message_user')
    def test_admin_action_creates_issue_even_when_copilot_user_not_exists(self, mock_message_user, mock_create_issue):
        """Test that issue is created even when Copilot user doesn't exist in Agira."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        # No Copilot user exists in Agira
        mock_create_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
            'title': 'Test Item',
            'assignees': [],  # No GitHub assignees
        }
        
        queryset = Item.objects.filter(id=item.id)
        
        # Should create issue successfully and log warning about missing Copilot user
        with self.assertLogs('core.services.github.service', level='WARNING') as log:
            self.admin.create_github_issue(self.request, queryset)
            
            # Check that warning was logged about missing Copilot user
            self.assertTrue(
                any("Copilot user does not exist" in message for message in log.output),
                "Expected warning about missing Copilot user not found in logs"
            )
        
        # Check that issue was still created
        mock_create_issue.assert_called_once()
        
        # Check that mapping was created despite missing Copilot user
        mapping = ExternalIssueMapping.objects.filter(item=item).first()
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.github_id, 12345)
        self.assertEqual(mapping.number, 42)
        
        # Check that item was NOT assigned (no Copilot user exists)
        item.refresh_from_db()
        self.assertIsNone(item.assigned_to)


class GitHubIssueCreationViewTestCase(TestCase):
    """Test GitHub issue creation from user UI view."""
    
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
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_view_creates_issue_for_backlog_item(self, mock_create_issue):
        """Test that view creates GitHub issue for Backlog item."""
        from django.test import Client
        
        # Create Copilot user for local assignment
        copilot_user = User.objects.create_user(
            username='Copilot',
            email='copilot@example.com',
            password='copilot123',
            name='GitHub Copilot Agent'
        )
        
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
            'assignees': [],  # No GitHub assignees
        }
        
        client = Client()
        client.force_login(self.user)
        response = client.post(f'/items/{item.id}/create-github-issue/')
        
        # Check that issue was created
        self.assertEqual(response.status_code, 200)
        mock_create_issue.assert_called_once()
        
        # Check that mapping was created
        mapping = ExternalIssueMapping.objects.filter(item=item).first()
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.github_id, 12345)
        self.assertEqual(mapping.number, 42)
    
    def test_view_rejects_inbox_item(self):
        """Test that view rejects Inbox items."""
        from django.test import Client
        
        item = Item.objects.create(
            project=self.project,
            title='Inbox Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
        
        client = Client()
        client.force_login(self.user)
        response = client.post(f'/items/{item.id}/create-github-issue/')
        
        # Check that request was rejected
        self.assertEqual(response.status_code, 400)
        self.assertIn('status', response.content.decode().lower())
        
        # Check that no mapping was created
        self.assertEqual(ExternalIssueMapping.objects.filter(item=item).count(), 0)
