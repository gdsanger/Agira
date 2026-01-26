"""
Tests for Item Pre-Review feature with AI agent
"""

from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    User, UserRole, Project, Item, ItemType, ItemStatus, ItemComment, CommentKind,
    Organisation, AIProvider, AIModel, Activity
)
from core.services.rag.models import RAGContext, RAGContextObject


class ItemPreReviewTestCase(TestCase):
    """Test cases for AI-powered item pre-review"""
    
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
            description='Test project for AI pre-review'
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
            title='Add Pre-Review Feature',
            description='We need to add a pre-review feature that analyzes items using AI.',
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
            name='GPT-4',
            model_id='gpt-4',
            active=True,
            is_default=True
        )
    
    def test_pre_review_requires_authentication(self):
        """Test that unauthenticated users cannot trigger pre-review"""
        url = reverse('item-pre-review', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])
    
    def test_pre_review_requires_agent_role(self):
        """Test that only users with Agent role can trigger pre-review"""
        # Login as regular user
        self.client.login(username='regular_user', password='testpass123')
        
        url = reverse('item-pre-review', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Should return 403 Forbidden
        self.assertEqual(response.status_code, 403)
        
        # Check error message
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Agent role', data['error'])
    
    def test_pre_review_requires_description(self):
        """Test that items without description cannot be reviewed"""
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
        
        url = reverse('item-pre-review', kwargs={'item_id': empty_item.id})
        response = self.client.post(url)
        
        # Should return 400 Bad Request
        self.assertEqual(response.status_code, 400)
        
        # Check error message
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('no description', data['error'])
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_pre_review_success(self, mock_build_context, mock_execute_agent):
        """Test successful pre-review generation"""
        # Mock RAG context
        mock_context = RAGContext(
            query=self.item.description,
            alpha=0.5,
            summary='Found 2 related items',
            items=[
                RAGContextObject(
                    object_type='item',
                    object_id='2',
                    title='Similar Feature',
                    content='Similar feature implementation',
                    source='items',
                    relevance_score=0.85,
                    link='/items/2/',
                    updated_at='2024-01-01T00:00:00'
                )
            ],
            stats={'total_results': 1, 'deduplicated': 1}
        )
        mock_build_context.return_value = mock_context
        
        # Mock AI agent response
        review_text = """## Zusammenfassung
Die Feature-Anfrage beschreibt die Implementierung einer Pre-Review-Funktionalität.

## Vollständigkeit
Die Beschreibung ist sehr knapp gehalten. Folgende Details fehlen:
- Technische Anforderungen
- Akzeptanzkriterien
- UI/UX Spezifikationen

## Ähnliche/Verwandte Issues
- #2 Ähnliche Feature-Implementierung gefunden

## Empfehlungen
1. Detaillierte Akzeptanzkriterien ergänzen
2. UI-Mockups hinzufügen
3. Technische Architektur skizzieren

## Risiken & Hinweise
- AI-Integration erfordert entsprechende API-Konfiguration
- Performance-Aspekte bei RAG-Suche beachten
"""
        mock_execute_agent.return_value = review_text
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Call pre-review endpoint
        url = reverse('item-pre-review', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('review', data)
        self.assertIn('review_html', data)
        self.assertEqual(data['review'], review_text)
        
        # Verify RAG was called
        mock_build_context.assert_called_once()
        call_kwargs = mock_build_context.call_args[1]
        self.assertEqual(call_kwargs['query'], self.item.description)
        self.assertEqual(call_kwargs['project_id'], str(self.project.id))
        
        # Verify agent was called with correct filename
        mock_execute_agent.assert_called_once()
        call_kwargs = mock_execute_agent.call_args[1]
        self.assertEqual(call_kwargs['filename'], 'issue-analyse-agent.yml')
        self.assertIn(self.item.title, call_kwargs['input_text'])
        self.assertIn(self.item.description, call_kwargs['input_text'])
        
        # Verify activity was logged
        activities = Activity.objects.filter(
            verb='item.pre_review.generated',
            target_object_id=self.item.id
        )
        self.assertEqual(activities.count(), 1)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_pre_review_handles_ai_error(self, mock_build_context, mock_execute_agent):
        """Test that AI errors are handled gracefully"""
        # Mock RAG context
        mock_context = RAGContext(
            query=self.item.description,
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
        
        # Call pre-review endpoint
        url = reverse('item-pre-review', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('AI service unavailable', data['error'])
        
        # Verify error activity was logged
        activities = Activity.objects.filter(
            verb='item.pre_review.error',
            target_object_id=self.item.id
        )
        self.assertEqual(activities.count(), 1)
    
    def test_save_pre_review_requires_authentication(self):
        """Test that unauthenticated users cannot save pre-review"""
        url = reverse('item-save-pre-review', kwargs={'item_id': self.item.id})
        response = self.client.post(
            url,
            data='{"review": "Test review"}',
            content_type='application/json'
        )
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])
    
    def test_save_pre_review_requires_agent_role(self):
        """Test that only users with Agent role can save pre-review"""
        # Login as regular user
        self.client.login(username='regular_user', password='testpass123')
        
        url = reverse('item-save-pre-review', kwargs={'item_id': self.item.id})
        response = self.client.post(
            url,
            data='{"review": "Test review"}',
            content_type='application/json'
        )
        
        # Should return 403 Forbidden
        self.assertEqual(response.status_code, 403)
    
    def test_save_pre_review_success(self):
        """Test successful saving of pre-review as comment"""
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        review_content = "## AI Pre-Review\n\nThis is a test review with some recommendations."
        
        import json
        
        # Call save endpoint
        url = reverse('item-save-pre-review', kwargs={'item_id': self.item.id})
        response = self.client.post(
            url,
            data=json.dumps({'review': review_content}),
            content_type='application/json'
        )
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('comment_id', data)
        
        # Verify comment was created
        comment = ItemComment.objects.get(id=data['comment_id'])
        self.assertEqual(comment.item, self.item)
        self.assertEqual(comment.author, self.agent_user)
        self.assertEqual(comment.body, review_content)
        self.assertEqual(comment.kind, CommentKind.AI_GENERATED)
        self.assertEqual(comment.subject, 'AI Pre-Review')
        
        # Verify activity was logged
        activities = Activity.objects.filter(
            verb='item.comment.ai_review_saved',
            target_object_id=self.item.id
        )
        self.assertEqual(activities.count(), 1)
    
    def test_save_pre_review_requires_content(self):
        """Test that empty review content is rejected"""
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Call save endpoint with empty content
        url = reverse('item-save-pre-review', kwargs={'item_id': self.item.id})
        response = self.client.post(
            url,
            data='{"review": ""}',
            content_type='application/json'
        )
        
        # Should return 400 Bad Request
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('No review content', data['error'])
    
    def test_save_pre_review_handles_invalid_json(self):
        """Test that invalid JSON is handled gracefully"""
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Call save endpoint with invalid JSON
        url = reverse('item-save-pre-review', kwargs={'item_id': self.item.id})
        response = self.client.post(
            url,
            data='invalid json',
            content_type='application/json'
        )
        
        # Should return 400 Bad Request
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid JSON', data['error'])
    
    def test_multiple_pre_reviews_create_separate_comments(self):
        """Test that multiple pre-reviews create separate comments"""
        import json
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        url = reverse('item-save-pre-review', kwargs={'item_id': self.item.id})
        
        # Save first review
        response1 = self.client.post(
            url,
            data=json.dumps({'review': 'First review'}),
            content_type='application/json'
        )
        self.assertEqual(response1.status_code, 200)
        
        # Save second review
        response2 = self.client.post(
            url,
            data=json.dumps({'review': 'Second review'}),
            content_type='application/json'
        )
        self.assertEqual(response2.status_code, 200)
        
        # Verify two separate comments were created
        ai_comments = ItemComment.objects.filter(
            item=self.item,
            kind=CommentKind.AI_GENERATED
        )
        self.assertEqual(ai_comments.count(), 2)
        
        # Verify they have different content
        bodies = set(comment.body for comment in ai_comments)
        self.assertEqual(len(bodies), 2)
        self.assertIn('First review', bodies)
        self.assertIn('Second review', bodies)
