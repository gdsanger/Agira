"""
Tests for Item ListView implementation with django-tables2 and django-filter.
"""
from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ProjectStatus, UserRole
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


class UserScopedItemListViewTestCase(TestCase):
    """Test cases for user-scoped Item list views (Assigned, Responsible)"""

    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()

        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation"
        )

        # Create test users
        self.agent_user = User.objects.create(
            username="agent1",
            email="agent@example.com",
            role=UserRole.AGENT,
            active=True
        )
        self.agent_user.set_password("testpass123")
        self.agent_user.save()

        self.regular_user = User.objects.create(
            username="regular1",
            email="regular@example.com",
            role=UserRole.USER,
            active=True
        )
        self.regular_user.set_password("testpass123")
        self.regular_user.save()

        self.other_user = User.objects.create(
            username="other1",
            email="other@example.com",
            active=True
        )

        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )

        # Create item type
        self.item_type = ItemType.objects.create(
            key="task",
            name="Task"
        )

        # Create items assigned to agent_user
        self.assigned_inbox = Item.objects.create(
            title="Assigned Inbox Item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.INBOX,
            assigned_to=self.agent_user,
        )

        self.assigned_working = Item.objects.create(
            title="Assigned Working Item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
            assigned_to=self.agent_user,
        )

        # Create item assigned to other user
        self.assigned_to_other = Item.objects.create(
            title="Assigned to Other",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            assigned_to=self.other_user,
        )

        # Create items where agent_user is responsible
        self.responsible_backlog = Item.objects.create(
            title="Responsible Backlog Item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            responsible=self.agent_user,
        )

        self.responsible_testing = Item.objects.create(
            title="Responsible Testing Item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.TESTING,
            responsible=self.agent_user,
        )

        # Create item where other user is responsible
        self.responsible_other = Item.objects.create(
            title="Responsible by Other",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
            responsible=self.other_user,
        )

        # Create closed item (should be excluded)
        self.assigned_closed = Item.objects.create(
            title="Assigned Closed Item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.CLOSED,
            assigned_to=self.agent_user,
        )

        self.responsible_closed = Item.objects.create(
            title="Responsible Closed Item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.CLOSED,
            responsible=self.agent_user,
        )

        # Login as agent_user
        self.client.login(username='agent1', password='testpass123')

    def test_assigned_view_shows_only_assigned_items(self):
        """Test that assigned view only shows items assigned to current user"""
        response = self.client.get(reverse('items-assigned'))
        self.assertEqual(response.status_code, 200)

        # Check that table is in context
        self.assertIn('table', response.context)

        # Get items from table
        items = list(response.context['table'].data)

        # Should have 2 items (inbox + working, excluding closed)
        self.assertEqual(len(items), 2)

        # All items should be assigned to agent_user
        for item in items:
            self.assertEqual(item.assigned_to, self.agent_user)
            self.assertNotEqual(item.status, ItemStatus.CLOSED)

        # Verify specific items are present
        item_titles = [item.title for item in items]
        self.assertIn("Assigned Inbox Item", item_titles)
        self.assertIn("Assigned Working Item", item_titles)
        self.assertNotIn("Assigned to Other", item_titles)
        self.assertNotIn("Assigned Closed Item", item_titles)

    def test_responsible_view_shows_only_responsible_items(self):
        """Test that responsible view only shows items where current user is responsible"""
        response = self.client.get(reverse('items-responsible'))
        self.assertEqual(response.status_code, 200)

        # Check that table is in context
        self.assertIn('table', response.context)

        # Get items from table
        items = list(response.context['table'].data)

        # Should have 2 items (backlog + testing, excluding closed)
        self.assertEqual(len(items), 2)

        # All items should have agent_user as responsible
        for item in items:
            self.assertEqual(item.responsible, self.agent_user)
            self.assertNotEqual(item.status, ItemStatus.CLOSED)

        # Verify specific items are present
        item_titles = [item.title for item in items]
        self.assertIn("Responsible Backlog Item", item_titles)
        self.assertIn("Responsible Testing Item", item_titles)
        self.assertNotIn("Responsible by Other", item_titles)
        self.assertNotIn("Responsible Closed Item", item_titles)

    def test_user_scoped_views_exclude_closed_items(self):
        """Test that user-scoped views exclude closed items by default"""
        # Check assigned view
        response = self.client.get(reverse('items-assigned'))
        items = list(response.context['table'].data)
        for item in items:
            self.assertNotEqual(item.status, ItemStatus.CLOSED)

        # Check responsible view
        response = self.client.get(reverse('items-responsible'))
        items = list(response.context['table'].data)
        for item in items:
            self.assertNotEqual(item.status, ItemStatus.CLOSED)

    def test_assigned_view_with_filters(self):
        """Test that filters work correctly in assigned view"""
        # Search for "Working"
        response = self.client.get(reverse('items-assigned'), {'q': 'Working'})
        self.assertEqual(response.status_code, 200)

        items = list(response.context['table'].data)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Assigned Working Item")

    def test_responsible_view_with_filters(self):
        """Test that filters work correctly in responsible view"""
        # Search for "Testing"
        response = self.client.get(reverse('items-responsible'), {'q': 'Testing'})
        self.assertEqual(response.status_code, 200)

        items = list(response.context['table'].data)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].title, "Responsible Testing Item")

    def test_user_scope_not_removable(self):
        """Test that user scope cannot be removed via filters"""
        # Try to see other user's items (should not work)
        response = self.client.get(reverse('items-assigned'))
        items = list(response.context['table'].data)

        # Should never contain items assigned to other users
        for item in items:
            self.assertEqual(item.assigned_to, self.agent_user)

    def test_user_scoped_views_login_required(self):
        """Test that login is required for user-scoped views"""
        self.client.logout()

        views = ['items-assigned', 'items-responsible']

        for view_name in views:
            response = self.client.get(reverse(view_name))
            # Should redirect to login
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith('/login/'))

    def test_user_scoped_views_page_title(self):
        """Test that page titles are set correctly"""
        # Check assigned view
        response = self.client.get(reverse('items-assigned'))
        self.assertEqual(response.context['page_title'], "Items - Assigned to Me")

        # Check responsible view
        response = self.client.get(reverse('items-responsible'))
        self.assertEqual(response.context['page_title'], "Items - Responsible For")

    def test_distinct_values_in_user_scoped_views(self):
        """Test that distinct values are computed correctly for user-scoped views"""
        response = self.client.get(reverse('items-assigned'))
        self.assertEqual(response.status_code, 200)

        # Check distinct_values is in context
        self.assertIn('distinct_values', response.context)

        distinct = response.context['distinct_values']

        # Check structure
        self.assertIn('project', distinct)
        self.assertIn('type', distinct)
        self.assertIn('organisation', distinct)
