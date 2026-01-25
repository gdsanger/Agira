"""
Unit tests for RAG Pipeline Service.
"""

from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from core.services.rag.service import RAGPipelineService, build_context
from core.services.rag.models import RAGContext, RAGContextObject
from core.services.rag.config import (
    DEFAULT_ALPHA_KEYWORD,
    DEFAULT_ALPHA_SEMANTIC,
    DEFAULT_ALPHA_BALANCED,
)


class AlphaHeuristicTestCase(TestCase):
    """Test alpha heuristic for hybrid search weighting."""
    
    def test_keyword_query_with_issue_id(self):
        """Query with issue ID should use keyword-heavy alpha."""
        alpha = RAGPipelineService._determine_alpha("Fix bug #36")
        self.assertEqual(alpha, DEFAULT_ALPHA_KEYWORD)
    
    def test_keyword_query_with_version(self):
        """Query with version number should use keyword-heavy alpha."""
        alpha = RAGPipelineService._determine_alpha("Update to v1.2.3")
        self.assertEqual(alpha, DEFAULT_ALPHA_KEYWORD)
    
    def test_keyword_query_with_camelcase(self):
        """Query with camelCase should use keyword-heavy alpha."""
        alpha = RAGPipelineService._determine_alpha("Fix handleSubmit function")
        self.assertEqual(alpha, DEFAULT_ALPHA_KEYWORD)
    
    def test_keyword_query_with_pascalcase(self):
        """Query with PascalCase should use keyword-heavy alpha."""
        alpha = RAGPipelineService._determine_alpha("Update UserController")
        self.assertEqual(alpha, DEFAULT_ALPHA_KEYWORD)
    
    def test_keyword_query_with_snake_case(self):
        """Query with snake_case should use keyword-heavy alpha."""
        alpha = RAGPipelineService._determine_alpha("Fix user_service error")
        self.assertEqual(alpha, DEFAULT_ALPHA_KEYWORD)
    
    def test_keyword_query_with_exception(self):
        """Query with exception keyword should use keyword-heavy alpha."""
        alpha = RAGPipelineService._determine_alpha("NullPointerException in login")
        self.assertEqual(alpha, DEFAULT_ALPHA_KEYWORD)
    
    def test_keyword_query_with_http_error(self):
        """Query with HTTP error code should use keyword-heavy alpha."""
        alpha = RAGPipelineService._determine_alpha("HTTP 404 error")
        self.assertEqual(alpha, DEFAULT_ALPHA_KEYWORD)
    
    def test_semantic_query_long_natural_language(self):
        """Long natural language query should use semantic-heavy alpha."""
        query = "I need to implement a feature that allows users to export their data as CSV files"
        alpha = RAGPipelineService._determine_alpha(query)
        self.assertEqual(alpha, DEFAULT_ALPHA_SEMANTIC)
    
    def test_balanced_query_medium_text(self):
        """Medium-length query without patterns should use balanced alpha."""
        alpha = RAGPipelineService._determine_alpha("login bug with special characters")
        self.assertEqual(alpha, DEFAULT_ALPHA_BALANCED)
    
    def test_multiple_patterns_keyword_heavy(self):
        """Query with multiple keyword patterns should use keyword alpha."""
        alpha = RAGPipelineService._determine_alpha("Fix #42 in UserService v2.1")
        self.assertEqual(alpha, DEFAULT_ALPHA_KEYWORD)


class ContentTruncationTestCase(TestCase):
    """Test content truncation functionality."""
    
    def test_short_content_not_truncated(self):
        """Short content should not be truncated."""
        content = "This is a short text."
        result = RAGPipelineService._truncate_content(content, max_length=100)
        self.assertEqual(result, content)
    
    def test_long_content_truncated(self):
        """Long content should be truncated."""
        content = "word " * 200  # 1000 characters
        result = RAGPipelineService._truncate_content(content, max_length=100)
        self.assertTrue(len(result) <= 104)  # 100 + "..."
        self.assertTrue(result.endswith("..."))
    
    def test_truncation_respects_word_boundaries(self):
        """Truncation should respect word boundaries."""
        content = "This is a long sentence that should be truncated at a word boundary"
        result = RAGPipelineService._truncate_content(content, max_length=30)
        self.assertTrue(result.endswith("..."))
        # Should not break mid-word
        self.assertNotIn("tence...", result)  # "sentence" should not be broken
    
    def test_empty_content(self):
        """Empty content should return empty string."""
        result = RAGPipelineService._truncate_content("", max_length=100)
        self.assertEqual(result, "")
    
    def test_none_content(self):
        """None content should return None."""
        result = RAGPipelineService._truncate_content(None, max_length=100)
        self.assertIsNone(result)


