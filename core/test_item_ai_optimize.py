"""
Tests for Item AI Description Optimization feature
"""

from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    User, UserRole, Project, Item, ItemType, ItemStatus, 
    Organisation, AIProvider, AIModel, Activity
)
from core.services.rag.models import RAGContext, RAGContextObject


class ItemOptimizeDescriptionAITestCase(TestCase):
    """Test cases for AI-powered item description optimization"""
    
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
            description='Test project for AI optimization'
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        
        # Create test item
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='This is a test description that needs optimization.',
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
            model_id='gpt-4',
            active=True,
            is_default=True
        )
    
    def test_optimize_description_requires_authentication(self):
        """Test that unauthenticated users cannot optimize descriptions"""
        url = reverse('item-optimize-description-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])
    
    def test_optimize_description_requires_agent_role(self):
        """Test that only users with Agent role can optimize descriptions"""
        # Login as regular user
        self.client.login(username='regular_user', password='testpass123')
        
        url = reverse('item-optimize-description-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Should return 403 Forbidden
        self.assertEqual(response.status_code, 403)
        
        # Check error message
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('Agent role', data['message'])
    
    def test_optimize_description_requires_description(self):
        """Test that items without description cannot be optimized"""
        # Create item without description
        empty_item = Item.objects.create(
            project=self.project,
            title='Empty Item',
            description='',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        url = reverse('item-optimize-description-ai', kwargs={'item_id': empty_item.id})
        response = self.client.post(url)
        
        # Should return 400 Bad Request
        self.assertEqual(response.status_code, 400)
        
        # Check error message
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('no description', data['message'])
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_optimize_description_success(self, mock_build_context, mock_execute_agent):
        """Test successful description optimization"""
        # Mock RAG context
        mock_context = RAGContext(
            query='This is a test description',
            alpha=0.5,
            summary='Found 2 related items',
            items=[
                RAGContextObject(
                    object_type='item',
                    object_id='1',
                    title='Related Item',
                    content='Related content',
                    source='items',
                    relevance_score=0.9,
                    link='/items/1/',
                    updated_at='2024-01-01T00:00:00'
                )
            ],
            stats={'total_results': 1, 'deduplicated': 1}
        )
        mock_build_context.return_value = mock_context
        
        # Mock AI agent response
        optimized_text = """# Bug: Test Issue

## Description
This is an optimized description with better structure.

## Acceptance Criteria
- [ ] Fix the issue
- [ ] Add tests

## Open Questions
- None

## Similar Tasks
- #123 Related bug fix
"""
        mock_execute_agent.return_value = optimized_text
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Get initial description
        initial_description = self.item.description
        
        # Call optimization endpoint
        url = reverse('item-optimize-description-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        
        # Verify RAG was called with correct parameters
        mock_build_context.assert_called_once()
        call_kwargs = mock_build_context.call_args[1]
        self.assertEqual(call_kwargs['query'], initial_description)
        self.assertEqual(call_kwargs['project_id'], str(self.project.id))
        self.assertEqual(call_kwargs['limit'], 10)
        
        # Verify agent was called
        mock_execute_agent.assert_called_once()
        call_kwargs = mock_execute_agent.call_args[1]
        self.assertEqual(call_kwargs['filename'], 'github-issue-creation-agent.yml')
        self.assertIn(initial_description, call_kwargs['input_text'])
        self.assertIn('Context from similar items', call_kwargs['input_text'])
        self.assertEqual(call_kwargs['user'], self.agent_user)
        
        # Verify item description was updated
        self.item.refresh_from_db()
        self.assertEqual(self.item.description, optimized_text.strip())
        self.assertNotEqual(self.item.description, initial_description)
        
        # Verify activity was logged
        activities = Activity.objects.filter(
            verb='item.description.ai_optimized',
            target_object_id=self.item.id
        )
        self.assertEqual(activities.count(), 1)
        activity = activities.first()
        self.assertEqual(activity.actor, self.agent_user)
        self.assertIn('AI', activity.summary)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_optimize_description_handles_ai_error(self, mock_build_context, mock_execute_agent):
        """Test that AI errors are handled gracefully"""
        # Mock RAG context
        mock_context = RAGContext(
            query='This is a test description',
            alpha=0.5,
            summary='No context found',
            items=[],
            stats={'total_results': 0, 'deduplicated': 0}
        )
        mock_build_context.return_value = mock_context
        
        # Mock AI agent error
        mock_execute_agent.side_effect = Exception('AI service unavailable')
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Get initial description
        initial_description = self.item.description
        
        # Call optimization endpoint
        url = reverse('item-optimize-description-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('AI service unavailable', data['message'])
        
        # Verify item description was NOT updated
        self.item.refresh_from_db()
        self.assertEqual(self.item.description, initial_description)
        
        # Verify error activity was logged
        activities = Activity.objects.filter(
            verb='item.description.ai_error',
            target_object_id=self.item.id
        )
        self.assertEqual(activities.count(), 1)
        activity = activities.first()
        self.assertEqual(activity.actor, self.agent_user)
        self.assertIn('failed', activity.summary.lower())
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_optimize_description_with_empty_rag_context(self, mock_build_context, mock_execute_agent):
        """Test optimization works even when RAG returns no context"""
        # Mock empty RAG context
        mock_context = RAGContext(
            query='This is a test description',
            alpha=0.5,
            summary='No related objects found',
            items=[],
            stats={'total_results': 0, 'deduplicated': 0}
        )
        mock_build_context.return_value = mock_context
        
        # Mock AI agent response
        mock_execute_agent.return_value = '# Optimized Description\n\nBetter formatted text.'
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Call optimization endpoint
        url = reverse('item-optimize-description-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        
        # Verify agent was called with "No additional context found" message
        call_kwargs = mock_execute_agent.call_args[1]
        self.assertIn('No additional context found', call_kwargs['input_text'])
        
        # Verify item was updated
        self.item.refresh_from_db()
        self.assertIn('Optimized Description', self.item.description)
    
    def test_optimize_description_item_not_found(self):
        """Test that 404 is returned for non-existent items"""
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Try to optimize non-existent item
        url = reverse('item-optimize-description-ai', kwargs={'item_id': 99999})
        response = self.client.post(url)
        
        # Should return 404
        self.assertEqual(response.status_code, 404)
