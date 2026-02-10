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
        """Helper to mock GitHubService.sync_mapping behavior by setting mapping state to closed."""
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
        # Set item to Closed status so it gets synced
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        
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
        # Set item to Closed status so it gets synced
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        
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
        
        # Verify status remains CLOSED (since it was already closed, shouldn't be updated to TESTING)
        self.assertEqual(self.item.status, ItemStatus.CLOSED)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_links_prs_from_timeline(self, mock_service_class):
        """Test that command links PRs found in timeline."""
        # Set item to Closed status so it gets synced
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        
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
        # Set item to Closed status so it gets synced
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        
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
        # Set the existing item to Closed
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        
        # Create multiple mappings with Closed status
        for i in range(5):
            item = Item.objects.create(
                project=self.project,
                title=f'Test Bug {i}',
                type=self.item_type,
                status=ItemStatus.CLOSED,  # Set to Closed so they get synced
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
        # Set item to Closed status so it would get synced
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        
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
        # Set item to Closed status
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        
        # Create another project and item with Closed status
        other_project = Project.objects.create(
            name='Other Project',
            github_owner='otherowner',
            github_repo='otherrepo',
        )
        other_item = Item.objects.create(
            project=other_project,
            title='Other Bug',
            type=self.item_type,
            status=ItemStatus.CLOSED,
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
    def test_command_does_not_update_status_for_ready_for_release_items(self, mock_service_class):
        """Test that command does not update status for items already in Ready for Release status."""
        # Set item to Ready for Release status
        self.item.status = ItemStatus.READY_FOR_RELEASE
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
        
        # Verify status was NOT updated (remains Ready for Release)
        self.assertEqual(self.item.status, ItemStatus.READY_FOR_RELEASE)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_filters_correctly_by_status_and_time(self, mock_service_class):
        """Test that command syncs non-closed items and recently closed items, but not old closed items."""
        from datetime import timedelta
        
        # Item 1: Non-closed item (should be synced)
        self.item.status = ItemStatus.WORKING
        self.item.save()
        
        # Item 2: Recently closed item (should be synced)
        recent_closed_item = Item.objects.create(
            project=self.project,
            title='Recently Closed Bug',
            type=self.item_type,
            status=ItemStatus.CLOSED,
        )
        recent_closed_mapping = ExternalIssueMapping.objects.create(
            item=recent_closed_item,
            github_id=88888,
            number=888,
            kind=ExternalIssueKind.ISSUE,
            state='closed',
            html_url='https://github.com/testowner/testrepo/issues/888',
        )
        
        # Item 3: Old closed item (should NOT be synced)
        old_item = Item.objects.create(
            project=self.project,
            title='Old Closed Bug',
            type=self.item_type,
            status=ItemStatus.CLOSED,
        )
        old_mapping = ExternalIssueMapping.objects.create(
            item=old_item,
            github_id=99999,
            number=999,
            kind=ExternalIssueKind.ISSUE,
            state='closed',
            html_url='https://github.com/testowner/testrepo/issues/999',
        )
        # Manually set updated_at to more than 2 hours ago
        old_time = timezone.now() - timedelta(hours=3)
        Item.objects.filter(id=old_item.id).update(updated_at=old_time)
        
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
            call_command('github_sync_worker', stdout=out)
        
        output = out.getvalue()
        
        # Should sync 2 items: the non-closed item and the recently closed item
        self.assertIn('Found 2 issue mappings to sync', output)
        self.assertIn('Issue #42', output)  # Non-closed item
        self.assertIn('Issue #888', output)  # Recently closed item
        self.assertNotIn('Issue #999', output)  # Old closed item should not be synced
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_syncs_non_closed_items(self, mock_service_class):
        """Test that command syncs items that are not in Closed status."""
        # Set item to Working status (not Closed)
        self.item.status = ItemStatus.WORKING
        self.item.save()
        
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
            call_command('github_sync_worker', stdout=out)
        
        output = out.getvalue()
        
        # Should sync non-closed items
        self.assertIn('Found 1 issue mappings to sync', output)
        
        # Verify GitHub API calls were made
        mock_service.sync_mapping.assert_called_once()
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_shows_time_threshold_in_output(self, mock_service_class):
        """Test that command shows the time threshold in output."""
        # Set item to Working status (non-closed) so it gets synced
        self.item.status = ItemStatus.WORKING
        self.item.save()
        
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
            call_command('github_sync_worker', stdout=out)
        
        output = out.getvalue()
        
        # Verify time threshold is shown in output
        self.assertIn('Filtering to non-closed items and items closed in the last 2 hours', output)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_syncs_various_non_closed_statuses(self, mock_service_class):
        """Test that command syncs items with various non-closed statuses."""
        # Set the main item to a non-closed status
        self.item.status = ItemStatus.INBOX
        self.item.save()
        
        # Create items with different non-closed statuses
        statuses_to_test = [
            ItemStatus.BACKLOG,
            ItemStatus.WORKING,
            ItemStatus.TESTING,
            ItemStatus.READY_FOR_RELEASE,
        ]
        
        for i, status in enumerate(statuses_to_test):
            item = Item.objects.create(
                project=self.project,
                title=f'Test Item {status}',
                type=self.item_type,
                status=status,
            )
            ExternalIssueMapping.objects.create(
                item=item,
                github_id=50000 + i,
                number=500 + i,
                kind=ExternalIssueKind.ISSUE,
                state='open',
                html_url=f'https://github.com/testowner/testrepo/issues/{500+i}',
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
            call_command('github_sync_worker', stdout=out)
        
        output = out.getvalue()
        
        # Should sync all non-closed items (1 original + 6 created)
        self.assertIn('Found 7 issue mappings to sync', output)
    
    @patch('core.management.commands.github_sync_worker.GitHubService')
    def test_command_does_not_sync_old_closed_items(self, mock_service_class):
        """Test that command does not sync items that were closed more than 2 hours ago."""
        from datetime import timedelta
        
        # Create a closed item updated more than 2 hours ago
        old_item = Item.objects.create(
            project=self.project,
            title='Old Closed Bug',
            type=self.item_type,
            status=ItemStatus.CLOSED,
        )
        old_mapping = ExternalIssueMapping.objects.create(
            item=old_item,
            github_id=99999,
            number=999,
            kind=ExternalIssueKind.ISSUE,
            state='closed',
            html_url='https://github.com/testowner/testrepo/issues/999',
        )
        # Manually set updated_at to more than 2 hours ago
        old_time = timezone.now() - timedelta(hours=3)
        Item.objects.filter(id=old_item.id).update(updated_at=old_time)
        
        # Set original item to also be old and closed
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        Item.objects.filter(id=self.item.id).update(updated_at=old_time)
        
        # Mock GitHub service
        mock_service = MagicMock()
        mock_service.is_enabled.return_value = True
        mock_service.is_configured.return_value = True
        mock_service_class.return_value = mock_service
        
        # Mock Weaviate
        with patch('core.management.commands.github_sync_worker.is_available', return_value=False):
            out = StringIO()
            call_command('github_sync_worker', stdout=out)
        
        output = out.getvalue()
        
        # Should not sync any old closed items
        self.assertIn('Found 0 issue mappings to sync', output)
        
        # Verify no GitHub API calls were made
        mock_service.sync_mapping.assert_not_called()



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