class SummaryGenerationTestCase(TestCase):
    """Test summary generation functionality."""
    
    def test_empty_results_summary(self):
        """Empty results should generate appropriate summary."""
        summary = RAGPipelineService._generate_summary([])
        self.assertEqual(summary, "No related objects found.")
    
    def test_single_item_summary(self):
        """Single item should have correct grammar."""
        items = [
            RAGContextObject(
                object_type="item",
                object_id="1",
                title="Test",
                content="Content",
                source="agira",
                relevance_score=0.9,
                link="/items/1/",
                updated_at="2024-01-01"
            )
        ]
        summary = RAGPipelineService._generate_summary(items)
        self.assertIn("1 related object", summary)
        self.assertIn("1 item", summary)
    
    def test_multiple_types_summary(self):
        """Multiple types should be counted correctly."""
        items = [
            RAGContextObject(
                object_type="item",
                object_id="1",
                title="Test 1",
                content="Content",
                source="agira",
                relevance_score=0.9,
                link="/items/1/",
                updated_at="2024-01-01"
            ),
            RAGContextObject(
                object_type="item",
                object_id="2",
                title="Test 2",
                content="Content",
                source="agira",
                relevance_score=0.8,
                link="/items/2/",
                updated_at="2024-01-01"
            ),
            RAGContextObject(
                object_type="comment",
                object_id="3",
                title=None,
                content="Comment",
                source="agira",
                relevance_score=0.7,
                link="/comments/3/",
                updated_at="2024-01-01"
            ),
        ]
        summary = RAGPipelineService._generate_summary(items)
        self.assertIn("3 related objects", summary)
        self.assertIn("2 items", summary)
        self.assertIn("1 comment", summary)
    
    def test_github_issue_pr_mention(self):
        """Summary should mention GitHub issues/PRs if present."""
        items = [
            RAGContextObject(
                object_type="github_issue",
                object_id="1",
                title="Issue",
                content="Content",
                source="github",
                relevance_score=0.9,
                link="https://github.com/repo/issues/1",
                updated_at="2024-01-01"
            ),
        ]
        summary = RAGPipelineService._generate_summary(items)
        self.assertIn("GitHub issues/PRs", summary)


class DeduplicationRankingTestCase(TestCase):
    """Test deduplication and ranking functionality."""
    
    def test_deduplication_by_object_id(self):
        """Duplicate object_ids should be removed."""
        results = [
            {'object_id': '1', 'object_type': 'item', 'score': 0.9},
            {'object_id': '1', 'object_type': 'item', 'score': 0.8},  # Duplicate
            {'object_id': '2', 'object_type': 'comment', 'score': 0.7},
        ]
        unique = RAGPipelineService._deduplicate_and_rank(results, limit=10)
        self.assertEqual(len(unique), 2)
        # Should keep the first (highest scored) occurrence
        self.assertEqual(unique[0]['object_id'], '1')
        self.assertEqual(unique[0]['score'], 0.9)
    
    def test_ranking_by_score(self):
        """Results should be ranked by score (descending)."""
        results = [
            {'object_id': '1', 'object_type': 'item', 'score': 0.5},
            {'object_id': '2', 'object_type': 'item', 'score': 0.9},
            {'object_id': '3', 'object_type': 'item', 'score': 0.7},
        ]
        ranked = RAGPipelineService._deduplicate_and_rank(results, limit=10)
        self.assertEqual(ranked[0]['object_id'], '2')  # Highest score
        self.assertEqual(ranked[1]['object_id'], '3')
        self.assertEqual(ranked[2]['object_id'], '1')  # Lowest score
    
    def test_ranking_by_type_priority(self):
        """Results with same score should be ranked by type priority."""
        results = [
            {'object_id': '1', 'object_type': 'attachment', 'score': 0.8},
            {'object_id': '2', 'object_type': 'item', 'score': 0.8},
            {'object_id': '3', 'object_type': 'comment', 'score': 0.8},
        ]
        ranked = RAGPipelineService._deduplicate_and_rank(results, limit=10)
        # Item should be first (highest priority)
        self.assertEqual(ranked[0]['object_type'], 'item')
        self.assertEqual(ranked[1]['object_type'], 'comment')
        self.assertEqual(ranked[2]['object_type'], 'attachment')
    
    def test_limit_enforced(self):
        """Results should be limited to specified count."""
        results = [
            {'object_id': str(i), 'object_type': 'item', 'score': 1.0 - i*0.1}
            for i in range(20)
        ]
        limited = RAGPipelineService._deduplicate_and_rank(results, limit=5)
        self.assertEqual(len(limited), 5)


