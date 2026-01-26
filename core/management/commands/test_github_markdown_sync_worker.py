"""
Tests for GitHub markdown sync worker command.
"""

from unittest.mock import Mock, patch, MagicMock
from io import StringIO
from django.test import TestCase
from django.core.management import call_command
from django.contrib.auth import get_user_model

from core.models import (
    GitHubConfiguration,
    Project,
    Attachment,
)
from core.management.commands.github_markdown_sync_worker import Command

User = get_user_model()


class GitHubMarkdownSyncWorkerTestCase(TestCase):
    """Test GitHub markdown sync worker command."""
    
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
    
    def test_command_fails_when_github_disabled(self):
        """Test that command fails when GitHub is disabled."""
        self.config.enable_github = False
        self.config.save()
        
        from django.core.management.base import CommandError
        
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command('github_markdown_sync_worker', stdout=out, stderr=out)
    
    def test_command_fails_when_github_not_configured(self):
        """Test that command fails when GitHub is not configured."""
        self.config.github_token = ''
        self.config.save()
        
        from django.core.management.base import CommandError
        
        out = StringIO()
        with self.assertRaises(CommandError):
            call_command('github_markdown_sync_worker', stdout=out, stderr=out)
    
    @patch('core.management.commands.github_markdown_sync_worker.GitHubService')
    @patch('core.management.commands.github_markdown_sync_worker.MarkdownSyncService')
    def test_command_syncs_markdown_files(self, mock_markdown_service_class, mock_github_service_class):
        """Test that command syncs markdown files from GitHub repos."""
        # Mock GitHub service
        mock_github_service = MagicMock()
        mock_github_service.is_enabled.return_value = True
        mock_github_service.is_configured.return_value = True
        mock_github_service_class.return_value = mock_github_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_github_service._get_client.return_value = mock_client
        
        # Mock MarkdownSyncService
        mock_markdown_service = MagicMock()
        mock_markdown_service.sync_project_markdown_files.return_value = {
            'files_found': 3,
            'files_created': 2,
            'files_updated': 1,
            'files_skipped': 0,
            'errors': [],
        }
        mock_markdown_service_class.return_value = mock_markdown_service
        
        out = StringIO()
        call_command('github_markdown_sync_worker', stdout=out)
        
        output = out.getvalue()
        
        # Verify output
        self.assertIn('Found 1 projects with GitHub repositories', output)
        self.assertIn('Test Project', output)
        self.assertIn('testowner/testrepo', output)
        self.assertIn('Found 3 .md files', output)
        self.assertIn('2 created', output)
        self.assertIn('1 updated', output)
        self.assertIn('Projects processed: 1', output)
        self.assertIn('Files found: 3', output)
        self.assertIn('Files created: 2', output)
        self.assertIn('Files updated: 1', output)
        
        # Verify markdown service was called
        mock_markdown_service.sync_project_markdown_files.assert_called_once_with(self.project)
    
    @patch('core.management.commands.github_markdown_sync_worker.GitHubService')
    def test_command_dry_run_mode(self, mock_github_service_class):
        """Test that dry-run mode doesn't make changes."""
        # Mock GitHub service
        mock_github_service = MagicMock()
        mock_github_service.is_enabled.return_value = True
        mock_github_service.is_configured.return_value = True
        mock_github_service_class.return_value = mock_github_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_github_service._get_client.return_value = mock_client
        
        out = StringIO()
        call_command('github_markdown_sync_worker', '--dry-run', stdout=out)
        
        output = out.getvalue()
        
        # Verify dry-run indicators
        self.assertIn('DRY RUN', output)
        self.assertIn('No changes were made', output)
        self.assertIn('[DRY RUN] Would sync markdown files', output)
    
    @patch('core.management.commands.github_markdown_sync_worker.GitHubService')
    def test_command_filters_by_project(self, mock_github_service_class):
        """Test that command can filter by project ID."""
        # Create another project
        other_project = Project.objects.create(
            name='Other Project',
            github_owner='otherowner',
            github_repo='otherrepo',
        )
        
        # Mock GitHub service
        mock_github_service = MagicMock()
        mock_github_service.is_enabled.return_value = True
        mock_github_service.is_configured.return_value = True
        mock_github_service_class.return_value = mock_github_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_github_service._get_client.return_value = mock_client
        
        out = StringIO()
        call_command(
            'github_markdown_sync_worker',
            '--project-id', str(self.project.id),
            '--dry-run',
            stdout=out
        )
        
        output = out.getvalue()
        
        # Should only process the filtered project
        self.assertIn('Found 1 projects with GitHub repositories', output)
        self.assertIn('Test Project', output)
        self.assertNotIn('Other Project', output)
    
    @patch('core.management.commands.github_markdown_sync_worker.GitHubService')
    @patch('core.management.commands.github_markdown_sync_worker.MarkdownSyncService')
    def test_command_handles_errors_gracefully(self, mock_markdown_service_class, mock_github_service_class):
        """Test that command handles errors without crashing."""
        # Mock GitHub service
        mock_github_service = MagicMock()
        mock_github_service.is_enabled.return_value = True
        mock_github_service.is_configured.return_value = True
        mock_github_service_class.return_value = mock_github_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_github_service._get_client.return_value = mock_client
        
        # Mock MarkdownSyncService to raise an error
        mock_markdown_service = MagicMock()
        mock_markdown_service.sync_project_markdown_files.side_effect = Exception("API Error")
        mock_markdown_service_class.return_value = mock_markdown_service
        
        out = StringIO()
        call_command('github_markdown_sync_worker', stdout=out)
        
        output = out.getvalue()
        
        # Should capture error without crashing
        self.assertIn('Error', output)
        self.assertIn('Errors: 1', output)
    
    @patch('core.management.commands.github_markdown_sync_worker.GitHubService')
    def test_command_skips_projects_without_github_repo(self, mock_github_service_class):
        """Test that command skips projects without GitHub repo configuration."""
        # Create project without GitHub repo
        project_no_repo = Project.objects.create(name='No Repo Project')
        
        # Mock GitHub service
        mock_github_service = MagicMock()
        mock_github_service.is_enabled.return_value = True
        mock_github_service.is_configured.return_value = True
        mock_github_service_class.return_value = mock_github_service
        
        out = StringIO()
        call_command('github_markdown_sync_worker', stdout=out)
        
        output = out.getvalue()
        
        # Should only process projects with GitHub repos
        self.assertIn('Found 1 projects with GitHub repositories', output)
        self.assertNotIn('No Repo Project', output)


