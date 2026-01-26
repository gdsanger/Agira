"""
Tests for GitHub Service.
"""

from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import (
    GitHubConfiguration,
    Project,
    Item,
    ItemType,
    ExternalIssueMapping,
    ExternalIssueKind,
)
from core.services.github import GitHubService
from core.services.integrations.base import (
    IntegrationDisabled,
    IntegrationNotConfigured,
    IntegrationAuthError,
    IntegrationRateLimitError,
)

User = get_user_model()


class GitHubServiceConfigTestCase(TestCase):
    """Test GitHub service configuration checks."""
    
    def setUp(self):
        """Set up test data."""
        self.service = GitHubService()
        self.config = GitHubConfiguration.load()
    
    def test_is_enabled_returns_false_by_default(self):
        """Test that GitHub is disabled by default."""
        self.config.enable_github = False
        self.config.save()
        
        self.assertFalse(self.service.is_enabled())
    
    def test_is_enabled_returns_true_when_enabled(self):
        """Test that GitHub can be enabled."""
        self.config.enable_github = True
        self.config.save()
        
        self.assertTrue(self.service.is_enabled())
    
    def test_is_configured_returns_false_without_token(self):
        """Test that service is not configured without token."""
        self.config.github_token = ''
        self.config.save()
        
        self.assertFalse(self.service.is_configured())
    
    def test_is_configured_returns_true_with_token(self):
        """Test that service is configured with token."""
        self.config.github_token = 'test_token_123'
        self.config.save()
        
        self.assertTrue(self.service.is_configured())
    
    def test_check_availability_raises_when_disabled(self):
        """Test that disabled service raises IntegrationDisabled."""
        self.config.enable_github = False
        self.config.save()
        
        with self.assertRaises(IntegrationDisabled):
            self.service._check_availability()
    
    def test_check_availability_raises_when_not_configured(self):
        """Test that unconfigured service raises IntegrationNotConfigured."""
        self.config.enable_github = True
        self.config.github_token = ''
        self.config.save()
        
        with self.assertRaises(IntegrationNotConfigured):
            self.service._check_availability()
    
    def test_check_availability_passes_when_properly_configured(self):
        """Test that properly configured service passes check."""
        self.config.enable_github = True
        self.config.github_token = 'test_token_123'
        self.config.save()
        
        # Should not raise
        self.service._check_availability()


