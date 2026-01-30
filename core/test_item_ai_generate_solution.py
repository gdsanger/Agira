"""
Tests for Item AI Solution Description Generation feature
"""

from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    User, UserRole, Project, Item, ItemType, ItemStatus, 
    Organisation, AIProvider, AIModel, Activity
)
from core.services.rag.models import RAGContext, RAGContextObject


class ItemGenerateSolutionAITestCase(TestCase):
    """Test cases for AI-powered solution description generation"""
    
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
            description='Test project for AI solution generation'
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
            title='Test Feature',
            description='Add a new user authentication system with OAuth2 support.',
            type=self.item_type,
            status=ItemStatus.BACKLOG
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
    
    def test_generate_solution_requires_authentication(self):
        """Test that unauthenticated users cannot generate solutions"""
        url = reverse('item-generate-solution-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])
    
    def test_generate_solution_requires_agent_role(self):
        """Test that only users with Agent role can generate solutions"""
        # Login as regular user
        self.client.login(username='regular_user', password='testpass123')
        
        url = reverse('item-generate-solution-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Should return 403 Forbidden
        self.assertEqual(response.status_code, 403)
        
        # Check error message
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('Agent role', data['message'])
    
    def test_generate_solution_requires_description(self):
        """Test that items without description cannot have solutions generated"""
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
        
        url = reverse('item-generate-solution-ai', kwargs={'item_id': empty_item.id})
        response = self.client.post(url)
        
        # Should return 400 Bad Request
        self.assertEqual(response.status_code, 400)
        
        # Check error message
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('no description', data['message'].lower())
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_generate_solution_success(self, mock_build_context, mock_execute_agent):
        """Test successful solution description generation"""
        # Mock RAG context
        mock_context = RAGContext(
            query='Add a new user authentication system',
            alpha=0.5,
            summary='Found 2 related items',
            items=[
                RAGContextObject(
                    object_type='item',
                    object_id='1',
                    title='OAuth2 Implementation',
                    content='Implemented OAuth2 using library XYZ',
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
        solution_text = """## Technical Solution

### Architecture
Implement OAuth2 authentication using the following approach:

1. Use passport.js library for OAuth2 provider integration
2. Support Google, GitHub, and Microsoft providers
3. Store tokens securely in encrypted database fields

### Implementation Steps
1. Install passport and provider-specific strategies
2. Configure OAuth2 credentials in environment variables
3. Create authentication routes and callbacks
4. Implement token refresh mechanism
5. Add user profile synchronization

### Security Considerations
- Use HTTPS for all OAuth callbacks
- Implement CSRF protection
- Store tokens encrypted at rest
- Set appropriate token expiration times
"""
        mock_execute_agent.return_value = solution_text
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Get initial solution (should be empty)
        initial_solution = self.item.solution_description
        
        # Call generation endpoint
        url = reverse('item-generate-solution-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        
        # Verify RAG was called with correct parameters
        mock_build_context.assert_called_once()
        call_kwargs = mock_build_context.call_args[1]
        self.assertEqual(call_kwargs['query'], self.item.description)
        self.assertEqual(call_kwargs['project_id'], str(self.project.id))
        self.assertEqual(call_kwargs['limit'], 10)
        
        # Verify agent was called
        mock_execute_agent.assert_called_once()
        call_kwargs = mock_execute_agent.call_args[1]
        self.assertEqual(call_kwargs['filename'], 'create-user-description.yml')
        self.assertIn(self.item.description, call_kwargs['input_text'])
        self.assertIn('Context from similar items', call_kwargs['input_text'])
        self.assertEqual(call_kwargs['user'], self.agent_user)
        
        # Verify item solution_description was updated
        self.item.refresh_from_db()
        self.assertEqual(self.item.solution_description, solution_text.strip())
        self.assertNotEqual(self.item.solution_description, initial_solution)
        
        # Verify activity was logged
        activities = Activity.objects.filter(
            verb='item.solution_description.ai_generated',
            target_object_id=self.item.id
        )
        self.assertEqual(activities.count(), 1)
        activity = activities.first()
        self.assertEqual(activity.actor, self.agent_user)
        self.assertIn('AI', activity.summary)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_generate_solution_handles_ai_error(self, mock_build_context, mock_execute_agent):
        """Test that AI errors are handled gracefully"""
        # Mock RAG context
        mock_context = RAGContext(
            query='Add a new user authentication system',
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
        
        # Get initial solution
        initial_solution = self.item.solution_description
        
        # Call generation endpoint
        url = reverse('item-generate-solution-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('AI service unavailable', data['message'])
        
        # Verify item solution was NOT updated
        self.item.refresh_from_db()
        self.assertEqual(self.item.solution_description, initial_solution)
        
        # Verify error activity was logged
        activities = Activity.objects.filter(
            verb='item.solution_description.ai_error',
            target_object_id=self.item.id
        )
        self.assertEqual(activities.count(), 1)
        activity = activities.first()
        self.assertEqual(activity.actor, self.agent_user)
        self.assertIn('failed', activity.summary.lower())
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_generate_solution_with_empty_rag_context(self, mock_build_context, mock_execute_agent):
        """Test solution generation works even when RAG returns no context"""
        # Mock empty RAG context
        mock_context = RAGContext(
            query='Add a new user authentication system',
            alpha=0.5,
            summary='No related objects found',
            items=[],
            stats={'total_results': 0, 'deduplicated': 0}
        )
        mock_build_context.return_value = mock_context
        
        # Mock AI agent response
        mock_execute_agent.return_value = '## Solution\n\nImplement using standard OAuth2 flow.'
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Call generation endpoint
        url = reverse('item-generate-solution-ai', kwargs={'item_id': self.item.id})
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
        self.assertIn('Solution', self.item.solution_description)
    
    def test_generate_solution_item_not_found(self):
        """Test that 404 is returned for non-existent items"""
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Try to generate solution for non-existent item
        url = reverse('item-generate-solution-ai', kwargs={'item_id': 99999})
        response = self.client.post(url)
        
        # Should return 404
        self.assertEqual(response.status_code, 404)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_generate_solution_overwrites_existing(self, mock_build_context, mock_execute_agent):
        """Test that generating a solution overwrites existing solution description"""
        # Set existing solution
        self.item.solution_description = 'Old solution description'
        self.item.save()
        
        # Mock RAG and agent
        mock_context = RAGContext(
            query='Test',
            alpha=0.5,
            summary='Found context',
            items=[],
            stats={}
        )
        mock_build_context.return_value = mock_context
        mock_execute_agent.return_value = 'New AI-generated solution'
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Call generation endpoint
        url = reverse('item-generate-solution-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        
        # Verify solution was overwritten
        self.item.refresh_from_db()
        self.assertEqual(self.item.solution_description, 'New AI-generated solution')
        self.assertNotIn('Old solution', self.item.solution_description)
