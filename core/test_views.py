"""
Tests for item board views
"""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ProjectStatus
)


class ItemBoardViewsTestCase(TestCase):
    """Test cases for item board views"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation"
        )
        
        # Create test user
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com"
        )
        
        # Create projects
        self.project1 = Project.objects.create(
            name="Project Alpha",
            status=ProjectStatus.WORKING
        )
        
        self.project2 = Project.objects.create(
            name="Project Beta",
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key="bug",
            name="Bug"
        )
        
        # Create items with different statuses
        self.backlog_item = Item.objects.create(
            title="Backlog Item",
            description="This is a backlog item",
            project=self.project1,
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            organisation=self.org,
        )
        
        self.working_item = Item.objects.create(
            title="Working Item",
            description="This is a working item",
            project=self.project1,
            type=self.item_type,
            status=ItemStatus.WORKING,
            organisation=self.org,
        )
        
        self.testing_item = Item.objects.create(
            title="Testing Item",
            description="This is a testing item",
            project=self.project2,
            type=self.item_type,
            status=ItemStatus.TESTING,
            organisation=self.org,
        )
        
        self.ready_item = Item.objects.create(
            title="Ready Item",
            description="This is a ready item",
            project=self.project2,
            type=self.item_type,
            status=ItemStatus.READY_FOR_RELEASE,
            organisation=self.org,
        )
        
        self.inbox_item = Item.objects.create(
            title="Inbox Item",
            description="This is an inbox item",
            project=self.project1,
            type=self.item_type,
            status=ItemStatus.INBOX,
            organisation=self.org,
        )
    
    def test_items_backlog_view(self):
        """Test items backlog view returns correct items"""
        response = self.client.get(reverse('items-backlog'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('items', response.context)
        self.assertIn('projects', response.context)
        
        # Should only have backlog items
        items = list(response.context['items'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, ItemStatus.BACKLOG)
        self.assertEqual(items[0].title, "Backlog Item")
    
    def test_items_working_view(self):
        """Test items working view returns correct items"""
        response = self.client.get(reverse('items-working'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('items', response.context)
        
        # Should only have working items
        items = list(response.context['items'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, ItemStatus.WORKING)
        self.assertEqual(items[0].title, "Working Item")
    
    def test_items_testing_view(self):
        """Test items testing view returns correct items"""
        response = self.client.get(reverse('items-testing'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('items', response.context)
        
        # Should only have testing items
        items = list(response.context['items'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, ItemStatus.TESTING)
        self.assertEqual(items[0].title, "Testing Item")
    
    def test_items_ready_view(self):
        """Test items ready view returns correct items"""
        response = self.client.get(reverse('items-ready'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('items', response.context)
        
        # Should only have ready items
        items = list(response.context['items'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, ItemStatus.READY_FOR_RELEASE)
        self.assertEqual(items[0].title, "Ready Item")
    
    def test_search_filter_by_title(self):
        """Test search filter works for title"""
        # Create another backlog item
        Item.objects.create(
            title="Another Backlog Item",
            description="Different description",
            project=self.project1,
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            organisation=self.org,
        )
        
        response = self.client.get(reverse('items-backlog'), {'q': 'Another'})
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['items'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Another Backlog Item")
    
    def test_search_filter_by_description(self):
        """Test search filter works for description"""
        response = self.client.get(reverse('items-backlog'), {'q': 'backlog item'})
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['items'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].description, "This is a backlog item")
    
    def test_project_filter(self):
        """Test project filter works"""
        # Create a backlog item for project 2
        Item.objects.create(
            title="Project Beta Backlog Item",
            description="Another backlog item",
            project=self.project2,
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            organisation=self.org,
        )
        
        response = self.client.get(
            reverse('items-backlog'),
            {'project': self.project2.id}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['items'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].project, self.project2)
    
    def test_combined_filters(self):
        """Test combining search and project filters"""
        # Create a backlog item for project 2
        Item.objects.create(
            title="Specific Backlog Item",
            description="Specific description",
            project=self.project2,
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            organisation=self.org,
        )
        
        response = self.client.get(
            reverse('items-backlog'),
            {'q': 'Specific', 'project': self.project2.id}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['items'])
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Specific Backlog Item")
        self.assertEqual(items[0].project, self.project2)
    
    def test_empty_results(self):
        """Test views handle empty results correctly"""
        # Test with search that yields no results
        response = self.client.get(
            reverse('items-backlog'),
            {'q': 'NonexistentItem'}
        )
        self.assertEqual(response.status_code, 200)
        items = list(response.context['items'])
        self.assertEqual(len(items), 0)
    
    def test_context_contains_search_query(self):
        """Test that search query is passed to context"""
        response = self.client.get(
            reverse('items-backlog'),
            {'q': 'test query'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['search_query'], 'test query')
    
    def test_context_contains_project_id(self):
        """Test that project_id is passed to context"""
        response = self.client.get(
            reverse('items-backlog'),
            {'project': str(self.project1.id)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['project_id'], str(self.project1.id))
    
    def test_templates_exist(self):
        """Test that all templates are being used"""
        views_and_templates = [
            ('items-backlog', 'items_backlog.html'),
            ('items-working', 'items_working.html'),
            ('items-testing', 'items_testing.html'),
            ('items-ready', 'items_ready.html'),
        ]
        
        for view_name, template_name in views_and_templates:
            response = self.client.get(reverse(view_name))
            self.assertTemplateUsed(response, template_name)
    
    def test_invalid_project_id_handled_gracefully(self):
        """Test that invalid project IDs are handled gracefully"""
        # Test with non-numeric project ID
        response = self.client.get(
            reverse('items-backlog'),
            {'project': 'invalid'}
        )
        self.assertEqual(response.status_code, 200)
        # Should show all items when project filter is invalid
        items = list(response.context['items'])
        self.assertEqual(len(items), 1)
        
        # Test with empty string
        response = self.client.get(
            reverse('items-backlog'),
            {'project': ''}
        )
        self.assertEqual(response.status_code, 200)
        items = list(response.context['items'])
        self.assertEqual(len(items), 1)
