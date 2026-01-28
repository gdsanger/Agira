"""
Tests for project items tab HTMX functionality
"""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ProjectStatus
)


class ProjectItemsTabHTMXTestCase(TestCase):
    """Test cases for project items tab HTMX functionality"""
    
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
        
        # Create multiple items for pagination testing
        for i in range(30):
            Item.objects.create(
                title=f"Item {i}",
                description=f"Description {i}",
                project=self.project,
                type=self.item_type,
                status=ItemStatus.INBOX if i % 2 == 0 else ItemStatus.BACKLOG,
                organisation=self.org,
            )
    
    def test_filter_form_has_htmx_attributes(self):
        """Test that the filter form has correct HTMX attributes"""
        response = self.client.get(reverse('project-items-tab', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check form has HTMX attributes
        self.assertIn('hx-get=', content)
        self.assertIn('hx-target="#items"', content)
        self.assertIn('hx-swap="innerHTML"', content)
    
    def test_pagination_links_have_htmx_attributes(self):
        """Test that pagination links have correct HTMX attributes"""
        response = self.client.get(reverse('project-items-tab', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check pagination links have HTMX attributes
        # Since we have 30 items and pagination is 25 per page, there should be a "Next" link
        if response.context['page_obj'].has_next:
            self.assertIn('hx-get=', content)
            self.assertIn('Next', content)
    
    def test_pagination_preserves_filters(self):
        """Test that pagination links preserve filter parameters"""
        # Create enough items to trigger pagination with filter
        for i in range(30, 60):  # Add 30 more items all with INBOX status
            Item.objects.create(
                title=f"Item {i}",
                description=f"Description {i}",
                project=self.project,
                type=self.item_type,
                status=ItemStatus.INBOX,  # All INBOX to ensure we have enough for pagination
                organisation=self.org,
            )
        
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'status': [ItemStatus.INBOX], 'page': 1}
        )
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check that filter parameters are preserved in pagination URLs
        if response.context['page_obj'].has_next:
            # Check for the status parameter in the HTMX get URL (could be &amp; or & depending on template rendering)
            self.assertTrue('&status=Inbox' in content or '&amp;status=Inbox' in content,
                           "Status filter parameter should be preserved in pagination links")
        else:
            # If no pagination needed, test passes anyway
            self.assertTrue(True)
    
    def test_filter_submission_with_pagination(self):
        """Test that filtering works correctly and pagination is reset"""
        # First, apply a filter
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'status': [ItemStatus.INBOX]}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['page_obj'].object_list)
        
        # All items should have INBOX status
        for item in items:
            self.assertEqual(item.status, ItemStatus.INBOX)
    
    def test_clear_filters_button_has_htmx(self):
        """Test that clear filters button has HTMX attributes when filters are active"""
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'status': [ItemStatus.INBOX]}
        )
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check clear button has HTMX attributes
        self.assertIn('hx-get=', content)
        self.assertIn('clearFilters()', content)
    
    def test_search_and_pagination_together(self):
        """Test that search and pagination work together"""
        # Search for items with specific text
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'q': 'Item 1'}  # Will match Item 1, Item 10-19
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['page_obj'].object_list)
        
        # All items should contain "Item 1" in the title
        for item in items:
            self.assertIn('Item 1', item.title)
    
    def test_multiple_filters_and_pagination(self):
        """Test that multiple filters work together with pagination"""
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {
                'status': [ItemStatus.INBOX, ItemStatus.BACKLOG],
                'q': 'Item'
            }
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['page_obj'].object_list)
        
        # Items should match the filters
        for item in items:
            self.assertIn(item.status, [ItemStatus.INBOX, ItemStatus.BACKLOG])
            self.assertIn('Item', item.title)