class GitHubServiceItemTestCase(TestCase):
    """Test GitHub service item operations."""
    
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
            key='bug',
            name='Bug'
        )
        
        # Create test item
        self.item = Item.objects.create(
            project=self.project,
            title='Test Bug',
            description='This is a test bug',
            type=self.item_type,
        )
        
        self.service = GitHubService()
    
    def test_get_repo_info_returns_owner_and_repo(self):
        """Test that repo info is extracted from project."""
        owner, repo = self.service._get_repo_info(self.item)
        
        self.assertEqual(owner, 'testowner')
        self.assertEqual(repo, 'testrepo')
    
    def test_get_repo_info_raises_without_github_config(self):
        """Test that missing GitHub config raises ValueError."""
        project_no_github = Project.objects.create(
            name='Project Without GitHub',
        )
        item_no_github = Item.objects.create(
            project=project_no_github,
            title='Test Item',
            type=self.item_type,
        )
        
        with self.assertRaises(ValueError) as context:
            self.service._get_repo_info(item_no_github)
        
        self.assertIn('does not have GitHub repository configured', str(context.exception))
    
    def test_map_state_for_open_issue(self):
        """Test state mapping for open issue."""
        github_data = {'state': 'open'}
        state = self.service._map_state(github_data, 'issue')
        
        self.assertEqual(state, 'open')
    
    def test_map_state_for_closed_issue(self):
        """Test state mapping for closed issue."""
        github_data = {'state': 'closed'}
        state = self.service._map_state(github_data, 'issue')
        
        self.assertEqual(state, 'closed')
    
    def test_map_state_for_open_pr(self):
        """Test state mapping for open PR."""
        github_data = {'state': 'open'}
        state = self.service._map_state(github_data, 'pr')
        
        self.assertEqual(state, 'open')
    
    def test_map_state_for_merged_pr(self):
        """Test state mapping for merged PR."""
        github_data = {
            'state': 'closed',
            'merged_at': '2024-01-24T10:00:00Z'
        }
        state = self.service._map_state(github_data, 'pr')
        
        self.assertEqual(state, 'merged')
    
    def test_map_state_for_closed_unmerged_pr(self):
        """Test state mapping for closed but not merged PR."""
        github_data = {
            'state': 'closed',
            'merged_at': None
        }
        state = self.service._map_state(github_data, 'pr')
        
        self.assertEqual(state, 'closed')
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_create_issue_for_item_with_defaults(self, mock_create_issue):
        """Test creating GitHub issue with default title/body."""
        mock_create_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
            'title': 'Test Bug',
        }
        
        mapping = self.service.create_issue_for_item(
            item=self.item,
            actor=self.user,
        )
        
        # Check that issue was created
        mock_create_issue.assert_called_once()
        call_args = mock_create_issue.call_args
        self.assertEqual(call_args[1]['owner'], 'testowner')
        self.assertEqual(call_args[1]['repo'], 'testrepo')
        self.assertEqual(call_args[1]['title'], 'Test Bug')
        self.assertIn('This is a test bug', call_args[1]['body'])
        
        # Check mapping was created
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.item, self.item)
        self.assertEqual(mapping.github_id, 12345)
        self.assertEqual(mapping.number, 42)
        self.assertEqual(mapping.kind, ExternalIssueKind.ISSUE)
        self.assertEqual(mapping.state, 'open')
        self.assertEqual(mapping.html_url, 'https://github.com/testowner/testrepo/issues/42')
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_create_issue_for_item_with_custom_title_body(self, mock_create_issue):
        """Test creating GitHub issue with custom title and body."""
        mock_create_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
        }
        
        mapping = self.service.create_issue_for_item(
            item=self.item,
            title='Custom Title',
            body='Custom body content',
            labels=['bug', 'priority:high'],
            actor=self.user,
        )
        
        # Check that custom values were used
        call_args = mock_create_issue.call_args
        self.assertEqual(call_args[1]['title'], 'Custom Title')
        self.assertEqual(call_args[1]['body'], 'Custom body content')
        self.assertEqual(call_args[1]['labels'], ['bug', 'priority:high'])
    
    @patch('core.services.github.client.GitHubClient.get_issue')
    def test_sync_mapping_updates_state(self, mock_get_issue):
        """Test that sync_mapping updates state from GitHub."""
        # Create existing mapping
        mapping = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=12345,
            number=42,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testowner/testrepo/issues/42',
        )
        
        # Mock GitHub response showing closed issue
        mock_get_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'closed',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
        }
        
        updated_mapping = self.service.sync_mapping(mapping)
        
        # Check that state was updated
        self.assertEqual(updated_mapping.state, 'closed')
        self.assertIsNotNone(updated_mapping.last_synced_at)
        
        # Reload from DB to verify
        mapping.refresh_from_db()
        self.assertEqual(mapping.state, 'closed')
    
    @patch('core.services.github.client.GitHubClient.get_pr')
    def test_sync_mapping_for_pr(self, mock_get_pr):
        """Test that sync_mapping works for pull requests."""
        # Create PR mapping
        mapping = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=67890,
            number=15,
            kind=ExternalIssueKind.PR,
            state='open',
            html_url='https://github.com/testowner/testrepo/pull/15',
        )
        
        # Mock GitHub response showing merged PR
        mock_get_pr.return_value = {
            'id': 67890,
            'number': 15,
            'state': 'closed',
            'merged_at': '2024-01-24T10:00:00Z',
            'html_url': 'https://github.com/testowner/testrepo/pull/15',
        }
        
        updated_mapping = self.service.sync_mapping(mapping)
        
        # Check that state was updated to 'merged'
        self.assertEqual(updated_mapping.state, 'merged')
    
    @patch('core.services.github.client.GitHubClient.get_issue')
    def test_sync_item_syncs_all_mappings(self, mock_get_issue):
        """Test that sync_item syncs all mappings for an item."""
        # Create multiple mappings
        mapping1 = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=11111,
            number=1,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testowner/testrepo/issues/1',
        )
        mapping2 = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=22222,
            number=2,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testowner/testrepo/issues/2',
        )
        
        # Mock GitHub responses
        def get_issue_side_effect(owner, repo, number):
            return {
                'id': 11111 if number == 1 else 22222,
                'number': number,
                'state': 'closed',
                'html_url': f'https://github.com/{owner}/{repo}/issues/{number}',
            }
        
        mock_get_issue.side_effect = get_issue_side_effect
        
        count = self.service.sync_item(self.item)
        
        # Check that both mappings were synced
        self.assertEqual(count, 2)
        self.assertEqual(mock_get_issue.call_count, 2)
        
        # Verify states were updated
        mapping1.refresh_from_db()
        mapping2.refresh_from_db()
        self.assertEqual(mapping1.state, 'closed')
        self.assertEqual(mapping2.state, 'closed')
    
    @patch('core.services.github.client.GitHubClient.get_issue')
    def test_upsert_mapping_creates_new_mapping(self, mock_get_issue):
        """Test that upsert_mapping_from_github creates new mapping."""
        mock_get_issue.return_value = {
            'id': 99999,
            'number': 99,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/99',
        }
        
        mapping = self.service.upsert_mapping_from_github(
            item=self.item,
            number=99,
            kind='issue',
        )
        
        # Check that mapping was created
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.github_id, 99999)
        self.assertEqual(mapping.number, 99)
        self.assertEqual(mapping.kind, ExternalIssueKind.ISSUE)
        self.assertEqual(mapping.state, 'open')
    
    @patch('core.services.github.client.GitHubClient.get_issue')
    def test_upsert_mapping_updates_existing_by_github_id(self, mock_get_issue):
        """Test that upsert finds existing mapping by github_id."""
        # Create existing mapping
        existing = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=88888,
            number=88,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testowner/testrepo/issues/88',
        )
        
        mock_get_issue.return_value = {
            'id': 88888,  # Same github_id
            'number': 88,
            'state': 'closed',  # Different state
            'html_url': 'https://github.com/testowner/testrepo/issues/88',
        }
        
        mapping = self.service.upsert_mapping_from_github(
            item=self.item,
            number=88,
            kind='issue',
        )
        
        # Check that existing mapping was updated (not created new)
        self.assertEqual(mapping.id, existing.id)
        self.assertEqual(mapping.state, 'closed')
        
        # Verify only one mapping exists
        self.assertEqual(ExternalIssueMapping.objects.count(), 1)
    
    @patch('core.services.github.client.GitHubClient.get_pr')
    def test_upsert_mapping_for_pr(self, mock_get_pr):
        """Test that upsert works for pull requests."""
        mock_get_pr.return_value = {
            'id': 77777,
            'number': 77,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/pull/77',
        }
        
        mapping = self.service.upsert_mapping_from_github(
            item=self.item,
            number=77,
            kind='pr',
        )
        
        self.assertEqual(mapping.kind, ExternalIssueKind.PR)
        self.assertEqual(mapping.number, 77)
    
    def test_upsert_mapping_raises_on_invalid_kind(self):
        """Test that upsert raises ValueError for invalid kind."""
        with self.assertRaises(ValueError) as context:
            self.service.upsert_mapping_from_github(
                item=self.item,
                number=1,
                kind='invalid',
            )
        
        self.assertIn('Invalid kind', str(context.exception))


