"""
Tests for Item ListView implementation with django-tables2 and django-filter.
"""
from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ProjectStatus
)


class ItemListViewTestCase(TestCase):
    """Test cases for Item list views with django-tables2 and django-filter"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation"
        )
        
        # Create test users
        self.user1 = User.objects.create(
            username="testuser1",
            email="test1@example.com",
            active=True
        )
        self.user1.set_password("testpass123")
        self.user1.save()
        
        self.user2 = User.objects.create(
            username="testuser2",
            email="test2@example.com",
            active=True
        )
        
        # Add users to organisation
        from core.models import UserOrganisation
        UserOrganisation.objects.create(user=self.user1, organisation=self.org)
        UserOrganisation.objects.create(user=self.user2, organisation=self.org)
        
        # Create projects
        self.project1 = Project.objects.create(
            name="Project Alpha",
            status=ProjectStatus.WORKING
        )
        
        self.project2 = Project.objects.create(
            name="Project Beta",
            status=ProjectStatus.WORKING
        )
        
        # Create item types
        self.bug_type = ItemType.objects.create(
            key="bug",
            name="Bug"
        )
        
        self.feature_type = ItemType.objects.create(
            key="feature",
            name="Feature"
        )
        
        # Create items with different statuses
        self.inbox_item = Item.objects.create(
            title="Inbox Item",
            description="This is an inbox item",
            project=self.project1,
            type=self.bug_type,
            status=ItemStatus.INBOX,
            organisation=self.org,
            requester=self.user1,
        )
        
        self.backlog_item1 = Item.objects.create(
            title="Backlog Item 1",
            description="This is a backlog item",
            project=self.project1,
            type=self.bug_type,
            status=ItemStatus.BACKLOG,
            organisation=self.org,
            requester=self.user1,
            assigned_to=self.user2,
        )
        
        self.backlog_item2 = Item.objects.create(
            title="Backlog Item 2",
            description="Another backlog item",
            project=self.project2,
            type=self.feature_type,
            status=ItemStatus.BACKLOG,
            organisation=self.org,
        )
        
        self.working_item = Item.objects.create(
            title="Working Item",
            description="This is a working item",
            project=self.project1,
            type=self.bug_type,
            status=ItemStatus.WORKING,
            organisation=self.org,
            assigned_to=self.user1,
        )
        
        self.testing_item = Item.objects.create(
            title="Testing Item",
            description="This is a testing item",
            project=self.project2,
            type=self.feature_type,
            status=ItemStatus.TESTING,
            organisation=self.org,
        )
        
        self.ready_item = Item.objects.create(
            title="Ready Item",
            description="This is a ready item",
            project=self.project2,
            type=self.bug_type,
            status=ItemStatus.READY_FOR_RELEASE,
            organisation=self.org,
        )
        
        # Login user
        self.client.login(username='testuser1', password='testpass123')
    
    def test_inbox_view_status_scope(self):
        """Test inbox view only shows inbox items"""
        response = self.client.get(reverse('items-inbox'))
        self.assertEqual(response.status_code, 200)
        
        # Check that table is in context
        self.assertIn('table', response.context)
        
        # Get items from table
        items = list(response.context['table'].data)
        
        # Should only have inbox items
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, ItemStatus.INBOX)
        self.assertEqual(items[0].title, "Inbox Item")
    
    def test_backlog_view_status_scope(self):
        """Test backlog view only shows backlog items"""
        response = self.client.get(reverse('items-backlog'))
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['table'].data)
        
        # Should only have backlog items
        self.assertEqual(len(items), 2)
        for item in items:
            self.assertEqual(item.status, ItemStatus.BACKLOG)
    
    def test_working_view_status_scope(self):
        """Test working view only shows working items"""
        response = self.client.get(reverse('items-working'))
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['table'].data)
        
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, ItemStatus.WORKING)
    
    def test_testing_view_status_scope(self):
        """Test testing view only shows testing items"""
        response = self.client.get(reverse('items-testing'))
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['table'].data)
        
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, ItemStatus.TESTING)
    
    def test_ready_view_status_scope(self):
        """Test ready view only shows ready items"""
        response = self.client.get(reverse('items-ready'))
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['table'].data)
        
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].status, ItemStatus.READY_FOR_RELEASE)
    
    def test_search_filter(self):
        """Test search filter works correctly"""
        # Search in backlog (has 2 items)
        response = self.client.get(reverse('items-backlog'), {'q': 'Another'})
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['table'].data)
        
        # Should only find one item with "Another" in title
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Backlog Item 2")
    
    def test_project_filter(self):
        """Test project filter works correctly"""
        # Filter backlog by project1
        response = self.client.get(
            reverse('items-backlog'),
            {'project': self.project1.id}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['table'].data)
        
        # Should only have backlog items from project1
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].project, self.project1)
    
    def test_type_filter(self):
        """Test type filter works correctly"""
        # Filter backlog by bug type
        response = self.client.get(
            reverse('items-backlog'),
            {'type': self.bug_type.id}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['table'].data)
        
        # Should only have backlog items with bug type
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].type, self.bug_type)
    
    def test_multiple_filters(self):
        """Test multiple filters work together"""
        # Search for "Backlog" in project1
        response = self.client.get(
            reverse('items-backlog'),
            {'q': 'Backlog', 'project': self.project1.id}
        )
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['table'].data)
        
        # Should only find backlog items in project1 with "Backlog" in title
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Backlog Item 1")
        self.assertEqual(items[0].project, self.project1)
    
    def test_status_scope_not_removable(self):
        """Test that status scope cannot be removed via filters"""
        # Try to get working items from backlog view (should not work)
        response = self.client.get(reverse('items-backlog'))
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['table'].data)
        
        # Should never contain working items
        for item in items:
            self.assertNotEqual(item.status, ItemStatus.WORKING)
    
    def test_pagination_context(self):
        """Test that pagination is present in context"""
        response = self.client.get(reverse('items-backlog'))
        self.assertEqual(response.status_code, 200)
        
        # Table should support pagination
        self.assertTrue(hasattr(response.context['table'], 'page'))
    
    def test_distinct_values_in_context(self):
        """Test that distinct values are provided in context"""
        response = self.client.get(reverse('items-backlog'))
        self.assertEqual(response.status_code, 200)
        
        # Check distinct_values is in context
        self.assertIn('distinct_values', response.context)
        
        distinct = response.context['distinct_values']
        
        # Check structure
        self.assertIn('project', distinct)
        self.assertIn('type', distinct)
        self.assertIn('organisation', distinct)
        
        # Check that distinct values are from backlog items only
        project_ids = [p.id for p in distinct['project']]
        self.assertIn(self.project1.id, project_ids)
        self.assertIn(self.project2.id, project_ids)
    
    def test_login_required(self):
        """Test that login is required for all views"""
        self.client.logout()
        
        views = [
            'items-inbox',
            'items-backlog',
            'items-working',
            'items-testing',
            'items-ready',
        ]
        
        for view_name in views:
            response = self.client.get(reverse(view_name))
            # Should redirect to login
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith('/login/'))
    
    def test_sorting_via_querystring(self):
        """Test that sorting works via querystring"""
        # Sort backlog by title
        response = self.client.get(reverse('items-backlog'), {'sort': 'title'})
        self.assertEqual(response.status_code, 200)
        
        items = list(response.context['table'].data)
        
        # Should be sorted by title
        self.assertEqual(items[0].title, "Backlog Item 1")
        self.assertEqual(items[1].title, "Backlog Item 2")
