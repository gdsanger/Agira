"""
Tests for Issue ID Lookup feature in header
"""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, UserOrganisation
)


class IssueIdLookupTestCase(TestCase):
    """Test cases for Issue ID Lookup feature"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation"
        )
        
        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            name="Test User",
            active=True
        )
        
        # Link user to organisation
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            description="Test project"
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key="feature",
            name="Feature"
        )
        
        # Create test items
        self.item1 = Item.objects.create(
            title="Test Item 1",
            description="This is test item 1",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.INBOX,
            organisation=self.org,
            requester=self.user
        )
        
        self.item2 = Item.objects.create(
            title="Test Item 2",
            description="This is test item 2",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
    
    def test_item_lookup_requires_login(self):
        """Test that the item lookup endpoint requires login"""
        response = self.client.get(reverse('item-lookup', kwargs={'item_id': self.item1.id}))
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_item_lookup_existing_item(self):
        """Test lookup for an existing item"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('item-lookup', kwargs={'item_id': self.item1.id}))
        
        # Should return 200 OK with JSON
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        # Check response data
        data = response.json()
        self.assertTrue(data['exists'])
        self.assertEqual(data['id'], self.item1.id)
        self.assertEqual(data['title'], 'Test Item 1')
    
    def test_item_lookup_nonexistent_item(self):
        """Test lookup for a non-existent item"""
        self.client.login(username='testuser', password='testpass123')
        
        # Use an ID that definitely doesn't exist
        nonexistent_id = 999999
        response = self.client.get(reverse('item-lookup', kwargs={'item_id': nonexistent_id}))
        
        # Should return 404
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        # Check error message
        data = response.json()
        self.assertFalse(data['exists'])
        self.assertIn('error', data)
        self.assertIn('existiert kein Issue', data['error'])
    
    def test_item_detail_view_existing_item(self):
        """Test that the item detail view works for existing items"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('item-detail', kwargs={'item_id': self.item2.id}))
        
        # Should return 200 OK
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'item_detail.html')
        
        # Check context data
        self.assertEqual(response.context['item'], self.item2)
    
    def test_item_detail_view_nonexistent_item(self):
        """Test that the item detail view returns 404 for non-existent items"""
        self.client.login(username='testuser', password='testpass123')
        
        # Use an ID that definitely doesn't exist
        nonexistent_id = 999999
        response = self.client.get(reverse('item-detail', kwargs={'item_id': nonexistent_id}))
        
        # Should return 404
        self.assertEqual(response.status_code, 404)