class GitHubImportClosedIssuesTestCase(TestCase):
    """Test importing closed GitHub issues for a project."""
    
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
            name='Feature',
            is_active=True,
        )
        
        self.service = GitHubService()
    
    @patch('core.services.github.client.GitHubClient.list_issues')
    @patch('core.services.github.client.GitHubClient.get_issue_timeline')
    def test_import_closed_issues_creates_items(self, mock_timeline, mock_list_issues):
        """Test that import creates items for closed issues."""
        # Mock GitHub API response with closed issues
        mock_list_issues.return_value = [
            {
                'id': 111111,
                'number': 1,
                'state': 'closed',
                'title': 'Bug Fix',
                'body': 'Fixed a critical bug',
                'html_url': 'https://github.com/testowner/testrepo/issues/1',
            },
            {
                'id': 222222,
                'number': 2,
                'state': 'closed',
                'title': 'Feature Request',
                'body': 'Added new feature',
                'html_url': 'https://github.com/testowner/testrepo/issues/2',
            },
        ]
        
        # Mock timeline (no PRs)
        mock_timeline.return_value = []
        
        # Import closed issues
        stats = self.service.import_closed_issues_for_project(
            project=self.project,
            actor=self.user,
        )
        
        # Check stats
        self.assertEqual(stats['issues_found'], 2)
        self.assertEqual(stats['issues_imported'], 2)
        self.assertEqual(stats['prs_linked'], 0)
        self.assertEqual(len(stats['errors']), 0)
        
        # Verify items were created
        items = Item.objects.filter(project=self.project)
        self.assertEqual(items.count(), 2)
        
        # Verify item status is CLOSED
        from core.models import ItemStatus
        for item in items:
            self.assertEqual(item.status, ItemStatus.CLOSED)
        
        # Verify mappings were created
        mappings = ExternalIssueMapping.objects.filter(item__project=self.project)
        self.assertEqual(mappings.count(), 2)
        
        # Verify mapping details
        mapping1 = mappings.get(number=1)
        self.assertEqual(mapping1.github_id, 111111)
        self.assertEqual(mapping1.state, 'closed')
        self.assertEqual(mapping1.kind, ExternalIssueKind.ISSUE)
    
    @patch('core.services.github.client.GitHubClient.list_issues')
    def test_import_skips_pull_requests(self, mock_list_issues):
        """Test that import skips items that are pull requests."""
        # Mock response with a mix of issues and PRs
        mock_list_issues.return_value = [
            {
                'id': 111111,
                'number': 1,
                'state': 'closed',
                'title': 'Bug Fix',
                'body': 'Fixed a critical bug',
                'html_url': 'https://github.com/testowner/testrepo/issues/1',
            },
            {
                'id': 222222,
                'number': 2,
                'state': 'closed',
                'title': 'PR for Feature',
                'body': 'Added new feature',
                'html_url': 'https://github.com/testowner/testrepo/pull/2',
                'pull_request': {},  # This marks it as a PR
            },
        ]
        
        stats = self.service.import_closed_issues_for_project(
            project=self.project,
            actor=self.user,
        )
        
        # Only the issue should be counted, not the PR
        self.assertEqual(stats['issues_found'], 1)
        self.assertEqual(stats['issues_imported'], 1)
    
    @patch('core.services.github.client.GitHubClient.list_issues')
    @patch('core.services.github.client.GitHubClient.get_issue_timeline')
    def test_import_skips_existing_issues(self, mock_timeline, mock_list_issues):
        """Test that import skips issues that already have mappings."""
        # Create existing item and mapping
        from core.models import ItemStatus
        existing_item = Item.objects.create(
            project=self.project,
            title='Existing Issue',
            type=self.item_type,
            status=ItemStatus.CLOSED,
        )
        ExternalIssueMapping.objects.create(
            item=existing_item,
            github_id=111111,
            number=1,
            kind=ExternalIssueKind.ISSUE,
            state='closed',
            html_url='https://github.com/testowner/testrepo/issues/1',
        )
        
        # Mock GitHub API response
        mock_list_issues.return_value = [
            {
                'id': 111111,  # Same ID as existing mapping
                'number': 1,
                'state': 'closed',
                'title': 'Existing Issue',
                'body': 'This already exists',
                'html_url': 'https://github.com/testowner/testrepo/issues/1',
            },
        ]
        mock_timeline.return_value = []
        
        stats = self.service.import_closed_issues_for_project(
            project=self.project,
            actor=self.user,
        )
        
        # Should find 1 issue but import 0 (already exists)
        self.assertEqual(stats['issues_found'], 1)
        self.assertEqual(stats['issues_imported'], 0)
        
        # Should still only have 1 item
        self.assertEqual(Item.objects.filter(project=self.project).count(), 1)
    
    def test_import_raises_without_github_config(self):
        """Test that import raises ValueError without GitHub config."""
        project_no_config = Project.objects.create(
            name='No GitHub Project',
        )
        
        with self.assertRaises(ValueError) as context:
            self.service.import_closed_issues_for_project(
                project=project_no_config,
                actor=self.user,
            )
        
        self.assertIn('does not have GitHub repository configured', str(context.exception))


