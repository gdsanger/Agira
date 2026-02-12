"""
Tests for Open Questions feature
"""

from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
import json

from core.models import (
    User, UserRole, Project, Item, ItemType, ItemStatus, 
    Organisation, AIProvider, AIModel,
    IssueOpenQuestion, IssueStandardAnswer, 
    OpenQuestionStatus, OpenQuestionSource, OpenQuestionAnswerType
)
from core.views import RAG_NO_CONTEXT_MESSAGE


class IssueStandardAnswerModelTest(TestCase):
    """Test cases for IssueStandardAnswer model"""
    
    def setUp(self):
        """Set up test data"""
        self.answer, _ = IssueStandardAnswer.objects.get_or_create(
            key='test_answer',
            defaults={
                'label': 'Test Answer',
                'text': 'This is a test answer',
                'is_active': True,
                'sort_order': 10
            }
        )
    
    def test_create_standard_answer(self):
        """Test creating a standard answer"""
        self.assertEqual(self.answer.key, 'test_answer')
        self.assertEqual(self.answer.label, 'Test Answer')
        self.assertTrue(self.answer.is_active)
    
    def test_str_representation(self):
        """Test string representation"""
        self.assertEqual(str(self.answer), 'Test Answer')
    
    def test_ordering(self):
        """Test default ordering by sort_order"""
        answer2, _ = IssueStandardAnswer.objects.get_or_create(
            key='answer2',
            defaults={
                'label': 'Answer 2',
                'text': 'Text 2',
                'sort_order': 5
            }
        )
        
        # Filter to only our test answers
        answers = list(IssueStandardAnswer.objects.filter(key__in=['answer2', 'test_answer']))
        self.assertEqual(len(answers), 2)
        self.assertEqual(answers[0].key, 'answer2')  # Lower sort_order first
        self.assertEqual(answers[1].key, 'test_answer')



