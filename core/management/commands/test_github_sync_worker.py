"""
Tests for GitHub sync worker command.
"""

from unittest.mock import Mock, patch, MagicMock, call
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model
from django.utils import timezone

from core.models import (
    GitHubConfiguration,
    Project,
    Item,
    ItemType,
    ItemStatus,
    ExternalIssueMapping,
    ExternalIssueKind,
)
from core.management.commands.github_sync_worker import Command

User = get_user_model()


class GitHubSyncWorkerTestCase(TestCase):
    """Test GitHub sync worker command."""
    
    def setUp(self):
        """Set up test data."""
        # Configure GitHub
        self.config = GitHubConfiguration.load()
        self.config.enable_github = True
        self.config.github_token = 'test_token_123'
        self.config.github_api_base_url = 'https://api.github.com'
        self.config.save()
        
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
            status=ItemStatus.WORKING,
        )
        
        # Create ExternalIssueMapping
        self.mapping = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=12345,
            number=42,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testowner/testrepo/issues/42',
        )
    
    def _mock_sync_mapping_close(self, mapping):
        """Helper to mock sync_mapping changing state to closed."""
        mapping.state = 'closed'
        mapping.save()
        return mapping
    
    def test_command_fails_when_github_disabled(self):
        """Test that command fails when GitHub is disabled."""
        self.config.enable_github = False
        self.config.save()
        
        from django.core.management.base import CommandError
        
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command('github_sync_worker', stdout=out, stderr=out)
    
    def test_command_fails_when_github_not_configured(self):
        """Test that command fails when GitHub is not configured."""
        self.config.github_token = ''
        self.config.save()
        
        from django.core.management.base import CommandError
        
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command('github_sync_worker', stdout=out, stderr=out)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_syncs_issue_mappings(self, mock_service_class):
        """Test that command syncs issue mappings."""
        # Mock GitHub service
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.is_configured.return_value = True
        mock_service._get_repo_info.return_value = ('testowner', 'testrepo')
        
        # Mock sync_mapping to change state
        def mock_sync_mapping(mapping):
            mapping.state = 'closed'
            mapping.save()
            return mapping
        
        mock_service.sync_mapping.side_effect = mock_sync_mapping
        mock_service_class.return_value = mock_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_client.get_issue_timeline.return_value = []
        mock_client.get_issue.return_value = {
            'id': 12345,
            'number': 42,
            'title': 'Test Issue',
            'body': 'Test body',
            'state': 'closed',
        }
        mock_service._get_client.return_value = mock_client
        
        # Mock Weaviate
        with patch('core.management.commands.github_sync_worker.is_available', return_value=False):
            out = StringIO()
            call_command('github_sync_worker', '--dry-run', stdout=out)
        
        output = out.getvalue()
        
        # Verify output
        self.assertIn('Found 1 issue mappings to sync', output)
        self.assertIn('Issue #42', output)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_updates_item_status_when_issue_closed(self, mock_service_class):
        """Test that command updates Item status when issue is closed."""
        # Mock GitHub service
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.is_configured.return_value = True
        mock_service._get_repo_info.return_value = ('testowner', 'testrepo')
        
        # Mock sync_mapping to change state to closed
        def mock_sync_mapping(mapping):
            mapping.state = 'closed'
            mapping.save()
            return mapping
        
        mock_service.sync_mapping.side_effect = mock_sync_mapping
        mock_service_class.return_value = mock_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_client.get_issue_timeline.return_value = []
        mock_client.get_issue.return_value = {
            'id': 12345,
            'number': 42,
            'title': 'Test Issue',
            'body': 'Test body',
            'state': 'closed',
        }
        mock_service._get_client.return_value = mock_client
        
        # Mock Weaviate
        with patch('core.management.commands.github_sync_worker.is_available', return_value=False):
            out = StringIO()
            call_command('github_sync_worker', stdout=out)
        
        # Reload item
        self.item.refresh_from_db()
        
        # Verify status was updated
        self.assertEqual(self.item.status, ItemStatus.TESTING)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_links_prs_from_timeline(self, mock_service_class):
        """Test that command links PRs found in timeline."""
        # Mock GitHub service
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.is_configured.return_value = True
        mock_service._get_repo_info.return_value = ('testowner', 'testrepo')
        mock_service.sync_mapping.return_value = self.mapping
        
        # Mock GitHub client with timeline containing PR reference
        mock_client = MagicMock()
        mock_client.get_issue_timeline.return_value = [
            {
                'event': 'cross-referenced',
                'source': {
                    'type': 'issue',
                    'issue': {
                        'number': 100,
                        'pull_request': {},  # Indicates this is a PR
                    }
                }
            }
        ]
        mock_client.get_issue.return_value = {
            'id': 12345,
            'number': 42,
            'title': 'Test Issue',
            'body': 'Test body',
            'state': 'open',
        }
        
        # Make _get_client return our mock client
        mock_service._get_client = MagicMock(return_value=mock_client)
        
        mock_service_class.return_value = mock_service
        
        # Track upsert_mapping_from_github calls
        pr_mapping = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=67890,
            number=100,
            kind=ExternalIssueKind.PR,
            state='open',
            html_url='https://github.com/testowner/testrepo/pull/100',
        )
        mock_service.upsert_mapping_from_github.return_value = pr_mapping
        
        # Mock Weaviate
        with patch('core.management.commands.github_sync_worker.is_available', return_value=False):
            out = StringIO()
            call_command('github_sync_worker', stdout=out)
        
        output = out.getvalue()
        
        # Verify PR was linked
        mock_service.upsert_mapping_from_github.assert_called_with(
            item=self.item,
            number=100,
            kind='pr',
        )
        self.assertIn('Linked PR #100', output)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    @patch('core.management.commands.github_sync_worker.is_available')
    @patch('core.management.commands.github_sync_worker.upsert_instance')
    def test_command_pushes_to_weaviate_on_status_change(
        self,
        mock_upsert,
        mock_weaviate_available,
        mock_service_class
    ):
        """Test that command pushes to Weaviate when status changes."""
        # Mock Weaviate as available
        mock_weaviate_available.return_value = True
        mock_upsert.return_value = 'test-uuid-123'
        
        # Mock GitHub service
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.is_configured.return_value = True
        mock_service._get_repo_info.return_value = ('testowner', 'testrepo')
        
        # Mock sync_mapping to change state
        def mock_sync_mapping(mapping):
            mapping.state = 'closed'
            mapping.save()
            return mapping
        
        mock_service.sync_mapping.side_effect = mock_sync_mapping
        mock_service_class.return_value = mock_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_client.get_issue_timeline.return_value = []
        mock_client.get_issue.return_value = {
            'id': 12345,
            'number': 42,
            'title': 'Test Issue',
            'body': 'Test body',
            'state': 'closed',
        }
        mock_service._get_client.return_value = mock_client
        
        out = StringIO()
        call_command('github_sync_worker', stdout=out)
        
        output = out.getvalue()
        
        # Verify Weaviate push was attempted
        self.assertTrue(mock_upsert.called)
        self.assertIn('Pushed', output)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_handles_batch_processing(self, mock_service_class):
        """Test that command processes mappings in batches."""
        # Create multiple mappings
        for i in range(5):
            item = Item.objects.create(
                project=self.project,
                title=f'Test Bug {i}',
                type=self.item_type,
                status=ItemStatus.WORKING,
            )
            ExternalIssueMapping.objects.create(
                item=item,
                github_id=20000 + i,  # Use different github_id range to avoid conflict
                number=100 + i,
                kind=ExternalIssueKind.ISSUE,
                state='open',
                html_url=f'https://github.com/testowner/testrepo/issues/{100+i}',
            )
        
        # Mock GitHub service
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.is_configured.return_value = True
        mock_service._get_repo_info.return_value = ('testowner', 'testrepo')
        mock_service.sync_mapping.return_value = self.mapping
        mock_service_class.return_value = mock_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_client.get_issue_timeline.return_value = []
        mock_client.get_issue.return_value = {
            'id': 12345,
            'number': 42,
            'state': 'open',
        }
        mock_service._get_client.return_value = mock_client
        
        # Mock Weaviate
        with patch('core.management.commands.github_sync_worker.is_available', return_value=False):
            out = StringIO()
            # Process with small batch size
            call_command('github_sync_worker', '--batch-size', '2', stdout=out)
        
        output = out.getvalue()
        
        # Should see multiple batches
        self.assertIn('Found 6 issue mappings to sync', output)
        self.assertIn('batch', output.lower())
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_dry_run_mode(self, mock_service_class):
        """Test that dry-run mode doesn't make changes."""
        # Mock GitHub service
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.is_configured.return_value = True
        mock_service._get_repo_info.return_value = ('testowner', 'testrepo')
        
        # Mock sync_mapping to change state
        def mock_sync_mapping(mapping):
            mapping.state = 'closed'
            mapping.save()
            return mapping
        
        mock_service.sync_mapping.side_effect = mock_sync_mapping
        mock_service_class.return_value = mock_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_client.get_issue_timeline.return_value = []
        mock_service._get_client.return_value = mock_client
        
        original_status = self.item.status
        
        # Mock Weaviate
        with patch('core.management.commands.github_sync_worker.is_available', return_value=False):
            out = StringIO()
            call_command('github_sync_worker', '--dry-run', stdout=out)
        
        output = out.getvalue()
        
        # Verify dry-run indicators
        self.assertIn('DRY RUN', output)
        self.assertIn('No changes were made', output)
        
        # In dry-run, sync_mapping is NOT called
        # So the status should not be updated
        # Note: The test mocks sync_mapping but in dry-run we skip it
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_filters_by_project(self, mock_service_class):
        """Test that command can filter by project ID."""
        # Create another project and item
        other_project = Project.objects.create(
            name='Other Project',
            github_owner='otherowner',
            github_repo='otherrepo',
        )
        other_item = Item.objects.create(
            project=other_project,
            title='Other Bug',
            type=self.item_type,
        )
        other_mapping = ExternalIssueMapping.objects.create(
            item=other_item,
            github_id=99999,
            number=999,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/otherowner/otherrepo/issues/999',
        )
        
        # Mock GitHub service
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.is_configured.return_value = True
        mock_service._get_repo_info.return_value = ('testowner', 'testrepo')
        mock_service.sync_mapping.return_value = self.mapping
        mock_service_class.return_value = mock_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_client.get_issue_timeline.return_value = []
        mock_client.get_issue.return_value = {'id': 12345, 'number': 42, 'state': 'open'}
        mock_service._get_client.return_value = mock_client
        
        # Mock Weaviate
        with patch('core.management.commands.github_sync_worker.is_available', return_value=False):
            out = StringIO()
            call_command(
                'github_sync_worker',
                '--project-id', str(self.project.id),
                stdout=out
            )
        
        output = out.getvalue()
        
        # Should only sync 1 mapping (not 2)
        self.assertIn('Found 1 issue mappings to sync', output)
        self.assertIn(f'project ID: {self.project.id}', output)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_does_not_update_status_for_closed_items(self, mock_service_class):
        """Test that command does not update status for items already in Closed status."""
        # Set item to Closed status
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        
        # Mock GitHub service
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.is_configured.return_value = True
        mock_service._get_repo_info.return_value = ('testowner', 'testrepo')
        mock_service.sync_mapping.side_effect = self._mock_sync_mapping_close
        mock_service_class.return_value = mock_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_client.get_issue_timeline.return_value = []
        mock_client.get_issue.return_value = {
            'id': 12345,
            'number': 42,
            'title': 'Test Issue',
            'body': 'Test body',
            'state': 'closed',
        }
        mock_service._get_client.return_value = mock_client
        
        # Mock Weaviate
        with patch('core.management.commands.github_sync_worker.is_available', return_value=False):
            out = StringIO()
            call_command('github_sync_worker', stdout=out)
        
        # Reload item
        self.item.refresh_from_db()
        
        # Verify status was NOT updated (remains Closed)
        self.assertEqual(self.item.status, ItemStatus.CLOSED)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_updates_status_for_non_closed_items(self, mock_service_class):
        """Test that command still updates status for items not in Closed status."""
        # Set item to Working status (not Closed)
        self.item.status = ItemStatus.WORKING
        self.item.save()
        
        # Mock GitHub service
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.is_configured.return_value = True
        mock_service._get_repo_info.return_value = ('testowner', 'testrepo')
        mock_service.sync_mapping.side_effect = self._mock_sync_mapping_close
        mock_service_class.return_value = mock_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_client.get_issue_timeline.return_value = []
        mock_client.get_issue.return_value = {
            'id': 12345,
            'number': 42,
            'title': 'Test Issue',
            'body': 'Test body',
            'state': 'closed',
        }
        mock_service._get_client.return_value = mock_client
        
        # Mock Weaviate
        with patch('core.management.commands.github_sync_worker.is_available', return_value=False):
            out = StringIO()
            call_command('github_sync_worker', stdout=out)
        
        # Reload item
        self.item.refresh_from_db()
        
        # Verify status was updated to Testing
        self.assertEqual(self.item.status, ItemStatus.TESTING)


