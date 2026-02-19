"""
Tests for Item responsible field functionality.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item, UserRole
)

User = get_user_model()


class ItemResponsibleFieldTest(TestCase):
    """Test the item responsible field."""
    
    def setUp(self):
        """Set up test data."""
        # Create agent user
        self.agent = User.objects.create_user(
            username='agent',
            email='agent@example.com',
            password='testpass',
            name='Agent User',
            role=UserRole.AGENT
        )
        
        # Create non-agent user
        self.user = User.objects.create_user(
            username='testuser',
            email='user@example.com',
            password='testpass',
            name='Test User',
            role=UserRole.USER
        )
        
        # Create organisation
        self.org = Organisation.objects.create(name='Test Org')
        UserOrganisation.objects.create(
            user=self.agent,
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
    
    def test_item_responsible_default_value(self):
        """Test that new items have responsible=None by default."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        self.assertIsNone(item.responsible)
    
    def test_item_responsible_can_be_set_to_agent(self):
        """Test that responsible can be set to an agent user."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=self.agent
        )
        item.full_clean()  # Should not raise
        self.assertEqual(item.responsible, self.agent)
    
    def test_item_responsible_cannot_be_non_agent(self):
        """Test that responsible cannot be set to a non-agent user."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=self.user  # Non-agent
        )
        with self.assertRaises(ValidationError) as context:
            item.full_clean()
        self.assertIn('responsible', context.exception.message_dict)
    
    def test_item_responsible_can_be_null(self):
        """Test that responsible can be null."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=None
        )
        item.full_clean()  # Should not raise
        self.assertIsNone(item.responsible)
    
    def test_take_over_responsible_action_as_agent(self):
        """Test take over action as agent user."""
        self.client.login(username='agent', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        response = self.client.post(
            reverse('item-take-over-responsible', args=[item.id])
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Reload item and check responsible
        item.refresh_from_db()
        self.assertEqual(item.responsible, self.agent)
    
    def test_take_over_responsible_action_as_non_agent(self):
        """Test take over action as non-agent user should fail."""
        self.client.login(username='testuser', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        response = self.client.post(
            reverse('item-take-over-responsible', args=[item.id])
        )
        
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_take_over_responsible_idempotent(self):
        """Test take over action is idempotent (no change if already responsible)."""
        self.client.login(username='agent', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=self.agent
        )
        
        response = self.client.post(
            reverse('item-take-over-responsible', args=[item.id])
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data.get('no_change', False))
    
    def test_assign_responsible_action(self):
        """Test assign action."""
        self.client.login(username='testuser', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        response = self.client.post(
            reverse('item-assign-responsible', args=[item.id]),
            {'agent_id': self.agent.id}
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Reload item and check responsible
        item.refresh_from_db()
        self.assertEqual(item.responsible, self.agent)
    
    def test_assign_responsible_validates_agent_role(self):
        """Test assign action validates that selected user is an agent."""
        self.client.login(username='testuser', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        response = self.client.post(
            reverse('item-assign-responsible', args=[item.id]),
            {'agent_id': self.user.id}  # Non-agent
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_assign_responsible_idempotent(self):
        """Test assign action is idempotent."""
        self.client.login(username='testuser', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=self.agent
        )
        
        response = self.client.post(
            reverse('item-assign-responsible', args=[item.id]),
            {'agent_id': self.agent.id}
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data.get('no_change', False))
