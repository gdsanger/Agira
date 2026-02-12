"""
Tests for RAG Retrieval Raw feature
"""

from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    User, UserRole, Project, Item, ItemType, ItemStatus, 
    Organisation
)
from core.services.rag.models import RAGContext, RAGContextObject


class ItemRagRetrievalRawTestCase(TestCase):
    """Test cases for RAG retrieval raw results display"""
    
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
            description='Test project for RAG retrieval'
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
            description='This is a test description for RAG retrieval.',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
    
    def test_rag_retrieval_requires_authentication(self):
        """Test that unauthenticated users cannot access RAG retrieval"""
        url = reverse('item-rag-retrieval-raw', kwargs={'item_id': self.item.id})
        response = self.client.get(url)
        
        # Should redirect to login or return 403
        self.assertIn(response.status_code, [302, 403])
    
    def test_rag_retrieval_requires_agent_role(self):
        """Test that only users with Agent role can access RAG retrieval"""
        # Login as regular user
        self.client.login(username='regular_user', password='testpass123')
        
        url = reverse('item-rag-retrieval-raw', kwargs={'item_id': self.item.id})
        response = self.client.get(url)
        
        # Should return 403 Forbidden
        self.assertEqual(response.status_code, 403)
        
        # Check error message
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('Agent role', data['message'])
    
    def test_rag_retrieval_requires_description(self):
        """Test that item must have a description for RAG retrieval"""
        # Create item without description
        item_no_desc = Item.objects.create(
            project=self.project,
            title='Item Without Description',
            description='',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        url = reverse('item-rag-retrieval-raw', kwargs={'item_id': item_no_desc.id})
        response = self.client.get(url)
        
        # Should return 400 Bad Request
        self.assertEqual(response.status_code, 400)
        
        # Check error message
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('no description', data['message'])
    
    @patch('core.views.build_context')
    def test_rag_retrieval_success(self, mock_build_context):
        """Test successful RAG retrieval with mocked results"""
        # Mock RAG context with sample results
        mock_rag_context = RAGContext(
            query='This is a test description for RAG retrieval.',
            alpha=0.5,
            summary='Found 2 results',
            items=[
                RAGContextObject(
                    object_type='item',
                    object_id='123',
                    title='Related Item 1',
                    content='This is related content 1',
                    source='agira',
                    relevance_score=0.85,
                    link='http://example.com/item/123',
                    updated_at='2024-01-01 12:00:00'
                ),
                RAGContextObject(
                    object_type='comment',
                    object_id='456',
                    title='Related Comment',
                    content='This is related comment content',
                    source='agira',
                    relevance_score=0.72,
                    link='http://example.com/comment/456',
                    updated_at='2024-01-02 14:30:00'
                )
            ],
            stats={'total_results': 2, 'deduplicated': 2}
        )
        
        mock_build_context.return_value = mock_rag_context
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        url = reverse('item-rag-retrieval-raw', kwargs={'item_id': self.item.id})
        response = self.client.get(url)
        
        # Should return 200 OK
        self.assertEqual(response.status_code, 200)
        
        # Check response data
        data = response.json()
        self.assertEqual(data['status'], 'success')
        self.assertIn('markdown', data)
        
        # Verify markdown content structure
        markdown = data['markdown']
        self.assertIn('## RAG Retrieval (raw)', markdown)
        self.assertIn('### Header', markdown)
        self.assertIn('### Hits', markdown)
        self.assertIn('query:', markdown)
        self.assertIn('search_type: `hybrid`', markdown)
        self.assertIn('alpha: `0.50`', markdown)
        self.assertIn('hits: `2`', markdown)
        
        # Verify hit details are included
        self.assertIn('1) Hit', markdown)
        self.assertIn('2) Hit', markdown)
        self.assertIn('score: `0.8500`', markdown)
        self.assertIn('score: `0.7200`', markdown)
        self.assertIn('Related Item 1', markdown)
        self.assertIn('Related Comment', markdown)
        
        # Verify build_context was called with correct parameters
        mock_build_context.assert_called_once_with(
            query='This is a test description for RAG retrieval.',
            project_id=str(self.project.id),
            limit=10
        )
    
    @patch('core.views.build_context')
    def test_rag_retrieval_no_results(self, mock_build_context):
        """Test RAG retrieval when no results are found"""
        # Mock RAG context with no results
        mock_rag_context = RAGContext(
            query='This is a test description for RAG retrieval.',
            alpha=0.5,
            summary='No results found',
            items=[],
            stats={'total_results': 0, 'deduplicated': 0}
        )
        
        mock_build_context.return_value = mock_rag_context
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        url = reverse('item-rag-retrieval-raw', kwargs={'item_id': self.item.id})
        response = self.client.get(url)
        
        # Should return 200 OK
        self.assertEqual(response.status_code, 200)
        
        # Check response data
        data = response.json()
        self.assertEqual(data['status'], 'success')
        
        # Verify markdown content shows no hits
        markdown = data['markdown']
        self.assertIn('hits: `0`', markdown)
        self.assertIn('*No hits found*', markdown)
    
    @patch('core.views.build_context')
    def test_rag_retrieval_error_handling(self, mock_build_context):
        """Test error handling when RAG retrieval fails"""
        # Mock an exception
        mock_build_context.side_effect = Exception('Weaviate connection error')
        
        # Login as agent
        self.client.login(username='agent_user', password='testpass123')
        
        url = reverse('item-rag-retrieval-raw', kwargs={'item_id': self.item.id})
        response = self.client.get(url)
        
        # Should return 500 Internal Server Error
        self.assertEqual(response.status_code, 500)
        
        # Check error message
        data = response.json()
        self.assertEqual(data['status'], 'error')
        self.assertIn('Weaviate connection error', data['message'])


class MarkdownFormattingTestCase(TestCase):
    """Test cases for the _format_rag_results_as_markdown function"""
    
    def test_format_with_results(self):
        """Test markdown formatting with results"""
        from core.views import _format_rag_results_as_markdown
        
        # Create sample RAG context
        rag_context = RAGContext(
            query='Test query',
            alpha=0.7,
            summary='Found 1 result',
            items=[
                RAGContextObject(
                    object_type='item',
                    object_id='42',
                    title='Sample Item',
                    content='Sample content text',
                    source='agira',
                    relevance_score=0.95,
                    link='http://example.com/item/42',
                    updated_at='2024-01-15 10:30:00'
                )
            ],
            stats={'total_results': 1}
        )
        
        # Format as markdown
        markdown = _format_rag_results_as_markdown(
            query='Test query',
            rag_context=rag_context,
            duration_ms=250
        )
        
        # Verify structure
        self.assertIn('## RAG Retrieval (raw)', markdown)
        self.assertIn('### Header', markdown)
        self.assertIn('query: `Test query`', markdown)
        self.assertIn('alpha: `0.70`', markdown)
        self.assertIn('duration_ms: `250`', markdown)
        self.assertIn('hits: `1`', markdown)
        self.assertIn('### Hits', markdown)
        self.assertIn('1) Hit', markdown)
        self.assertIn('score: `0.9500`', markdown)
        self.assertIn('type=item, id=42, source=agira', markdown)
        self.assertIn('title: `Sample Item`', markdown)
        self.assertIn('Sample content text', markdown)
    
    def test_format_no_results(self):
        """Test markdown formatting with no results"""
        from core.views import _format_rag_results_as_markdown
        
        # Create empty RAG context
        rag_context = RAGContext(
            query='Test query with no results',
            alpha=0.5,
            summary='No results',
            items=[],
            stats={'total_results': 0}
        )
        
        # Format as markdown
        markdown = _format_rag_results_as_markdown(
            query='Test query with no results',
            rag_context=rag_context,
            duration_ms=100
        )
        
        # Verify structure
        self.assertIn('hits: `0`', markdown)
        self.assertIn('*No hits found*', markdown)
    
    def test_format_sorts_by_score(self):
        """Test that results are sorted by score descending"""
        from core.views import _format_rag_results_as_markdown
        
        # Create RAG context with unsorted results
        rag_context = RAGContext(
            query='Test',
            alpha=0.5,
            summary='Found 3 results',
            items=[
                RAGContextObject(
                    object_type='item',
                    object_id='1',
                    title='Low score',
                    content='Content 1',
                    source='agira',
                    relevance_score=0.3,
                    link=None,
                    updated_at=None
                ),
                RAGContextObject(
                    object_type='item',
                    object_id='2',
                    title='High score',
                    content='Content 2',
                    source='agira',
                    relevance_score=0.9,
                    link=None,
                    updated_at=None
                ),
                RAGContextObject(
                    object_type='item',
                    object_id='3',
                    title='Medium score',
                    content='Content 3',
                    source='agira',
                    relevance_score=0.6,
                    link=None,
                    updated_at=None
                )
            ],
            stats={'total_results': 3}
        )
        
        # Format as markdown
        markdown = _format_rag_results_as_markdown(
            query='Test',
            rag_context=rag_context,
            duration_ms=100
        )
        
        # Verify ordering - high score should be first
        lines = markdown.split('\n')
        
        # Find the positions of each score
        high_score_pos = None
        medium_score_pos = None
        low_score_pos = None
        
        for i, line in enumerate(lines):
            if '0.9000' in line:
                high_score_pos = i
            elif '0.6000' in line:
                medium_score_pos = i
            elif '0.3000' in line:
                low_score_pos = i
        
        # Verify ordering
        self.assertIsNotNone(high_score_pos)
        self.assertIsNotNone(medium_score_pos)
        self.assertIsNotNone(low_score_pos)
        self.assertLess(high_score_pos, medium_score_pos)
        self.assertLess(medium_score_pos, low_score_pos)
