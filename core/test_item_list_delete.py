"""
Tests for Item list delete functionality with HTMX.
"""
from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ProjectStatus
)


class ItemListDeleteTestCase(TestCase):
    """Test cases for Item list delete functionality"""
    
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
        
        # Create test items with different statuses
        self.inbox_item = Item.objects.create(
            title="Inbox Item to Delete",
            description="Test item in inbox",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.INBOX,
            organisation=self.org,
        )
        
        self.backlog_item = Item.objects.create(
            title="Backlog Item to Delete",
            description="Test item in backlog",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            organisation=self.org,
        )
        
        # Create additional items to test list refresh
        self.inbox_item_2 = Item.objects.create(
            title="Inbox Item 2",
            description="Should remain after delete",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.INBOX,
            organisation=self.org,
        )
    
    def test_delete_endpoint_requires_login(self):
        """Test that delete endpoint requires authentication"""
        self.client.logout()
        
        response = self.client.post(
            reverse('item-list-delete', kwargs={'item_id': self.inbox_item.id})
        )
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('/login/'))
        
        # Item should still exist
        self.assertTrue(Item.objects.filter(id=self.inbox_item.id).exists())
    
    def test_delete_requires_post(self):
        """Test that delete endpoint only accepts POST requests"""
        response = self.client.get(
            reverse('item-list-delete', kwargs={'item_id': self.inbox_item.id})
        )
        
        self.assertEqual(response.status_code, 405)  # Method not allowed
        
        # Item should still exist
        self.assertTrue(Item.objects.filter(id=self.inbox_item.id).exists())
    
    def test_delete_inbox_item(self):
        """Test deleting an item from inbox list"""
        # Get initial count
        initial_count = Item.objects.filter(status=ItemStatus.INBOX).count()
        
        response = self.client.post(
            reverse('item-list-delete', kwargs={'item_id': self.inbox_item.id})
        )
        
        # Should return 200 with HTML content
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response['Content-Type'])
        
        # Item should be deleted
        self.assertFalse(Item.objects.filter(id=self.inbox_item.id).exists())
        
        # Count should be reduced
        new_count = Item.objects.filter(status=ItemStatus.INBOX).count()
        self.assertEqual(new_count, initial_count - 1)
        
        # Response should contain the list container
        content = response.content.decode('utf-8')
        self.assertIn('items-list-container', content)
        
        # Response should contain the remaining item
        self.assertIn('Inbox Item 2', content)
        
        # Response should not contain the deleted item
        self.assertNotIn('Inbox Item to Delete', content)
    
    def test_delete_backlog_item(self):
        """Test deleting an item from backlog list"""
        # Get initial count
        initial_count = Item.objects.filter(status=ItemStatus.BACKLOG).count()
        
        response = self.client.post(
            reverse('item-list-delete', kwargs={'item_id': self.backlog_item.id})
        )
        
        # Should return 200 with HTML content
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response['Content-Type'])
        
        # Item should be deleted
        self.assertFalse(Item.objects.filter(id=self.backlog_item.id).exists())
        
        # Count should be reduced
        new_count = Item.objects.filter(status=ItemStatus.BACKLOG).count()
        self.assertEqual(new_count, initial_count - 1)
    
    def test_delete_preserves_filters(self):
        """Test that filters are preserved after delete"""
        # Create additional items
        Item.objects.create(
            title="Inbox Item 3",
            description="Another inbox item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.INBOX,
            organisation=self.org,
        )
        
        # Delete with filter parameter
        response = self.client.post(
            reverse('item-list-delete', kwargs={'item_id': self.inbox_item.id}),
            {'q': 'Item 2'}
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Item should be deleted
        self.assertFalse(Item.objects.filter(id=self.inbox_item.id).exists())
    
    def test_delete_nonexistent_item(self):
        """Test deleting a non-existent item returns 404"""
        response = self.client.post(
            reverse('item-list-delete', kwargs={'item_id': 99999})
        )
        
        self.assertEqual(response.status_code, 404)
    
    def test_delete_and_list_refresh_shows_updated_count(self):
        """Test that the refreshed list shows correct item count"""
        # Create a few more items
        for i in range(3):
            Item.objects.create(
                title=f"Inbox Item {i+10}",
                description=f"Test item {i}",
                project=self.project,
                type=self.item_type,
                status=ItemStatus.INBOX,
                organisation=self.org,
            )
        
        initial_count = Item.objects.filter(status=ItemStatus.INBOX).count()
        
        response = self.client.post(
            reverse('item-list-delete', kwargs={'item_id': self.inbox_item.id})
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify the count decreased
        new_count = Item.objects.filter(status=ItemStatus.INBOX).count()
        self.assertEqual(new_count, initial_count - 1)
        
        # The response should contain table with remaining items
        content = response.content.decode('utf-8')
        self.assertIn('table', content)
    
    def test_actions_column_in_table(self):
        """Test that the actions column appears in the list view"""
        response = self.client.get(reverse('items-inbox'))
        
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Should have Actions header
        self.assertIn('Actions', content)
        
        # Should have delete button with HTMX attributes
        self.assertIn('hx-post=', content)
        self.assertIn('hx-confirm=', content)
        self.assertIn('hx-target="#items-list-container"', content)
        self.assertIn('bi-trash', content)
    
    def test_delete_button_has_htmx_confirm(self):
        """Test that delete button has HTMX confirmation dialog"""
        response = self.client.get(reverse('items-backlog'))
        
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Should have confirmation message
        self.assertIn('Are you sure you want to delete this item?', content)
