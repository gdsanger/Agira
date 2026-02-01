"""
Tests for Item intern field functionality.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item
)

User = get_user_model()


class ItemInternFieldTest(TestCase):
    """Test the item intern field."""
    
    def setUp(self):
        """Set up test data."""
        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            name='Test User',
            role='Agent'
        )
        
        # Create organisation
        self.org = Organisation.objects.create(name='Test Org')
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        self.project.clients.add(self.org)
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            organisation=self.org
        )
        
        # Create client
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def test_item_intern_default_value(self):
        """Test that new items have intern=False by default."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        self.assertFalse(item.intern)
    
    def test_item_intern_can_be_set(self):
        """Test that intern field can be set to True."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            intern=True
        )
        
        self.assertTrue(item.intern)
        
        # Reload from database
        item.refresh_from_db()
        self.assertTrue(item.intern)
    
    def test_item_update_intern_endpoint(self):
        """Test HTMX endpoint for updating intern field."""
        # Create item with intern=False
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            intern=False
        )
        
        # Update to True
        url = reverse('item-update-intern', kwargs={'item_id': item.id})
        response = self.client.post(url, {'intern': 'on'})
        
        self.assertEqual(response.status_code, 200)
        
        # Verify in database
        item.refresh_from_db()
        self.assertTrue(item.intern)
        
        # Update back to False (checkbox not checked sends no value)
        response = self.client.post(url, {})
        
        self.assertEqual(response.status_code, 200)
        
        # Verify in database
        item.refresh_from_db()
        self.assertFalse(item.intern)
    
    def test_item_detail_view_contains_intern_field(self):
        """Test that item detail view displays the intern field."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            intern=True
        )
        
        url = reverse('item-detail', kwargs={'item_id': item.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'intern-checkbox')
        self.assertContains(response, 'Intern')
