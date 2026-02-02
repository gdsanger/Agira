"""
Verification test for the issue: AI Description optimization API response processing

This test demonstrates that when the AI agent returns JSON in the format:
{
  "issue": {
    "description": "Full issue text"
  },
  "open_questions": ["Question 1", "Question 2"]
}

The system correctly:
1. Saves ONLY issue.description to item.Description
2. Creates IssueOpenQuestion records for each question
"""

from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
import json

from core.models import (
    User, UserRole, Project, Item, ItemType, ItemStatus,
    Organisation, AIProvider, AIModel, IssueOpenQuestion,
    OpenQuestionStatus, OpenQuestionSource
)


class IssueVerificationTest(TestCase):
    """Verify that the issue described in the bug report is fixed"""
    
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
            description='Original description to optimize',
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
    def test_issue_fix_verification(self, mock_build_context, mock_execute_agent):
        """
        Verify the fix for: API Response incorrectly saves entire JSON to Description
        
        EXPECTED BEHAVIOR (as per issue):
        1. issue.description should be saved to item.Description
        2. Each question in open_questions should create an IssueOpenQuestion record
        
        INCORRECT BEHAVIOR (the bug):
        - The entire JSON response would be saved to item.Description
        """
        # Mock RAG context
        from core.services.rag.models import RAGContext
        mock_context = RAGContext(
            query='Test',
            alpha=0.5,
            summary='No context',
            items=[],
            stats={'total_results': 0, 'deduplicated': 0}
        )
        mock_build_context.return_value = mock_context
        
        # Mock AI agent response - exactly as described in the issue
        agent_response_json = {
            "issue": {
                "description": "Vollständiger Issue-Text (Markdown)\n\n## Problem\nDetailed description here..."
            },
            "open_questions": [
                "Was soll passieren, wenn Feld X leer ist?",
                "Darf Objekt Y gelöscht werden, wenn untergeordnete Elemente existieren?"
            ]
        }
        
        # The agent returns this as a JSON string
        mock_execute_agent.return_value = json.dumps(agent_response_json)
        
        # Login and call the endpoint
        self.client.login(username='agent_user', password='testpass123')
        url = reverse('item-optimize-description-ai', kwargs={'item_id': self.item.id})
        response = self.client.post(url)
        
        # Verify success
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['status'], 'ok')
        
        # VERIFICATION 1: Only issue.description should be in item.Description
        # NOT the entire JSON!
        self.item.refresh_from_db()
        
        print(f"\n=== VERIFICATION RESULTS ===")
        print(f"Item Description saved: {self.item.description[:100]}...")
        print(f"Expected: 'Vollständiger Issue-Text (Markdown)'")
        print(f"Length: {len(self.item.description)} characters")
        
        # Check that description contains only the issue text, not JSON
        self.assertIn('Vollständiger Issue-Text', self.item.description)
        self.assertIn('Detailed description here', self.item.description)
        
        # CRITICAL: Ensure NO JSON structure in description
        self.assertNotIn('"issue":', self.item.description)
        self.assertNotIn('"open_questions":', self.item.description)
        self.assertNotIn('"description":', self.item.description)
        self.assertNotIn('{', self.item.description)  # No JSON braces
        
        # VERIFICATION 2: Open questions should be created separately
        questions = IssueOpenQuestion.objects.filter(issue=self.item)
        self.assertEqual(questions.count(), 2, 
                        f"Expected 2 questions, got {questions.count()}")
        
        question_texts = [q.question for q in questions]
        print(f"\nOpen Questions created:")
        for i, q in enumerate(question_texts, 1):
            print(f"  {i}. {q}")
        
        # Verify the exact questions from the issue
        self.assertIn("Was soll passieren, wenn Feld X leer ist?", question_texts)
        self.assertIn("Darf Objekt Y gelöscht werden, wenn untergeordnete Elemente existieren?", 
                     question_texts)
        
        # Verify question metadata
        for question in questions:
            self.assertEqual(question.status, OpenQuestionStatus.OPEN)
            self.assertEqual(question.source, OpenQuestionSource.AI_AGENT)
            self.assertEqual(question.issue, self.item)
        
        print(f"\n✅ VERIFICATION PASSED: Issue is correctly fixed!")
        print(f"   - Description contains ONLY the issue text (not JSON)")
        print(f"   - 2 Open questions were created correctly")
        print(f"   - Questions are linked to the item via FK")
        print(f"   - Questions have correct status (Open) and source (AIAgent)")


if __name__ == '__main__':
    import django
    import os
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agira.test_settings')
    django.setup()
    
    from django.test.runner import DiscoverRunner
    runner = DiscoverRunner(verbosity=2)
    runner.run_tests(['__main__'])
