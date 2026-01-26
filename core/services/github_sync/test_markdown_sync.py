"""
Tests for GitHub Markdown Sync Service.
"""

from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
import io
import base64

from core.models import (
    Project,
    Attachment,
    AttachmentLink,
    AttachmentRole,
)
from core.services.github.client import GitHubClient
from core.services.github_sync.markdown_sync import MarkdownSyncService

User = get_user_model()


class GitHubClientRepoContentTestCase(TestCase):
    """Test GitHub client repository content methods."""
    
    def setUp(self):
        """Set up test data."""
        self.client = GitHubClient(token='test_token')
    
    @patch('core.services.github.client.HTTPClient.get')
    def test_get_repository_contents_for_directory(self, mock_get):
        """Test getting repository contents for a directory."""
        # Mock API response for directory listing
        mock_get.return_value = [
            {'type': 'file', 'name': 'README.md', 'path': 'README.md', 'sha': 'abc123'},
            {'type': 'dir', 'name': 'docs', 'path': 'docs', 'sha': 'def456'},
        ]
        
        result = self.client.get_repository_contents('owner', 'repo', '')
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['name'], 'README.md')
        self.assertEqual(result[1]['type'], 'dir')
        mock_get.assert_called_once()
    
    @patch('core.services.github.client.HTTPClient.get')
    def test_get_repository_contents_for_file(self, mock_get):
        """Test getting repository contents for a single file."""
        # Mock API response for a file
        mock_get.return_value = {
            'type': 'file',
            'name': 'README.md',
            'path': 'README.md',
            'sha': 'abc123',
            'size': 100,
        }
        
        result = self.client.get_repository_contents('owner', 'repo', 'README.md')
        
        self.assertEqual(result['type'], 'file')
        self.assertEqual(result['name'], 'README.md')
    
    @patch('core.services.github.client.HTTPClient.get')
    def test_get_file_content(self, mock_get):
        """Test getting raw file content."""
        # Mock file content (base64 encoded)
        content = b"# Test Markdown\n\nThis is a test."
        encoded_content = base64.b64encode(content).decode('utf-8')
        
        mock_get.return_value = {
            'type': 'file',
            'name': 'README.md',
            'content': encoded_content,
            'encoding': 'base64',
        }
        
        result = self.client.get_file_content('owner', 'repo', 'README.md')
        
        self.assertEqual(result, content)
        mock_get.assert_called_once()