class GitHubClientTestCase(TestCase):
    """Test GitHub client HTTP interactions."""
    
    @patch('core.services.integrations.http.httpx.Client')
    def test_client_sets_auth_headers(self, mock_client_class):
        """Test that client sets proper authentication headers."""
        from core.services.github.client import GitHubClient
        
        # Mock the HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'id': 1, 'number': 1}
        
        mock_client = Mock()
        mock_client.request.return_value = mock_response
        mock_client.__enter__ = Mock(return_value=mock_client)
        mock_client.__exit__ = Mock(return_value=False)
        mock_client_class.return_value = mock_client
        
        client = GitHubClient(token='test_token_123')
        result = client.get_issue('owner', 'repo', 1)
        
        # Check that request was made with auth header
        mock_client.request.assert_called_once()
        call_args = mock_client.request.call_args
        headers = call_args[1]['headers']
        
        self.assertIn('Authorization', headers)
        self.assertEqual(headers['Authorization'], 'Bearer test_token_123')
        self.assertEqual(headers['Accept'], 'application/vnd.github+json')
        self.assertEqual(headers['X-GitHub-Api-Version'], '2022-11-28')


if __name__ == '__main__':
    import django
    django.setup()
    from django.test.utils import get_runner
    from django.conf import settings
    
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    failures = test_runner.run_tests(['core.services.github.test_github'])
