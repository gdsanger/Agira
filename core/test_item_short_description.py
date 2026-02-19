"""
Tests for Item Short Description feature
"""

from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    User, UserRole, Project, Item, ItemType, ItemStatus, 
    Organisation, AIProvider, AIModel, Activity
)


class ItemShortDescriptionTestCase(TestCase):
    """Test cases for Item short_description field"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create users with different roles
        self.agent_user = User.objects.create_user(
            username='agent_user',
            email='agent@test.com',
            password='testpass123',
            name='Agent User',
            role=UserRole.AGENT
        )
        
        self.regular_user = User.objects.create_user(
            username='regular_user',
            email='user@test.com',
            password='testpass123',
            name='Regular User',
            role=UserRole.USER
        )
        
        # Create organization
        self.org = Organisation.objects.create(name='Test Org')
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project for short description'
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='feature',
            name='Feature',
            is_active=True
        )
        
        # Create test item
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='This is a test description.',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Create AI provider and model for agent execution
        self.provider = AIProvider.objects.create(
            name='Test OpenAI',
            provider_type='OpenAI',
            api_key='test-key',
            active=True
        )
        
        self.model = AIModel.objects.create(
            provider=self.provider,
            model_id='gpt-4o',
            active=True,
            is_default=True
        )
    
    def test_item_has_short_description_field(self):
        """Test that Item model has short_description field"""
        item = Item.objects.create(
            project=self.project,
            title='Test Item with Short Description',
            description='Full description',
            short_description='Short description text',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        self.assertEqual(item.short_description, 'Short description text')
    
    def test_short_description_can_be_empty(self):
        """Test that short_description can be empty"""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Full description',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        self.assertEqual(item.short_description, '')
    
    def test_generate_short_description_requires_authentication(self):
        """Test that unauthenticated users cannot generate short descriptions"""
        url = reverse('item-generate-short-description-ai', args=[self.item.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_generate_short_description_requires_agent_role(self):
        """Test that only Agent users can generate short descriptions"""
        self.client.login(username='regular_user', password='testpass123')
        url = reverse('item-generate-short-description-ai', args=[self.item.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)
        self.assertIn('Agent role', response.json()['message'])
    
    def test_generate_short_description_requires_description(self):
        """Test that generation requires item description"""
        # Create item without description
        empty_item = Item.objects.create(
            project=self.project,
            title='Empty Item',
            description='',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        self.client.login(username='agent_user', password='testpass123')
        url = reverse('item-generate-short-description-ai', args=[empty_item.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        self.assertIn('no description', response.json()['message'])
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_generate_short_description_success(self, mock_execute_agent):
        """Test successful short description generation"""
        # Mock the agent response
        mock_execute_agent.return_value = 'This is a generated short description. It contains key information.'
        
        self.client.login(username='agent_user', password='testpass123')
        url = reverse('item-generate-short-description-ai', args=[self.item.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')
        
        # Verify item was updated
        self.item.refresh_from_db()
        self.assertEqual(self.item.short_description, 'This is a generated short description. It contains key information.')
        
        # Verify agent was called with correct parameters
        mock_execute_agent.assert_called_once()
        call_kwargs = mock_execute_agent.call_args[1]
        self.assertEqual(call_kwargs['filename'], 'item-short-description-agent.yml')
        self.assertEqual(call_kwargs['input_text'], self.item.description)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_generate_short_description_logs_activity(self, mock_execute_agent):
        """Test that activity is logged on success"""
        mock_execute_agent.return_value = 'Generated short description.'
        
        self.client.login(username='agent_user', password='testpass123')
        url = reverse('item-generate-short-description-ai', args=[self.item.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify activity was logged
        activity = Activity.objects.filter(
            verb='item.short_description.ai_generated',
            target_object_id=str(self.item.id)
        ).first()
        self.assertIsNotNone(activity)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_generate_short_description_handles_error(self, mock_execute_agent):
        """Test error handling when agent fails"""
        mock_execute_agent.side_effect = Exception('Agent error')
        
        self.client.login(username='agent_user', password='testpass123')
        url = reverse('item-generate-short-description-ai', args=[self.item.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 500)
        self.assertIn('Failed to generate', response.json()['message'])
        
        # Verify error activity was logged
        activity = Activity.objects.filter(
            verb='item.short_description.ai_error',
            target_object_id=str(self.item.id)
        ).first()
        self.assertIsNotNone(activity)


class ItemUpdateShortDescriptionTestCase(TestCase):
    """Test cases for updating short_description via item_update"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User',
            role=UserRole.AGENT
        )
        
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project'
        )
        
        self.item_type = ItemType.objects.create(
            key='feature',
            name='Feature',
            is_active=True
        )
        
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Test description',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
    
    def test_item_update_saves_short_description(self):
        """Test that item_update endpoint saves short_description"""
        self.client.login(username='testuser', password='testpass123')
        url = reverse('item-update', args=[self.item.id])
        
        response = self.client.post(url, {
            'title': 'Updated Title',
            'description': 'Updated description',
            'short_description': 'Updated short description',
            'status': ItemStatus.INBOX,
            'type': self.item_type.id,
            'project': self.project.id
        })
        
        self.item.refresh_from_db()
        self.assertEqual(self.item.short_description, 'Updated short description')
