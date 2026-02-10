"""
Tests for Kanban view.
"""
from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    Item, ItemStatus, ItemType, Project, User, Release, 
    Organisation, ExternalIssueMapping, ExternalIssueKind
)


class KanbanViewTestCase(TestCase):
    """Tests for the Kanban board view."""

    def setUp(self):
        """Set up test data."""
        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        # Create organization
        self.org = Organisation.objects.create(
            name='Test Org',
            short='TO'
        )
        
        # Link user to organisation
        from core.models import UserOrganisation
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test Description',
            github_owner='testowner',
            github_repo='testrepo'
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug'
        )
        
        # Create release
        self.release = Release.objects.create(
            project=self.project,
            name='v1.0',
            version='1.0.0',
            planned_date='2024-12-31'
        )
        
        # Create items with different statuses
        self.items = {}
        for status in [ItemStatus.INBOX, ItemStatus.BACKLOG, ItemStatus.WORKING, 
                      ItemStatus.TESTING, ItemStatus.READY_FOR_RELEASE, ItemStatus.CLOSED]:
            item = Item.objects.create(
                project=self.project,
                title=f'Item {status.label}',
                description=f'Description for {status.label}',
                type=self.item_type,
                status=status,
                organisation=self.org,
                requester=self.user,
                solution_release=self.release if status != ItemStatus.CLOSED else None
            )
            self.items[status] = item
            
            # Add GitHub issue mapping for inbox item
            if status == ItemStatus.INBOX:
                ExternalIssueMapping.objects.create(
                    item=item,
                    github_id=12345,
                    number=123,
                    kind=ExternalIssueKind.ISSUE,
                    state='open',
                    html_url='https://github.com/testowner/testrepo/issues/123'
                )
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')

    def test_kanban_view_accessible(self):
        """Test that Kanban view is accessible."""
        response = self.client.get(reverse('items-kanban'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'items_kanban.html')

    def test_kanban_excludes_closed_items(self):
        """Test that Kanban view excludes closed items."""
        response = self.client.get(reverse('items-kanban'))
        items_by_status = response.context['items_by_status']
        
        # Verify closed status column exists but is empty or not in items
        all_items = []
        for status_items in items_by_status.values():
            all_items.extend(status_items)
        
        # Closed item should not be in the items
        closed_item = self.items[ItemStatus.CLOSED]
        self.assertNotIn(closed_item, all_items)
        
        # Non-closed items should be present
        for status in [ItemStatus.INBOX, ItemStatus.BACKLOG, ItemStatus.WORKING]:
            self.assertIn(self.items[status], all_items)

    def test_kanban_groups_items_by_status(self):
        """Test that items are correctly grouped by status."""
        response = self.client.get(reverse('items-kanban'))
        items_by_status = response.context['items_by_status']
        
        # Check that each status group contains the right item
        for status in [ItemStatus.INBOX, ItemStatus.BACKLOG, ItemStatus.WORKING, 
                      ItemStatus.TESTING, ItemStatus.READY_FOR_RELEASE]:
            status_items = items_by_status[status]
            expected_item = self.items[status]
            self.assertIn(expected_item, status_items)

    def test_kanban_filter_by_project(self):
        """Test filtering by project."""
        # Create another project and item
        other_project = Project.objects.create(name='Other Project')
        other_item = Item.objects.create(
            project=other_project,
            title='Other Item',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Filter by original project
        response = self.client.get(reverse('items-kanban'), {'project': self.project.id})
        all_items = []
        for status_items in response.context['items_by_status'].values():
            all_items.extend(status_items)
        
        # Should include items from original project
        self.assertIn(self.items[ItemStatus.INBOX], all_items)
        # Should exclude items from other project
        self.assertNotIn(other_item, all_items)

    def test_kanban_filter_by_release(self):
        """Test filtering by release."""
        # Create another release and item
        other_release = Release.objects.create(
            project=self.project,
            name='v2.0',
            version='2.0.0'
        )
        other_item = Item.objects.create(
            project=self.project,
            title='Other Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
            solution_release=other_release
        )
        
        # Filter by original release
        response = self.client.get(reverse('items-kanban'), {'solution_release': self.release.id})
        all_items = []
        for status_items in response.context['items_by_status'].values():
            all_items.extend(status_items)
        
        # Should include items from original release
        self.assertIn(self.items[ItemStatus.INBOX], all_items)
        # Should exclude items from other release
        self.assertNotIn(other_item, all_items)

    def test_kanban_search_filter(self):
        """Test search filtering by title."""
        response = self.client.get(reverse('items-kanban'), {'q': 'Inbox'})
        all_items = []
        for status_items in response.context['items_by_status'].values():
            all_items.extend(status_items)
        
        # Should include inbox item (title contains "Inbox")
        self.assertIn(self.items[ItemStatus.INBOX], all_items)
        # Should exclude items without "Inbox" in title
        self.assertNotIn(self.items[ItemStatus.BACKLOG], all_items)

    def test_kanban_displays_github_issue_link(self):
        """Test that GitHub issue links are displayed for items with external mappings."""
        response = self.client.get(reverse('items-kanban'))
        content = response.content.decode('utf-8')
        
        # Check that GitHub issue link is in the response
        self.assertIn('https://github.com/testowner/testrepo/issues/123', content)
        self.assertIn('#123', content)

    def test_kanban_displays_release_info(self):
        """Test that release information is displayed."""
        response = self.client.get(reverse('items-kanban'))
        content = response.content.decode('utf-8')
        
        # Check that release info is in the response
        self.assertIn('1.0.0', content)
        self.assertIn('31.12.2024', content)

    def test_kanban_login_required(self):
        """Test that Kanban view requires login."""
        self.client.logout()
        response = self.client.get(reverse('items-kanban'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
        self.assertIn('/login/', response.url)
