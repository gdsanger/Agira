"""
Tests for project items tab filtering
"""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ProjectStatus
)


class ProjectItemsTabTestCase(TestCase):
    """Test cases for project items tab filtering"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation"
        )
        
        # Create test user and authenticate
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.client.login(username="testuser", password="testpass123")
        
        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key="bug",
            name="Bug"
        )
        
        # Create items with different statuses
        self.inbox_item = Item.objects.create(
            title="Inbox Item",
            description="This is an inbox item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.INBOX,
            organisation=self.org,
        )
        
        self.backlog_item = Item.objects.create(
            title="Backlog Item",
            description="This is a backlog item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            organisation=self.org,
        )
        
        self.working_item = Item.objects.create(
            title="Working Item",
            description="This is a working item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
            organisation=self.org,
        )
        
        self.closed_item = Item.objects.create(
            title="Closed Item",
            description="This is a closed item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.CLOSED,
            organisation=self.org,
        )
    
    def test_no_filter_shows_all_items(self):
        """Test that when no filter is applied, all items including Closed are shown"""
        response = self.client.get(reverse('project-items-tab', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        # Get all items from the paginator
        items = list(response.context['page_obj'].object_list)
        
        # Should show all 4 items
        self.assertEqual(len(items), 4)
        
        # Check that closed item is included
        item_titles = [item.title for item in items]
        self.assertIn("Closed Item", item_titles)
    
    def test_filter_by_closed_status_shows_only_closed_items(self):
        """Test that selecting Closed status filter shows only closed items"""
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'status': [ItemStatus.CLOSED]}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['page_obj'].object_list)
        
        # Should show only 1 item
        self.assertEqual(len(items), 1)
        
        # Should be the closed item
        self.assertEqual(items[0].title, "Closed Item")
        self.assertEqual(items[0].status, ItemStatus.CLOSED)
    
    def test_filter_by_inbox_status_shows_only_inbox_items(self):
        """Test that selecting Inbox status filter shows only inbox items"""
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'status': [ItemStatus.INBOX]}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['page_obj'].object_list)
        
        # Should show only 1 item
        self.assertEqual(len(items), 1)
        
        # Should be the inbox item
        self.assertEqual(items[0].title, "Inbox Item")
        self.assertEqual(items[0].status, ItemStatus.INBOX)
    
    def test_filter_by_multiple_statuses(self):
        """Test that selecting multiple statuses shows items with any of those statuses"""
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'status': [ItemStatus.INBOX, ItemStatus.WORKING]}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['page_obj'].object_list)
        
        # Should show 2 items
        self.assertEqual(len(items), 2)
        
        # Should be inbox and working items
        item_titles = {item.title for item in items}
        self.assertSetEqual(item_titles, {"Inbox Item", "Working Item"})
    
    def test_filter_excludes_closed_when_other_statuses_selected(self):
        """Test that when other statuses are selected, closed items are not shown"""
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'status': [ItemStatus.BACKLOG, ItemStatus.WORKING]}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['page_obj'].object_list)
        
        # Should show 2 items
        self.assertEqual(len(items), 2)
        
        # Should NOT include closed item
        item_titles = {item.title for item in items}
        self.assertNotIn("Closed Item", item_titles)
    
    def test_search_filter_works_with_status_filter(self):
        """Test that search filter works together with status filter"""
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'q': 'Closed', 'status': [ItemStatus.CLOSED]}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['page_obj'].object_list)
        
        # Should show only 1 item
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Closed Item")
    
    def test_context_contains_selected_statuses(self):
        """Test that selected statuses are passed to context"""
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'status': [ItemStatus.INBOX, ItemStatus.CLOSED]}
        )
        self.assertEqual(response.status_code, 200)
        
        selected = response.context['selected_statuses']
        self.assertIn(ItemStatus.INBOX, selected)
        self.assertIn(ItemStatus.CLOSED, selected)
    
    def test_context_contains_status_choices(self):
        """Test that all status choices are available in context"""
        response = self.client.get(reverse('project-items-tab', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        status_choices = response.context['status_choices']
        
        # Check that Closed is in the choices
        status_values = [choice[0] for choice in status_choices]
        self.assertIn(ItemStatus.CLOSED, status_values)
        self.assertIn(ItemStatus.INBOX, status_values)
        self.assertIn(ItemStatus.BACKLOG, status_values)
        self.assertIn(ItemStatus.WORKING, status_values)