class BuildContextTestCase(TestCase):
    """Test build_context main function."""
    
    @patch('core.services.rag.service.is_available')
    def test_weaviate_not_available(self, mock_is_available):
        """Should return empty context when Weaviate is not available."""
        mock_is_available.return_value = False
        
        context = build_context(query="test query")
        
        self.assertIsInstance(context, RAGContext)
        self.assertEqual(context.query, "test query")
        self.assertEqual(len(context.items), 0)
        self.assertIn("not available", context.summary)
        self.assertIsNotNone(context.stats.get('error'))
    
    @patch('core.services.rag.service.is_available')
    @patch('core.services.rag.service.get_client')
    def test_successful_search(self, mock_get_client, mock_is_available):
        """Should return context with results on successful search."""
        mock_is_available.return_value = True
        
        # Mock Weaviate client
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        # Mock collection
        mock_collection = MagicMock()
        mock_client.collections.get.return_value = mock_collection
        
        # Mock search response
        mock_obj = MagicMock()
        mock_obj.properties = {
            'object_id': '1',
            'type': 'item',
            'title': 'Test Item',
            'text': 'Test content',
            'url': '/items/1/',
            'source_system': 'agira',
            'updated_at': datetime(2024, 1, 1),
        }
        mock_obj.metadata.score = 0.85
        
        mock_response = MagicMock()
        mock_response.objects = [mock_obj]
        mock_collection.query.hybrid.return_value = mock_response
        
        # Execute
        context = build_context(
            query="test query",
            project_id="1",
            limit=10
        )
        
        # Verify
        self.assertIsInstance(context, RAGContext)
        self.assertEqual(context.query, "test query")
        self.assertEqual(len(context.items), 1)
        self.assertEqual(context.items[0].object_type, "item")
        self.assertEqual(context.items[0].object_id, "1")
        self.assertEqual(context.items[0].title, "Test Item")
        self.assertIn("Test content", context.items[0].content)
        
        # Verify client was closed
        mock_client.close.assert_called_once()
    
    @patch('core.services.rag.service.is_available')
    @patch('core.services.rag.service.get_client')
    def test_project_filter(self, mock_get_client, mock_is_available):
        """Should apply project_id filter."""
        mock_is_available.return_value = True
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_collection = MagicMock()
        mock_client.collections.get.return_value = mock_collection
        
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.hybrid.return_value = mock_response
        
        # Execute with project filter
        build_context(
            query="test",
            project_id="123"
        )
        
        # Verify hybrid was called with where filter
        call_args = mock_collection.query.hybrid.call_args
        self.assertIsNotNone(call_args.kwargs.get('where'))
    
    @patch('core.services.rag.service.is_available')
    @patch('core.services.rag.service.get_client')
    def test_object_types_filter(self, mock_get_client, mock_is_available):
        """Should apply object_types filter."""
        mock_is_available.return_value = True
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_collection = MagicMock()
        mock_client.collections.get.return_value = mock_collection
        
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.hybrid.return_value = mock_response
        
        # Execute with type filter
        build_context(
            query="test",
            object_types=["item", "comment"]
        )
        
        # Verify hybrid was called with where filter
        call_args = mock_collection.query.hybrid.call_args
        self.assertIsNotNone(call_args.kwargs.get('where'))
    
    @patch('core.services.rag.service.is_available')
    @patch('core.services.rag.service.get_client')
    def test_alpha_parameter(self, mock_get_client, mock_is_available):
        """Should use provided alpha value."""
        mock_is_available.return_value = True
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_collection = MagicMock()
        mock_client.collections.get.return_value = mock_collection
        
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.hybrid.return_value = mock_response
        
        # Execute with custom alpha
        context = build_context(
            query="test",
            alpha=0.3
        )
        
        # Verify alpha was used
        self.assertEqual(context.alpha, 0.3)
        call_args = mock_collection.query.hybrid.call_args
        self.assertEqual(call_args.kwargs.get('alpha'), 0.3)
    
    @patch('core.services.rag.service.is_available')
    @patch('core.services.rag.service.get_client')
    def test_alpha_heuristic_applied(self, mock_get_client, mock_is_available):
        """Should apply alpha heuristic when alpha not provided."""
        mock_is_available.return_value = True
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        mock_collection = MagicMock()
        mock_client.collections.get.return_value = mock_collection
        
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.hybrid.return_value = mock_response
        
        # Execute with query that should trigger keyword heuristic
        context = build_context(query="Fix bug #36")
        
        # Should use keyword alpha
        self.assertEqual(context.alpha, DEFAULT_ALPHA_KEYWORD)
    
    @patch('core.services.rag.service.is_available')
    @patch('core.services.rag.service.get_client')
    def test_error_handling(self, mock_get_client, mock_is_available):
        """Should handle errors gracefully."""
        mock_is_available.return_value = True
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        # Simulate error
        mock_client.collections.get.side_effect = Exception("Connection failed")
        
        # Should not raise exception
        context = build_context(query="test")
        
        # Should return empty context with error
        self.assertEqual(len(context.items), 0)
        self.assertIsNotNone(context.stats.get('error'))
        
        # Client should still be closed
        mock_client.close.assert_called_once()
    
    def test_include_debug(self):
        """Should include debug info when requested."""
        with patch('core.services.rag.service.is_available') as mock_available:
            mock_available.return_value = False
            
            context = build_context(
                query="test query",
                include_debug=True
            )
            
            self.assertIsNotNone(context.debug)
            self.assertIn('alpha_heuristic', context.debug)
            self.assertIn('query_length', context.debug)


