"""
Tests for the item status HTMX endpoint.
"""
from django.test import TestCase, Client
from django.urls import reverse
from core.models import Item, Project, ItemStatus, ItemType, User


class ItemStatusEndpointTestCase(TestCase):
    """Test case for the item status HTMX endpoint."""
    
    def setUp(self):
        """Set up test data."""
        self.client = Client()
        
        # Create a test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        self.user.name = 'Test User'
        self.user.active = True
        self.user.save()
        
        # Create a test project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project description'
        )
        
        # Create an item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            description='Bug type for testing'
        )
        
        # Create a test item
        self.item = Item.objects.create(
            title='Test Item',
            description='Test item description',
            project=self.project,
            type=self.item_type,
            status=ItemStatus.INBOX
        )
    
    def test_status_endpoint_requires_authentication(self):
        """Test that the status endpoint requires authentication."""
        url = reverse('item-status', args=[self.item.id])
        response = self.client.get(url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_status_endpoint_returns_status(self):
        """Test that the status endpoint returns the item status."""
        # Login
        self.client.login(username='testuser', password='testpass123')
        
        # Get status
        url = reverse('item-status', args=[self.item.id])
        response = self.client.get(url)
        
        # Should return 200
        self.assertEqual(response.status_code, 200)
        
        # Should contain the status text
        self.assertContains(response, 'Inbox')
    
    def test_status_endpoint_updates_when_status_changes(self):
        """Test that the endpoint reflects status changes."""
        # Login
        self.client.login(username='testuser', password='testpass123')
        
        # Change item status
        self.item.status = ItemStatus.WORKING
        self.item.save()
        
        # Get status
        url = reverse('item-status', args=[self.item.id])
        response = self.client.get(url)
        
        # Should return 200
        self.assertEqual(response.status_code, 200)
        
        # Should contain the updated status
        self.assertContains(response, 'Working')
        self.assertNotContains(response, 'Inbox')
    
    def test_status_endpoint_404_for_nonexistent_item(self):
        """Test that the endpoint returns 404 for nonexistent items."""
        # Login
        self.client.login(username='testuser', password='testpass123')
        
        # Try to get status for nonexistent item
        url = reverse('item-status', args=[99999])
        response = self.client.get(url)
        
        # Should return 404
        self.assertEqual(response.status_code, 404)
