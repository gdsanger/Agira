"""
Tests for multiple GitHub issue creation (follow-up issues) functionality.
"""

from unittest.mock import Mock, patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from datetime import datetime

from core.models import (
    GitHubConfiguration,
    Project,
    Item,
    ItemType,
    ItemStatus,
    ExternalIssueMapping,
    ExternalIssueKind,
)
from core.services.github.service import GitHubService

User = get_user_model()


class FollowupGitHubIssueTestCase(TestCase):
    """Test follow-up GitHub issue creation functionality."""
    
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
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        # Create Copilot user for assignments
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
        
        # Create test client
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_first_issue_creation_no_notes_required(self, mock_create_issue):
        """Test that first issue creation doesn't require notes."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Original description',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        mock_create_issue.return_value = {
            'id': 12345,
            'number': 1,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/1',
            'title': 'Test Item',
            'assignees': [],
        }
        
        # Create first issue without notes
        url = reverse('item-create-github-issue', args=[item.id])
        response = self.client.post(url)
        
        # Should succeed
        self.assertEqual(response.status_code, 200)
        
        # Check that mapping was created
        self.assertEqual(ExternalIssueMapping.objects.filter(item=item).count(), 1)
        
        # Description should not be modified for first issue
        item.refresh_from_db()
        self.assertEqual(item.description, 'Original description')
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_followup_issue_requires_notes(self, mock_create_issue):
        """Test that follow-up issue creation requires notes."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Original description',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        # Create first issue mapping
        ExternalIssueMapping.objects.create(
            item=item,
            github_id=12345,
            number=1,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testowner/testrepo/issues/1',
        )
        
        # Try to create follow-up issue without notes
        url = reverse('item-create-github-issue', args=[item.id])
        response = self.client.post(url)
        
        # Should fail with 400
        self.assertEqual(response.status_code, 400)
        self.assertIn('Notes are required', response.content.decode())
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_followup_issue_updates_description(self, mock_create_issue):
        """Test that follow-up issue creation updates item description with notes and references."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Original description',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        # Create first issue mapping
        ExternalIssueMapping.objects.create(
            item=item,
            github_id=12345,
            number=1,
            kind=ExternalIssueKind.ISSUE,
            state='closed',
            html_url='https://github.com/testowner/testrepo/issues/1',
        )
        
        # Create a PR mapping
        ExternalIssueMapping.objects.create(
            item=item,
            github_id=67890,
            number=5,
            kind=ExternalIssueKind.PR,
            state='merged',
            html_url='https://github.com/testowner/testrepo/pull/5',
        )
        
        mock_create_issue.return_value = {
            'id': 23456,
            'number': 2,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/2',
            'title': 'Test Item',
            'assignees': [],
        }
        
        # Create follow-up issue with notes
        url = reverse('item-create-github-issue', args=[item.id])
        notes = 'Additional work needed to fix edge cases'
        response = self.client.post(url, {'notes': notes})
        
        # Should succeed
        self.assertEqual(response.status_code, 200)
        
        # Check that new mapping was created
        self.assertEqual(ExternalIssueMapping.objects.filter(item=item, kind=ExternalIssueKind.ISSUE).count(), 2)
        
        # Check that description was updated
        item.refresh_from_db()
        self.assertIn('## Original Item Issue Text', item.description)
        self.assertIn('Original description', item.description)
        self.assertIn('## Hinweise und Änderungen', item.description)
        self.assertIn(notes, item.description)
        self.assertIn('### Siehe folgende Issues und PRs', item.description)
        # Now the list should include all issues: #1, #2 (newly created), and #5
        self.assertIn('#1', item.description)
        self.assertIn('#2', item.description)  # Newly created issue should be included
        self.assertIn('#5', item.description)
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_followup_issue_preserves_existing_headers(self, mock_create_issue):
        """Test that follow-up issue doesn't duplicate headers if they already exist."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='## Original Item Issue Text\nOriginal description',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        # Create first issue mapping
        ExternalIssueMapping.objects.create(
            item=item,
            github_id=12345,
            number=1,
            kind=ExternalIssueKind.ISSUE,
            state='closed',
            html_url='https://github.com/testowner/testrepo/issues/1',
        )
        
        mock_create_issue.return_value = {
            'id': 23456,
            'number': 2,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/2',
            'title': 'Test Item',
            'assignees': [],
        }
        
        # Create follow-up issue with notes
        url = reverse('item-create-github-issue', args=[item.id])
        notes = 'Second follow-up'
        response = self.client.post(url, {'notes': notes})
        
        # Should succeed
        self.assertEqual(response.status_code, 200)
        
        # Check that description has only one "Original Item Issue Text" header
        item.refresh_from_db()
        self.assertEqual(item.description.count('## Original Item Issue Text'), 1)
        self.assertIn(notes, item.description)
    
    @patch('core.services.github.client.GitHubClient.create_issue')
    def test_multiple_followup_issues(self, mock_create_issue):
        """Test creating multiple follow-up issues for the same item."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Original description',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        # Create first issue
        mock_create_issue.return_value = {
            'id': 12345,
            'number': 1,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/1',
            'title': 'Test Item',
            'assignees': [],
        }
        url = reverse('item-create-github-issue', args=[item.id])
        self.client.post(url)
        
        # Create second issue with notes
        mock_create_issue.return_value = {
            'id': 23456,
            'number': 2,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/2',
            'title': 'Test Item',
            'assignees': [],
        }
        response = self.client.post(url, {'notes': 'First follow-up'})
        self.assertEqual(response.status_code, 200)
        
        # Create third issue with notes
        mock_create_issue.return_value = {
            'id': 34567,
            'number': 3,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/3',
            'title': 'Test Item',
            'assignees': [],
        }
        response = self.client.post(url, {'notes': 'Second follow-up'})
        self.assertEqual(response.status_code, 200)
        
        # Check that all three issues were created
        self.assertEqual(ExternalIssueMapping.objects.filter(item=item, kind=ExternalIssueKind.ISSUE).count(), 3)
        
        # Check that description contains all notes
        item.refresh_from_db()
        self.assertIn('First follow-up', item.description)
        self.assertIn('Second follow-up', item.description)
    
    def test_github_tab_shows_followup_button_when_issue_exists(self):
        """Test that GitHub tab shows follow-up button when item has existing issues."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Original description',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        # Create issue mapping
        ExternalIssueMapping.objects.create(
            item=item,
            github_id=12345,
            number=1,
            kind=ExternalIssueKind.ISSUE,
            state='closed',
            html_url='https://github.com/testowner/testrepo/issues/1',
        )
        
        # Load GitHub tab
        url = reverse('item-github-tab', args=[item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        
        # Should show follow-up button instead of regular create button
        self.assertIn('Create Follow-up GitHub Issue', content)
        self.assertIn('followupIssueModal', content)
    
    def test_github_tab_shows_regular_button_when_no_issue_exists(self):
        """Test that GitHub tab shows regular button when item has no issues."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Original description',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        # Load GitHub tab
        url = reverse('item-github-tab', args=[item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        
        # Should show regular create button (not the follow-up button)
        self.assertIn('Create GitHub Issue', content)
        # The modal is always present in the template, but the button to trigger it should not be visible
        self.assertNotIn('data-bs-toggle="modal" data-bs-target="#followupIssueModal"', content)
    
    def test_date_format_in_description_update(self):
        """Test that date is formatted correctly in German format (DD.MM.YYYY)."""
        from core.views import _append_followup_notes_to_item
        from datetime import datetime
        import re
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Original description',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        _append_followup_notes_to_item(item, 'Test notes')
        
        # Check date format - should match DD.MM.YYYY pattern
        item.refresh_from_db()
        # Pattern for German date format
        date_pattern = r'## Hinweise und Änderungen \d{2}\.\d{2}\.\d{4}'
        self.assertRegex(item.description, date_pattern)
        self.assertIn('Test notes', item.description)
    
    def test_empty_description_handling(self):
        """Test that function handles items with empty/None description correctly."""
        from core.views import _append_followup_notes_to_item
        
        # Test with empty string description
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='',  # Empty string instead of None
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        # Create a mapping for references
        ExternalIssueMapping.objects.create(
            item=item,
            github_id=12345,
            number=1,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testowner/testrepo/issues/1',
        )
        
        # Should not raise an error
        _append_followup_notes_to_item(item, 'Notes for empty item')
        
        # Check that description was created correctly
        item.refresh_from_db()
        self.assertIsNotNone(item.description)
        self.assertIn('## Hinweise und Änderungen', item.description)
        self.assertIn('Notes for empty item', item.description)
        self.assertIn('#1', item.description)