class MarkdownSyncServiceTestCase(TestCase):
    """Test markdown sync service."""
    
    def setUp(self):
        """Set up test data."""
        # Create test project
        self.project = Project.objects.create(
            name='Test Project',
            github_owner='testowner',
            github_repo='testrepo',
        )
        
        # Create mock GitHub client
        self.mock_client = MagicMock(spec=GitHubClient)
        self.service = MarkdownSyncService(github_client=self.mock_client)
    
    def test_find_markdown_files_in_root(self):
        """Test finding markdown files in repository root."""
        # Mock repository contents
        self.mock_client.get_repository_contents.return_value = [
            {'type': 'file', 'name': 'README.md', 'path': 'README.md', 'sha': 'abc123', 'size': 100},
            {'type': 'file', 'name': 'setup.py', 'path': 'setup.py', 'sha': 'def456', 'size': 200},
            {'type': 'file', 'name': 'CHANGELOG.md', 'path': 'CHANGELOG.md', 'sha': 'ghi789', 'size': 300},
        ]
        
        files = self.service._find_markdown_files('owner', 'repo')
        
        # Should find 2 markdown files
        self.assertEqual(len(files), 2)
        self.assertEqual(files[0]['name'], 'README.md')
        self.assertEqual(files[1]['name'], 'CHANGELOG.md')
    
    def test_find_markdown_files_recursively(self):
        """Test finding markdown files recursively in subdirectories."""
        # Mock root directory
        def mock_get_contents(owner, repo, path='', ref=None):
            if path == '':
                return [
                    {'type': 'file', 'name': 'README.md', 'path': 'README.md', 'sha': 'abc', 'size': 100},
                    {'type': 'dir', 'name': 'docs', 'path': 'docs', 'sha': 'def'},
                ]
            elif path == 'docs':
                return [
                    {'type': 'file', 'name': 'guide.md', 'path': 'docs/guide.md', 'sha': 'ghi', 'size': 200},
                ]
            return []
        
        self.mock_client.get_repository_contents.side_effect = mock_get_contents
        
        files = self.service._find_markdown_files('owner', 'repo')
        
        # Should find 2 markdown files (root + subdirectory)
        self.assertEqual(len(files), 2)
        paths = [f['path'] for f in files]
        self.assertIn('README.md', paths)
        self.assertIn('docs/guide.md', paths)
    
    @patch('core.services.github_sync.markdown_sync.upsert_instance')
    def test_create_attachment_for_new_file(self, mock_upsert):
        """Test creating attachment for a new markdown file."""
        # Mock file content
        content = b"# Test\n\nContent"
        self.mock_client.get_file_content.return_value = content
        
        # Mock repository contents
        self.mock_client.get_repository_contents.return_value = [
            {'type': 'file', 'name': 'README.md', 'path': 'README.md', 'sha': 'abc123', 'size': len(content)},
        ]
        
        # Sync project
        stats = self.service.sync_project_markdown_files(self.project)
        
        # Should create 1 attachment
        self.assertEqual(stats['files_found'], 1)
        self.assertEqual(stats['files_created'], 1)
        self.assertEqual(stats['files_updated'], 0)
        self.assertEqual(stats['files_skipped'], 0)
        
        # Verify attachment was created
        attachments = Attachment.objects.filter(github_repo_path__contains='testowner/testrepo')
        self.assertEqual(attachments.count(), 1)
        
        attachment = attachments.first()
        self.assertEqual(attachment.original_name, 'README.md')
        self.assertEqual(attachment.github_sha, 'abc123')
        self.assertEqual(attachment.github_repo_path, 'testowner/testrepo:README.md')
        self.assertIsNotNone(attachment.github_last_synced)
        
        # Verify attachment is linked to project
        links = AttachmentLink.objects.filter(attachment=attachment)
        self.assertEqual(links.count(), 1)
        self.assertEqual(links.first().target, self.project)
        self.assertEqual(links.first().role, AttachmentRole.PROJECT_FILE)
    
    @patch('core.services.github_sync.markdown_sync.upsert_instance')
    def test_skip_unchanged_file(self, mock_upsert):
        """Test skipping file when SHA hasn't changed."""
        # Create existing attachment
        content = b"# Test\n\nContent"
        file_obj = io.BytesIO(content)
        file_obj.name = 'README.md'
        
        from core.services.storage.service import AttachmentStorageService
        storage = AttachmentStorageService()
        existing_attachment = storage.store_attachment(
            file=file_obj,
            target=self.project,
            created_by=None,
        )
        existing_attachment.github_repo_path = 'testowner/testrepo:README.md'
        existing_attachment.github_sha = 'abc123'
        existing_attachment.save()
        
        # Mock repository with same SHA
        self.mock_client.get_repository_contents.return_value = [
            {'type': 'file', 'name': 'README.md', 'path': 'README.md', 'sha': 'abc123', 'size': len(content)},
        ]
        
        # Sync project
        stats = self.service.sync_project_markdown_files(self.project)
        
        # Should skip the file
        self.assertEqual(stats['files_found'], 1)
        self.assertEqual(stats['files_created'], 0)
        self.assertEqual(stats['files_updated'], 0)
        self.assertEqual(stats['files_skipped'], 1)
        
        # Should not download content
        self.mock_client.get_file_content.assert_not_called()
    
    @patch('core.services.github_sync.markdown_sync.upsert_instance')
    def test_update_changed_file(self, mock_upsert):
        """Test updating attachment when SHA has changed."""
        # Create existing attachment with old SHA
        old_content = b"# Old Content"
        file_obj = io.BytesIO(old_content)
        file_obj.name = 'README.md'
        
        from core.services.storage.service import AttachmentStorageService
        storage = AttachmentStorageService()
        existing_attachment = storage.store_attachment(
            file=file_obj,
            target=self.project,
            created_by=None,
        )
        existing_attachment.github_repo_path = 'testowner/testrepo:README.md'
        existing_attachment.github_sha = 'old_sha'
        existing_attachment.save()
        
        # Mock repository with new SHA and content
        new_content = b"# New Content\n\nUpdated"
        self.mock_client.get_repository_contents.return_value = [
            {'type': 'file', 'name': 'README.md', 'path': 'README.md', 'sha': 'new_sha', 'size': len(new_content)},
        ]
        self.mock_client.get_file_content.return_value = new_content
        
        # Sync project
        stats = self.service.sync_project_markdown_files(self.project)
        
        # Should update the file
        self.assertEqual(stats['files_found'], 1)
        self.assertEqual(stats['files_created'], 0)
        self.assertEqual(stats['files_updated'], 1)
        self.assertEqual(stats['files_skipped'], 0)
        
        # Verify attachment was updated
        existing_attachment.refresh_from_db()
        self.assertEqual(existing_attachment.github_sha, 'new_sha')
        self.assertEqual(existing_attachment.size_bytes, len(new_content))
    
    def test_sync_project_without_github_repo(self):
        """Test syncing project without GitHub repo configuration."""
        # Create project without GitHub repo
        project_no_repo = Project.objects.create(name='No Repo Project')
        
        stats = self.service.sync_project_markdown_files(project_no_repo)
        
        # Should return error
        self.assertEqual(len(stats['errors']), 1)
        self.assertIn('no GitHub repository', stats['errors'][0])
    
    def test_handle_api_errors_gracefully(self):
        """Test handling GitHub API errors without crashing."""
        # Mock API error
        self.mock_client.get_repository_contents.side_effect = Exception("API Error")
        
        stats = self.service.sync_project_markdown_files(self.project)
        
        # Should capture error
        self.assertEqual(len(stats['errors']), 1)
        self.assertIn('API Error', stats['errors'][0])