class GitHubSyncWorkerHelperMethodsTestCase(TestCase):
    """Test helper methods in the worker command."""
    
    def setUp(self):
        """Set up test data."""
        self.command = Command()
        
        # Create test project
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
            type=self.item_type,
            status=ItemStatus.WORKING,
        )
        
        # Create mapping
        self.mapping = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=12345,
            number=42,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testowner/testrepo/issues/42',
        )
    
    @patch('core.management.commands.github_sync_worker.exists_object')
    def test_should_push_to_weaviate_when_state_changed(self, mock_exists):
        """Test that _should_push_to_weaviate returns True when state changed."""
        mock_exists.return_value = True  # Object exists
        
        result = self.command._should_push_to_weaviate(self.mapping, state_changed=True)
        
        self.assertTrue(result)
    
    @patch('core.management.commands.github_sync_worker.exists_object')
    def test_should_push_to_weaviate_when_object_doesnt_exist(self, mock_exists):
        """Test that _should_push_to_weaviate returns True when object doesn't exist."""
        mock_exists.return_value = False  # Object doesn't exist
        
        result = self.command._should_push_to_weaviate(self.mapping, state_changed=False)
        
        self.assertTrue(result)
    
    @patch('core.management.commands.github_sync_worker.exists_object')
    def test_should_not_push_to_weaviate_when_no_change_and_exists(self, mock_exists):
        """Test that _should_push_to_weaviate returns False when no change and exists."""
        mock_exists.return_value = True  # Object exists
        
        result = self.command._should_push_to_weaviate(self.mapping, state_changed=False)
        
        self.assertFalse(result)