class MarkdownSyncIntegrationTestCase(TestCase):
    """Integration test for markdown file sync and Weaviate serialization."""
    
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
    
    @patch('core.management.commands.github_markdown_sync_worker.GitHubService')
    @patch('core.management.commands.github_markdown_sync_worker.MarkdownSyncService')
    def test_markdown_files_synced_with_content_to_weaviate(
        self,
        mock_markdown_service_class,
        mock_github_service_class
    ):
        """Test that synced markdown files have content (not filename) in Weaviate."""
        import io
        from core.services.storage.service import AttachmentStorageService
        from core.services.weaviate.serializers import _serialize_attachment
        
        # Mock GitHub service
        mock_github_service = MagicMock()
        mock_github_service.is_enabled.return_value = True
        mock_github_service.is_configured.return_value = True
        mock_github_service_class.return_value = mock_github_service
        
        # Mock GitHub client
        mock_client = MagicMock()
        mock_github_service._get_client.return_value = mock_client
        
        # Mock MarkdownSyncService to actually create attachments
        mock_markdown_service = MagicMock()
        
        # Define the markdown content that would be synced
        markdown_content = """# Project Documentation

This is the main README for the project.

## Features

- Feature 1: Markdown sync from GitHub
- Feature 2: Weaviate indexing
- Feature 3: Full-text search

## Installation

Run `pip install -r requirements.txt` to install dependencies.
"""
        
        # Create a real attachment with markdown content
        storage = AttachmentStorageService()
        file_obj = io.BytesIO(markdown_content.encode('utf-8'))
        file_obj.name = 'README.md'
        
        attachment = storage.store_attachment(
            file=file_obj,
            target=self.project,
            created_by=None,
        )
        attachment.content_type = 'text/markdown'
        attachment.github_repo_path = 'testowner/testrepo:README.md'
        attachment.github_sha = 'abc123'
        attachment.save()
        
        # Mock markdown service to return this attachment
        mock_markdown_service.sync_project_markdown_files.return_value = {
            'files_found': 1,
            'files_created': 1,
            'files_updated': 0,
            'files_skipped': 0,
            'errors': [],
        }
        mock_markdown_service_class.return_value = mock_markdown_service
        
        # Run the sync command
        out = StringIO()
        call_command('github_markdown_sync_worker', stdout=out)
        
        # Now verify that the attachment serialization includes the full content
        serialized = _serialize_attachment(attachment)
        
        # The text field should contain the actual markdown content
        self.assertIn('# Project Documentation', serialized['text'])
        self.assertIn('This is the main README for the project.', serialized['text'])
        self.assertIn('## Features', serialized['text'])
        self.assertIn('Feature 1: Markdown sync from GitHub', serialized['text'])
        self.assertIn('## Installation', serialized['text'])
        self.assertIn('pip install -r requirements.txt', serialized['text'])
        
        # The text field should NOT contain just the filename
        self.assertNotIn('Attachment: README.md', serialized['text'])
        
        # Verify other fields are correct
        self.assertEqual(serialized['type'], 'attachment')
        self.assertEqual(serialized['title'], 'README.md')
        self.assertEqual(serialized['mime_type'], 'text/markdown')