class IssueOpenQuestionModelTest(TestCase):
    """Test cases for IssueOpenQuestion model"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organisation.objects.create(name='Test Org')
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug', is_active=True)
        self.user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass',
            name='Test User'
        )
        
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Test description',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        self.standard_answer, _ = IssueStandardAnswer.objects.get_or_create(
            key='copilot_decides',
            defaults={
                'label': 'Copilot decides',
                'text': 'Copilot kann das selbst entscheiden'
            }
        )
        
        self.question = IssueOpenQuestion.objects.create(
            issue=self.item,
            question='What should happen in case X?',
            source=OpenQuestionSource.AI_AGENT
        )
    
    def test_create_open_question(self):
        """Test creating an open question"""
        self.assertEqual(self.question.question, 'What should happen in case X?')
        self.assertEqual(self.question.status, OpenQuestionStatus.OPEN)
        self.assertEqual(self.question.source, OpenQuestionSource.AI_AGENT)
        self.assertIsNone(self.question.answered_at)
    
    def test_str_representation(self):
        """Test string representation"""
        str_repr = str(self.question)
        self.assertIn('Test Item', str_repr)
        self.assertIn('What should happen', str_repr)
    
    def test_answer_with_standard_answer(self):
        """Test answering with a standard answer"""
        self.question.answer_type = OpenQuestionAnswerType.STANDARD_ANSWER
        self.question.standard_answer = self.standard_answer
        self.question.standard_answer_key = self.standard_answer.key
        self.question.status = OpenQuestionStatus.ANSWERED
        self.question.answered_at = timezone.now()
        self.question.answered_by = self.user
        self.question.save()
        
        self.assertEqual(self.question.status, OpenQuestionStatus.ANSWERED)
        self.assertEqual(self.question.get_answer_display_text(), self.standard_answer.text)
        self.assertIsNotNone(self.question.answered_at)
    
    def test_answer_with_free_text(self):
        """Test answering with free text"""
        self.question.answer_type = OpenQuestionAnswerType.FREE_TEXT
        self.question.answer_text = 'This is a custom answer'
        self.question.status = OpenQuestionStatus.ANSWERED
        self.question.answered_at = timezone.now()
        self.question.answered_by = self.user
        self.question.save()
        
        self.assertEqual(self.question.status, OpenQuestionStatus.ANSWERED)
        self.assertEqual(self.question.get_answer_display_text(), 'This is a custom answer')
    
    def test_dismiss_question(self):
        """Test dismissing a question"""
        self.question.status = OpenQuestionStatus.DISMISSED
        self.question.answered_at = timezone.now()
        self.question.answered_by = self.user
        self.question.save()
        
        self.assertEqual(self.question.status, OpenQuestionStatus.DISMISSED)
        self.assertIsNotNone(self.question.answered_at)
        self.assertEqual(self.question.get_answer_display_text(), '')


class ItemOptimizeWithOpenQuestionsTest(TestCase):
    """Test cases for item optimization with open questions"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        self.agent_user = User.objects.create_user(
            username='agent_user',
            email='agent@test.com',
            password='testpass123',
            name='Agent User',
            role=UserRole.AGENT
        )
        
        self.org = Organisation.objects.create(name='Test Org')
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug', is_active=True)
        
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='This is a test description.',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Create AI provider and model
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
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_optimize_with_json_response_and_open_questions(self, mock_build_context, mock_execute_agent):
        """Test optimization with JSON response containing open questions"""
        # Mock RAG context
        from core.services.rag.models import RAGContext
        mock_context = RAGContext(
            query='Test description',
            alpha=0.5,
            summary='No context found',
            items=[],
            stats={'total_results': 0, 'deduplicated': 0}
        )
        mock_build_context.return_value = mock_context
        
        # Mock AI agent response with JSON contract
        agent_response = json.dumps({
            "issue": {
                "description": "# Optimized Description\n\nThis is the improved description."
            },
            "open_questions": [
                "What should happen if field X is empty?",
                "Can we delete items with dependencies?"
            ]
        })
        mock_execute_agent.return_value = agent_response
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Call optimization endpoint
        url = reverse('item-optimize-description-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        
        # Verify item description was updated (only the issue.description part)
        self.item.refresh_from_db()
        self.assertIn('Optimized Description', self.item.description)
        self.assertIn('improved description', self.item.description)
        
        # Verify open questions were created
        questions = IssueOpenQuestion.objects.filter(issue=self.item)
        self.assertEqual(questions.count(), 2)
        
        question_texts = [q.question for q in questions]
        self.assertIn("What should happen if field X is empty?", question_texts)
        self.assertIn("Can we delete items with dependencies?", question_texts)
        
        # Verify all questions are marked as open and from AI agent
        for question in questions:
            self.assertEqual(question.status, OpenQuestionStatus.OPEN)
            self.assertEqual(question.source, OpenQuestionSource.AI_AGENT)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_optimize_with_plain_text_fallback(self, mock_build_context, mock_execute_agent):
        """Test optimization with plain text response (fallback)"""
        from core.services.rag.models import RAGContext
        mock_context = RAGContext(
            query='Test description',
            alpha=0.5,
            summary='No context found',
            items=[],
            stats={'total_results': 0, 'deduplicated': 0}
        )
        mock_build_context.return_value = mock_context
        
        # Mock AI agent response with plain text (no JSON)
        mock_execute_agent.return_value = "# Plain Text Response\n\nThis is not JSON."
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Call optimization endpoint
        url = reverse('item-optimize-description-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        
        # Verify item description was updated
        self.item.refresh_from_db()
        self.assertIn('Plain Text Response', self.item.description)
        
        # Verify no open questions were created
        questions = IssueOpenQuestion.objects.filter(issue=self.item)
        self.assertEqual(questions.count(), 0)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    @patch('core.services.rag.service.RAGPipelineService.build_context')
    def test_duplicate_questions_not_created(self, mock_build_context, mock_execute_agent):
        """Test that duplicate open questions are not created"""
        from core.services.rag.models import RAGContext
        mock_context = RAGContext(
            query='Test description',
            alpha=0.5,
            summary='No context found',
            items=[],
            stats={'total_results': 0, 'deduplicated': 0}
        )
        mock_build_context.return_value = mock_context
        
        # Create existing question
        IssueOpenQuestion.objects.create(
            issue=self.item,
            question="What should happen if field X is empty?",
            source=OpenQuestionSource.AI_AGENT,
            status=OpenQuestionStatus.OPEN
        )
        
        # Mock AI agent response with same question
        agent_response = json.dumps({
            "issue": {
                "description": "# Updated Description"
            },
            "open_questions": [
                "What should happen if field X is empty?",  # Duplicate
                "New question?"
            ]
        })
        mock_execute_agent.return_value = agent_response
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        # Call optimization endpoint
        url = reverse('item-optimize-description-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        
        # Verify only one new question was created (duplicate was skipped)
        questions = IssueOpenQuestion.objects.filter(issue=self.item)
        self.assertEqual(questions.count(), 2)  # 1 existing + 1 new


class OpenQuestionsAPITest(TestCase):
    """Test cases for open questions API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass123',
            name='Test User'
        )
        
        self.org = Organisation.objects.create(name='Test Org')
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug', is_active=True)
        
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Test description',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        self.standard_answer, _ = IssueStandardAnswer.objects.get_or_create(
            key='copilot_decides',
            defaults={
                'label': 'Copilot decides',
                'text': 'Copilot kann das selbst entscheiden'
            }
        )
        
        self.question = IssueOpenQuestion.objects.create(
            issue=self.item,
            question='What should happen in case X?',
            source=OpenQuestionSource.AI_AGENT
        )
    
    def test_list_open_questions(self):
        """Test listing open questions for an item"""
        self.client.login(username='testuser', password='testpass123')
        
        url = reverse('item-open-questions-list', kwargs={'item_id': self.item.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(len(data['questions']), 1)
        self.assertTrue(data['has_open'])
        
        question_data = data['questions'][0]
        self.assertEqual(question_data['question'], 'What should happen in case X?')
        self.assertEqual(question_data['status'], 'Open')
    
    def test_answer_question_with_standard_answer(self):
        """Test answering a question with a standard answer"""
        self.client.login(username='testuser', password='testpass123')
        
        url = reverse('item-open-question-answer', kwargs={'question_id': self.question.id})
        payload = {
            'action': 'answer',
            'answer_type': 'standard_answer',
            'standard_answer_id': self.standard_answer.id
        }
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'Answered')
        self.assertEqual(data['answer'], self.standard_answer.text)
        
        # Verify in database
        self.question.refresh_from_db()
        self.assertEqual(self.question.status, OpenQuestionStatus.ANSWERED)
        self.assertEqual(self.question.standard_answer, self.standard_answer)
        self.assertEqual(self.question.answered_by, self.user)
        self.assertIsNotNone(self.question.answered_at)
    
    def test_answer_question_with_free_text(self):
        """Test answering a question with free text"""
        self.client.login(username='testuser', password='testpass123')
        
        url = reverse('item-open-question-answer', kwargs={'question_id': self.question.id})
        payload = {
            'action': 'answer',
            'answer_type': 'free_text',
            'answer_text': 'This is my custom answer'
        }
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['answer'], 'This is my custom answer')
        
        # Verify in database
        self.question.refresh_from_db()
        self.assertEqual(self.question.status, OpenQuestionStatus.ANSWERED)
        self.assertEqual(self.question.answer_text, 'This is my custom answer')
        self.assertEqual(self.question.answer_type, OpenQuestionAnswerType.FREE_TEXT)
    
    def test_dismiss_question(self):
        """Test dismissing a question"""
        self.client.login(username='testuser', password='testpass123')
        
        url = reverse('item-open-question-answer', kwargs={'question_id': self.question.id})
        payload = {
            'action': 'dismiss'
        }
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['status'], 'Dismissed')
        
        # Verify in database
        self.question.refresh_from_db()
        self.assertEqual(self.question.status, OpenQuestionStatus.DISMISSED)
        self.assertEqual(self.question.answered_by, self.user)
        self.assertIsNotNone(self.question.answered_at)
    
    def test_answer_requires_authentication(self):
        """Test that answering requires authentication"""
        url = reverse('item-open-question-answer', kwargs={'question_id': self.question.id})
        payload = {'action': 'dismiss'}
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])
    
    def test_invalid_action(self):
        """Test invalid action parameter"""
        self.client.login(username='testuser', password='testpass123')
        
        url = reverse('item-open-question-answer', kwargs={'question_id': self.question.id})
        payload = {'action': 'invalid_action'}
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid action', data['error'])
    
    def test_free_text_answer_requires_text(self):
        """Test that free text answer requires answer_text"""
        self.client.login(username='testuser', password='testpass123')
        
        url = reverse('item-open-question-answer', kwargs={'question_id': self.question.id})
        payload = {
            'action': 'answer',
            'answer_type': 'free_text',
            'answer_text': ''  # Empty
        }
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Answer text is required', data['error'])
    
    def test_answered_questions_synced_to_description(self):
        """Test that answered questions are appended to item description"""
        self.client.login(username='testuser', password='testpass123')
        
        # Store original description
        original_description = self.item.description
        
        # Answer the question
        url = reverse('item-open-question-answer', kwargs={'question_id': self.question.id})
        payload = {
            'action': 'answer',
            'answer_type': 'standard_answer',
            'standard_answer_id': self.standard_answer.id
        }
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify description was updated
        self.item.refresh_from_db()
        self.assertIn('## Offene Fragen', self.item.description)
        self.assertIn('[x]', self.item.description)
        self.assertIn(self.question.question, self.item.description)
        self.assertIn(self.standard_answer.text, self.item.description)
        
        # Create another question and answer it
        question2 = IssueOpenQuestion.objects.create(
            issue=self.item,
            question='Second question?',
            source=OpenQuestionSource.AI_AGENT
        )
        
        url2 = reverse('item-open-question-answer', kwargs={'question_id': question2.id})
        payload2 = {
            'action': 'answer',
            'answer_type': 'free_text',
            'answer_text': 'Custom answer for second question'
        }
        
        response2 = self.client.post(
            url2,
            data=json.dumps(payload2),
            content_type='application/json'
        )
        
        self.assertEqual(response2.status_code, 200)
        
        # Verify both questions are in description
        self.item.refresh_from_db()
        self.assertIn(question2.question, self.item.description)
        self.assertIn('Custom answer for second question', self.item.description)
    
    def test_dismissed_questions_synced_to_description(self):
        """Test that dismissed questions are also added to description"""
        self.client.login(username='testuser', password='testpass123')
        
        # Dismiss the question
        url = reverse('item-open-question-answer', kwargs={'question_id': self.question.id})
        payload = {
            'action': 'dismiss'
        }
        
        response = self.client.post(
            url,
            data=json.dumps(payload),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify description was updated
        self.item.refresh_from_db()
        self.assertIn('## Offene Fragen', self.item.description)
        self.assertIn('[x]', self.item.description)
        self.assertIn(self.question.question, self.item.description)



class ItemAnswerQuestionAITest(TestCase):
    """Test cases for AI-powered question answering"""
    
    def setUp(self):
        """Set up test data"""
        self.org = Organisation.objects.create(name='Test Org')
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='feature', name='Feature', is_active=True)
        
        # Create agent user
        self.agent_user = User.objects.create_user(
            username='agent',
            email='agent@test.com',
            password='testpass123',
            name='Agent User',
            role=UserRole.AGENT
        )
        
        # Create regular user
        self.regular_user = User.objects.create_user(
            username='regular',
            email='regular@test.com',
            password='testpass123',
            name='Regular User',
            role=UserRole.TEAM_MEMBER
        )
        
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Test description',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        self.question = IssueOpenQuestion.objects.create(
            issue=self.item,
            question='How should the authentication be implemented?',
            source=OpenQuestionSource.AI_AGENT,
            status=OpenQuestionStatus.OPEN
        )
        
        self.client = Client()
    
    @patch('core.views.AgentService')
    @patch('core.views.build_context')
    def test_answer_question_with_ai_success(self, mock_build_context, mock_agent_service):
        """Test successfully answering a question with AI"""
        # Mock RAG context
        mock_rag_context = Mock()
        mock_rag_context.items = [Mock()]
        mock_rag_context.to_context_text.return_value = "Context: Use OAuth 2.0 for authentication"
        mock_build_context.return_value = mock_rag_context
        
        # Mock agent response
        mock_service_instance = Mock()
        mock_service_instance.execute_agent.return_value = "- Use OAuth 2.0\n- Implement JWT tokens\n- Add refresh token rotation"
        mock_agent_service.return_value = mock_service_instance
        
        # Login as agent
        self.client.login(username='agent', password='testpass123')
        
        url = reverse('item-answer-question-ai', kwargs={'question_id': self.question.id})
        response = self.client.post(url, content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data['status'], 'success')
        self.assertIn('Use OAuth 2.0', data['answer'])
        self.assertEqual(data['question_id'], self.question.id)
        
        # Verify question was updated in database
        self.question.refresh_from_db()
        self.assertEqual(self.question.status, OpenQuestionStatus.ANSWERED)
        self.assertEqual(self.question.answer_type, OpenQuestionAnswerType.FREE_TEXT)
        self.assertIn('Use OAuth 2.0', self.question.answer_text)
        self.assertEqual(self.question.answered_by, self.agent_user)
        self.assertIsNotNone(self.question.answered_at)
        
        # Verify RAG context was built correctly
        mock_build_context.assert_called_once()
        call_kwargs = mock_build_context.call_args[1]
        self.assertEqual(call_kwargs['query'], self.question.question)
        self.assertEqual(call_kwargs['project_id'], str(self.item.project.id))
        self.assertEqual(call_kwargs['limit'], 10)
        
        # Verify agent was called correctly
        mock_service_instance.execute_agent.assert_called_once()
        call_kwargs = mock_service_instance.execute_agent.call_args[1]
        self.assertEqual(call_kwargs['filename'], 'item-answer-question.yml')
        self.assertIn(self.question.question, call_kwargs['input_text'])
        self.assertIn("Context: Use OAuth 2.0", call_kwargs['input_text'])
        self.assertEqual(call_kwargs['user'], self.agent_user)
    
    def test_answer_question_ai_requires_agent_role(self):
        """Test that AI answering requires AGENT role"""
        self.client.login(username='regular', password='testpass123')
        
        url = reverse('item-answer-question-ai', kwargs={'question_id': self.question.id})
        response = self.client.post(url, content_type='application/json')
        
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('Agent role', data['message'])
        
        # Question should remain unchanged
        self.question.refresh_from_db()
        self.assertEqual(self.question.status, OpenQuestionStatus.OPEN)
        self.assertIsNone(self.question.answer_text)
    
    def test_answer_question_ai_requires_authentication(self):
        """Test that AI answering requires authentication"""
        url = reverse('item-answer-question-ai', kwargs={'question_id': self.question.id})
        response = self.client.post(url, content_type='application/json')
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
    
    def test_answer_question_ai_only_open_questions(self):
        """Test that AI can only answer open questions"""
        # Mark question as already answered
        self.question.status = OpenQuestionStatus.ANSWERED
        self.question.answer_text = "Already answered"
        self.question.save()
        
        self.client.login(username='agent', password='testpass123')
        
        url = reverse('item-answer-question-ai', kwargs={'question_id': self.question.id})
        response = self.client.post(url, content_type='application/json')
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('Only open questions', data['message'])
    
    def test_answer_question_ai_nonexistent_question(self):
        """Test handling of non-existent question"""
        self.client.login(username='agent', password='testpass123')
        
        url = reverse('item-answer-question-ai', kwargs={'question_id': 99999})
        response = self.client.post(url, content_type='application/json')
        
        self.assertEqual(response.status_code, 404)
    
    @patch('core.views.AgentService')
    @patch('core.views.build_context')
    def test_answer_question_ai_handles_agent_error(self, mock_build_context, mock_agent_service):
        """Test handling of agent execution errors"""
        # Mock RAG context
        mock_rag_context = Mock()
        mock_rag_context.items = [Mock()]
        mock_rag_context.to_context_text.return_value = "Some context"
        mock_build_context.return_value = mock_rag_context
        
        # Mock agent error
        mock_service_instance = Mock()
        mock_service_instance.execute_agent.side_effect = Exception("AI service unavailable")
        mock_agent_service.return_value = mock_service_instance
        
        self.client.login(username='agent', password='testpass123')
        
        url = reverse('item-answer-question-ai', kwargs={'question_id': self.question.id})
        response = self.client.post(url, content_type='application/json')
        
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('AI service unavailable', data['message'])
        
        # Question should remain unanswered
        self.question.refresh_from_db()
        self.assertEqual(self.question.status, OpenQuestionStatus.OPEN)
        self.assertIsNone(self.question.answer_text)
    
    @patch('core.views.AgentService')
    @patch('core.views.build_context')
    def test_answer_question_ai_empty_response(self, mock_build_context, mock_agent_service):
        """Test handling of empty AI response"""
        # Mock RAG context
        mock_rag_context = Mock()
        mock_rag_context.items = [Mock()]
        mock_rag_context.to_context_text.return_value = "Some context"
        mock_build_context.return_value = mock_rag_context
        
        # Mock empty agent response
        mock_service_instance = Mock()
        mock_service_instance.execute_agent.return_value = "  "  # Empty/whitespace
        mock_agent_service.return_value = mock_service_instance
        
        self.client.login(username='agent', password='testpass123')
        
        url = reverse('item-answer-question-ai', kwargs={'question_id': self.question.id})
        response = self.client.post(url, content_type='application/json')
        
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('empty answer', data['message'])
    
    @patch('core.views.AgentService')
    @patch('core.views.build_context')
    def test_answer_question_ai_syncs_to_description(self, mock_build_context, mock_agent_service):
        """Test that answering updates the item description"""
        # Mock RAG context
        mock_rag_context = Mock()
        mock_rag_context.items = [Mock()]
        mock_rag_context.to_context_text.return_value = "Context"
        mock_build_context.return_value = mock_rag_context
        
        # Mock agent response
        mock_service_instance = Mock()
        mock_service_instance.execute_agent.return_value = "- Answer point 1\n- Answer point 2"
        mock_agent_service.return_value = mock_service_instance
        
        self.client.login(username='agent', password='testpass123')
        
        url = reverse('item-answer-question-ai', kwargs={'question_id': self.question.id})
        response = self.client.post(url, content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item description was updated with the answered question
        self.item.refresh_from_db()
        self.assertIn('## Offene Fragen', self.item.description)
        self.assertIn(self.question.question, self.item.description)
        self.assertIn('[x]', self.item.description)
        self.assertIn('Answer point 1', self.item.description)
    
    @patch('core.views.AgentService')
    @patch('core.views.build_context')
    def test_answer_question_ai_with_no_rag_context(self, mock_build_context, mock_agent_service):
        """Test answering when no RAG context is available"""
        # Mock empty RAG context
        mock_rag_context = Mock()
        mock_rag_context.items = []
        mock_rag_context.to_context_text.return_value = ""
        mock_build_context.return_value = mock_rag_context
        
        # Mock agent response indicating no context
        mock_service_instance = Mock()
        mock_service_instance.execute_agent.return_value = "Nicht beantwortbar auf Basis des gegebenen Kontexts."
        mock_agent_service.return_value = mock_service_instance
        
        self.client.login(username='agent', password='testpass123')
        
        url = reverse('item-answer-question-ai', kwargs={'question_id': self.question.id})
        response = self.client.post(url, content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Should still succeed, but with a "not answerable" response
        self.assertEqual(data['status'], 'success')
        self.assertIn('Nicht beantwortbar', data['answer'])
        
        # Verify the agent input included the "no context" message
        call_kwargs = mock_service_instance.execute_agent.call_args[1]
        self.assertIn(RAG_NO_CONTEXT_MESSAGE, call_kwargs['input_text'])