class ContextTextGenerationTestCase(TestCase):
    """Test context text generation for agents."""
    
    def test_empty_context_text(self):
        """Empty context should generate minimal text."""
        context = RAGContext(
            query="test",
            alpha=0.5,
            summary="No results",
            items=[]
        )
        text = context.to_context_text()
        
        self.assertIn("[CONTEXT]", text)
        self.assertIn("[/CONTEXT]", text)
        self.assertIn("[SOURCES]", text)
        self.assertIn("[/SOURCES]", text)
    
    def test_context_text_format(self):
        """Context text should be properly formatted."""
        items = [
            RAGContextObject(
                object_type="item",
                object_id="1",
                title="Test Item",
                content="This is test content",
                source="agira",
                relevance_score=0.85,
                link="/items/1/",
                updated_at="2024-01-01"
            ),
        ]
        context = RAGContext(
            query="test",
            alpha=0.5,
            summary="Found 1 item",
            items=items
        )
        text = context.to_context_text()
        
        # Check structure
        self.assertIn("[CONTEXT]", text)
        self.assertIn("1) (type=item score=0.85) Title: Test Item", text)
        self.assertIn("Link: /items/1/", text)
        self.assertIn("Snippet: This is test content", text)
        self.assertIn("[SOURCES]", text)
        self.assertIn("- item:1 -> /items/1/", text)
    
    def test_context_text_without_title(self):
        """Context text should handle missing titles."""
        items = [
            RAGContextObject(
                object_type="comment",
                object_id="1",
                title=None,
                content="Comment content",
                source="agira",
                relevance_score=0.75,
                link="/comments/1/",
                updated_at="2024-01-01"
            ),
        ]
        context = RAGContext(
            query="test",
            alpha=0.5,
            summary="Found 1 comment",
            items=items
        )
        text = context.to_context_text()
        
        # Should not have "Title:" when no title
        self.assertNotIn("Title:", text)
        self.assertIn("(type=comment score=0.75)", text)
