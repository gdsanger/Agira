"""
Unit tests for Extended RAG Pipeline Service.
"""

import json
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from core.services.rag.extended_service import (
    ExtendedRAGPipelineService,
    build_extended_context,
    OptimizedQuery,
    ExtendedRAGContext,
)
from core.services.rag.models import RAGContextObject


class QuestionOptimizationTestCase(TestCase):
    """Test question optimization via AI agent."""
    
    @patch('core.services.rag.extended_service.AgentService')
    def test_optimization_returns_valid_json(self, mock_agent_service_class):
        """Question optimization should return valid JSON with all required fields."""
        # Mock agent response
        mock_service = mock_agent_service_class.return_value
        mock_service.execute_agent.return_value = json.dumps({
            "language": "de",
            "core": "Login Bug Passwort",
            "synonyms": ["Anmeldung Fehler", "Auth Problem"],
            "phrases": ["Login-Bug", "Passwort"],
            "entities": {"component": ["Login"]},
            "tags": ["login", "bug", "password"],
            "ban": ["wie", "kann"],
            "followup_questions": ["Welche Fehler?"]
        })
        
        optimized = ExtendedRAGPipelineService._optimize_question(
            "Wie kann ich den Login-Bug beheben?"
        )
        
        self.assertIsNotNone(optimized)
        self.assertEqual(optimized.language, "de")
        self.assertEqual(optimized.core, "Login Bug Passwort")
        self.assertEqual(len(optimized.synonyms), 2)
        self.assertEqual(len(optimized.tags), 3)
        self.assertIn("login", optimized.tags)
    
    @patch('core.services.rag.extended_service.AgentService')
    def test_optimization_handles_code_fences(self, mock_agent_service_class):
        """Question optimization should handle markdown code fences."""
        mock_service = mock_agent_service_class.return_value
        mock_service.execute_agent.return_value = """```json
{
    "language": "en",
    "core": "test query",
    "synonyms": [],
    "phrases": [],
    "entities": {},
    "tags": ["test"],
    "ban": [],
    "followup_questions": []
}
```"""
        
        optimized = ExtendedRAGPipelineService._optimize_question("test query")
        
        self.assertIsNotNone(optimized)
        self.assertEqual(optimized.core, "test query")
    
    @patch('core.services.rag.extended_service.AgentService')
    def test_optimization_handles_invalid_json(self, mock_agent_service_class):
        """Question optimization should handle invalid JSON gracefully."""
        mock_service = mock_agent_service_class.return_value
        mock_service.execute_agent.return_value = "This is not valid JSON"
        
        optimized = ExtendedRAGPipelineService._optimize_question("test query")
        
        self.assertIsNone(optimized)
    
    @patch('core.services.rag.extended_service.AgentService')
    def test_optimization_handles_missing_fields(self, mock_agent_service_class):
        """Question optimization should handle missing required fields."""
        mock_service = mock_agent_service_class.return_value
        # Missing 'tags' and 'ban' fields
        mock_service.execute_agent.return_value = json.dumps({
            "language": "de",
            "core": "test",
            "synonyms": [],
            "phrases": [],
            "entities": {},
            "followup_questions": []
        })
        
        optimized = ExtendedRAGPipelineService._optimize_question("test")
        
        self.assertIsNone(optimized)


class QueryBuildingTestCase(TestCase):
    """Test query building from optimized question."""
    
    def test_semantic_query_includes_core_synonyms_phrases_tags(self):
        """Semantic query should include core + top 3 synonyms + top 2 phrases + top 2 tags."""
        optimized = OptimizedQuery(
            language="de",
            core="Login Bug",
            synonyms=["Anmeldung Fehler", "Auth Problem", "Sign-in Error", "Extra"],
            phrases=["Passwort Problem", "User Error", "Extra phrase"],
            entities={},
            tags=["login", "bug", "password", "auth", "extra"],
            ban=[],
            followup_questions=[]
        )
        
        query = ExtendedRAGPipelineService._build_semantic_query(optimized)
        
        # Should include core
        self.assertIn("Login Bug", query)
        # Should include top 3 synonyms
        self.assertIn("Anmeldung Fehler", query)
        self.assertIn("Auth Problem", query)
        self.assertIn("Sign-in Error", query)
        # Should NOT include 4th synonym
        self.assertNotIn("Extra", query)
        # Should include top 2 phrases
        self.assertIn("Passwort Problem", query)
        self.assertIn("User Error", query)
        # Should NOT include 3rd phrase
        self.assertNotIn("Extra phrase", query)
        # Should include top 2 tags
        self.assertIn("login", query)
        self.assertIn("bug", query)
    
    def test_keyword_query_includes_tags_and_core(self):
        """Keyword query should include tags + core."""
        optimized = OptimizedQuery(
            language="de",
            core="Login Bug",
            synonyms=[],
            phrases=[],
            entities={},
            tags=["login", "bug", "password"],
            ban=[],
            followup_questions=[]
        )
        
        query = ExtendedRAGPipelineService._build_keyword_query(optimized)
        
        self.assertIn("login", query)
        self.assertIn("bug", query)
        self.assertIn("password", query)
        self.assertIn("Login Bug", query)


class SearchTestCase(TestCase):
    """Test Weaviate search execution."""
    
    @patch('core.services.rag.extended_service.is_available')
    def test_search_returns_empty_when_weaviate_unavailable(self, mock_is_available):
        """Search should return empty list when Weaviate is unavailable."""
        mock_is_available.return_value = False
        
        results = ExtendedRAGPipelineService._perform_search(
            query_text="test",
            alpha=0.6,
            limit=10
        )
        
        self.assertEqual(results, [])
    
    @patch('core.services.rag.extended_service.get_client')
    @patch('core.services.rag.extended_service.is_available')
    def test_search_returns_results(self, mock_is_available, mock_get_client):
        """Search should return formatted results from Weaviate."""
        mock_is_available.return_value = True
        
        # Mock Weaviate response
        mock_obj = Mock()
        mock_obj.properties = {
            'object_id': '123',
            'type': 'item',
            'title': 'Test Item',
            'text': 'Test content',
            'url': '/items/123/',
            'source_system': 'agira',
            'updated_at': '2024-01-01',
        }
        mock_obj.metadata.score = 0.85
        
        mock_response = Mock()
        mock_response.objects = [mock_obj]
        
        mock_collection = Mock()
        mock_collection.query.hybrid.return_value = mock_response
        
        mock_client = Mock()
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        results = ExtendedRAGPipelineService._perform_search(
            query_text="test",
            alpha=0.6,
            limit=10
        )
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['object_id'], '123')
        self.assertEqual(results[0]['object_type'], 'item')
        self.assertEqual(results[0]['title'], 'Test Item')
        self.assertEqual(results[0]['score'], 0.85)
    
    @patch('core.services.rag.extended_service.get_client')
    @patch('core.services.rag.extended_service.is_available')
    def test_search_returns_non_null_scores(self, mock_is_available, mock_get_client):
        """Search should return non-null scores from Weaviate metadata (Issue #401)."""
        mock_is_available.return_value = True
        
        # Mock Weaviate response with multiple results with different scores
        mock_obj1 = Mock()
        mock_obj1.properties = {
            'object_id': '1',
            'type': 'item',
            'title': 'First Item',
            'text': 'First content',
            'url': '/items/1/',
            'source_system': 'agira',
            'updated_at': '2024-01-01',
        }
        mock_obj1.metadata.score = 0.95
        
        mock_obj2 = Mock()
        mock_obj2.properties = {
            'object_id': '2',
            'type': 'item',
            'title': 'Second Item',
            'text': 'Second content',
            'url': '/items/2/',
            'source_system': 'agira',
            'updated_at': '2024-01-02',
        }
        mock_obj2.metadata.score = 0.72
        
        mock_obj3 = Mock()
        mock_obj3.properties = {
            'object_id': '3',
            'type': 'item',
            'title': 'Third Item',
            'text': 'Third content',
            'url': '/items/3/',
            'source_system': 'agira',
            'updated_at': '2024-01-03',
        }
        mock_obj3.metadata.score = 0.58
        
        mock_response = Mock()
        mock_response.objects = [mock_obj1, mock_obj2, mock_obj3]
        
        mock_collection = Mock()
        mock_collection.query.hybrid.return_value = mock_response
        
        mock_client = Mock()
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        results = ExtendedRAGPipelineService._perform_search(
            query_text="test query",
            alpha=0.6,
            limit=10
        )
        
        # Assert: all results have non-null scores
        self.assertEqual(len(results), 3)
        for result in results:
            self.assertIsNotNone(result['score'], 
                f"Score should not be None for result {result['object_id']}")
        
        # Assert: scores are different (not all constant 0.075)
        scores = [r['score'] for r in results]
        unique_scores = set(scores)
        self.assertGreater(len(unique_scores), 1, 
            "Scores should vary between results, not be constant")
        
        # Assert: specific score values match mock data
        self.assertEqual(results[0]['score'], 0.95)
        self.assertEqual(results[1]['score'], 0.72)
        self.assertEqual(results[2]['score'], 0.58)
        
        # Verify that return_metadata was passed to the hybrid query
        mock_collection.query.hybrid.assert_called_once()
        call_kwargs = mock_collection.query.hybrid.call_args[1]
        self.assertIn('return_metadata', call_kwargs, 
            "return_metadata should be passed to hybrid query")



class FusionAndRerankingTestCase(TestCase):
    """Test result fusion and reranking."""
    
    def test_fusion_removes_duplicates(self):
        """Fusion should remove duplicate results by object_id."""
        sem_results = [
            {'object_id': '1', 'object_type': 'item', 'score': 0.8, 'content': 'A', 'title': 'Item 1'},
            {'object_id': '2', 'object_type': 'item', 'score': 0.6, 'content': 'B', 'title': 'Item 2'},
        ]
        kw_results = [
            {'object_id': '1', 'object_type': 'item', 'score': 0.5, 'content': 'A', 'title': 'Item 1'},  # Duplicate
            {'object_id': '3', 'object_type': 'item', 'score': 0.7, 'content': 'C', 'title': 'Item 3'},
        ]
        
        fused = ExtendedRAGPipelineService._fuse_and_rerank(
            sem_results=sem_results,
            kw_results=kw_results,
            limit=10
        )
        
        # Should have 3 unique items
        self.assertEqual(len(fused), 3)
        
        # Check that object_ids are unique
        ids = [r['object_id'] for r in fused]
        self.assertEqual(len(ids), len(set(ids)))
    
    def test_fusion_calculates_final_scores(self):
        """Fusion should calculate weighted final scores."""
        sem_results = [
            {'object_id': '1', 'object_type': 'item', 'score': 1.0, 'content': 'A', 'title': 'Item 1'},
        ]
        kw_results = [
            {'object_id': '1', 'object_type': 'item', 'score': 0.5, 'content': 'A', 'title': 'Item 1'},
        ]
        
        fused = ExtendedRAGPipelineService._fuse_and_rerank(
            sem_results=sem_results,
            kw_results=kw_results,
            limit=10
        )
        
        # Final score should be: 0.6*1.0 + 0.2*0.5 + 0.15*1.0 + 0.05*0.0
        # = 0.6 + 0.1 + 0.15 + 0.0 = 0.85
        expected_score = 0.6 * 1.0 + 0.2 * 0.5 + 0.15 * 1.0 + 0.05 * 0.0
        self.assertAlmostEqual(fused[0]['final_score'], expected_score, places=2)
    
    def test_fusion_limits_results(self):
        """Fusion should limit results to specified number."""
        sem_results = [
            {'object_id': str(i), 'object_type': 'item', 'score': 0.8 - i*0.1, 'content': f'Item {i}', 'title': f'Title {i}'}
            for i in range(10)
        ]
        kw_results = []
        
        fused = ExtendedRAGPipelineService._fuse_and_rerank(
            sem_results=sem_results,
            kw_results=kw_results,
            limit=3
        )
        
        self.assertEqual(len(fused), 3)
    
    def test_fusion_avoids_constant_075_score(self):
        """Fusion should produce varying scores when input scores are non-zero (Issue #401)."""
        # Test that when both semantic and keyword searches return proper scores,
        # the final fusion scores vary and don't degenerate to constant 0.075
        sem_results = [
            {'object_id': '1', 'object_type': 'item', 'score': 0.9, 'content': 'High match', 'title': 'Item 1'},
            {'object_id': '2', 'object_type': 'item', 'score': 0.6, 'content': 'Medium match', 'title': 'Item 2'},
            {'object_id': '3', 'object_type': 'item', 'score': 0.3, 'content': 'Low match', 'title': 'Item 3'},
        ]
        kw_results = [
            {'object_id': '1', 'object_type': 'item', 'score': 0.8, 'content': 'High match', 'title': 'Item 1'},
            {'object_id': '2', 'object_type': 'item', 'score': 0.4, 'content': 'Medium match', 'title': 'Item 2'},
        ]
        
        fused = ExtendedRAGPipelineService._fuse_and_rerank(
            sem_results=sem_results,
            kw_results=kw_results,
            limit=10
        )
        
        # All results should have final_score > 0.075 (the problematic default)
        for result in fused:
            self.assertGreater(result['final_score'], 0.075, 
                f"Final score {result['final_score']} should be > 0.075 for {result['object_id']}")
        
        # Scores should be different, not all constant
        final_scores = [r['final_score'] for r in fused]
        unique_scores = set(final_scores)
        self.assertGreater(len(unique_scores), 1, 
            "Final scores should vary, not be constant 0.075")
        
        # Item 1 should have highest score (appears in both with high scores)
        # Item 1: 0.6*0.9 + 0.2*0.8 + 0.15*1.0 = 0.54 + 0.16 + 0.15 = 0.85
        self.assertAlmostEqual(fused[0]['final_score'], 0.85, places=2)
        self.assertEqual(fused[0]['object_id'], '1')
        
        # Item 2 should have middle score
        # Item 2: 0.6*0.6 + 0.2*0.4 + 0.15*1.0 = 0.36 + 0.08 + 0.15 = 0.59
        item2 = next(r for r in fused if r['object_id'] == '2')
        self.assertAlmostEqual(item2['final_score'], 0.59, places=2)
        
        # Item 3 should have lowest score (only semantic, no keyword)
        # Item 3: 0.6*0.3 + 0.2*0 + 0.15*0.5 = 0.18 + 0 + 0.075 = 0.255
        item3 = next(r for r in fused if r['object_id'] == '3')
        self.assertAlmostEqual(item3['final_score'], 0.255, places=2)


class LayerSeparationTestCase(TestCase):
    """Test A/B/C layer separation."""
    
    def test_layers_contain_correct_types(self):
        """Layers should contain appropriate object types."""
        results = [
            {'object_id': '1', 'object_type': 'comment', 'content': 'Comment 1', 'title': 'C1', 'score': 0.9},
            {'object_id': '2', 'object_type': 'item', 'content': 'Item 1', 'title': 'I1', 'score': 0.8},
            {'object_id': '5', 'object_type': 'attachment', 'content': 'Attachment 1', 'title': 'A1', 'score': 0.75},
            {'object_id': '3', 'object_type': 'project', 'content': 'Project 1', 'title': 'P1', 'score': 0.7},
            {'object_id': '4', 'object_type': 'comment', 'content': 'Comment 2', 'title': 'C2', 'score': 0.6},
        ]
        
        layer_a, layer_b, layer_c = ExtendedRAGPipelineService._separate_into_layers(results)
        
        # Layer A should have comments (up to 3)
        self.assertLessEqual(len(layer_a), 3)
        for item in layer_a:
            self.assertEqual(item.object_type, 'comment')
        
        # Layer B should have item-level context (items + attachments) (up to 3)
        self.assertLessEqual(len(layer_b), 3)
        for item in layer_b:
            self.assertIn(item.object_type, {'item', 'attachment'})

        self.assertTrue(any(item.object_type == 'attachment' for item in layer_b))
        
        # Layer C should have global context (up to 2)
        self.assertLessEqual(len(layer_c), 2)
    
    def test_layers_respect_limits(self):
        """Layers should respect their size limits."""
        results = [
            {'object_id': str(i), 'object_type': 'comment', 'content': f'Comment {i}', 'title': f'C{i}', 'score': 1.0 - i*0.1}
            for i in range(10)
        ]
        
        layer_a, layer_b, layer_c = ExtendedRAGPipelineService._separate_into_layers(results)
        
        # Layer A: up to 3
        self.assertLessEqual(len(layer_a), 3)
        # Layer B: up to 3
        self.assertLessEqual(len(layer_b), 3)
        # Layer C: up to 2
        self.assertLessEqual(len(layer_c), 2)


class ContextTextFormattingTestCase(TestCase):
    """Test context text formatting with layer markers."""
    
    def test_context_text_contains_layer_markers(self):
        """Context text should contain #A, #B, #C markers."""
        layer_a = [RAGContextObject(
            object_type='comment',
            object_id='1',
            title='Comment',
            content='Test comment',
            source='agira',
            relevance_score=0.9,
            link='/comment/1/',
            updated_at=None
        )]
        layer_b = [RAGContextObject(
            object_type='item',
            object_id='2',
            title='Item',
            content='Test item',
            source='agira',
            relevance_score=0.8,
            link='/item/2/',
            updated_at=None
        )]
        layer_c = [RAGContextObject(
            object_type='project',
            object_id='3',
            title='Project',
            content='Test project',
            source='agira',
            relevance_score=0.7,
            link='/project/3/',
            updated_at=None
        )]
        
        context = ExtendedRAGContext(
            query="test",
            optimized_query=None,
            layer_a=layer_a,
            layer_b=layer_b,
            layer_c=layer_c,
            all_items=layer_a + layer_b + layer_c,
            summary="Test summary"
        )
        
        text = context.to_context_text()
        
        self.assertIn('[#A1]', text)
        self.assertIn('[#B1]', text)
        self.assertIn('[#C1]', text)
        self.assertIn('Test comment', text)
        self.assertIn('Test item', text)
        self.assertIn('Test project', text)
    
    def test_context_text_includes_scores_and_links(self):
        """Context text should include relevance scores and links."""
        layer_a = [RAGContextObject(
            object_type='comment',
            object_id='1',
            title='Comment',
            content='Test',
            source='agira',
            relevance_score=0.95,
            link='/comment/1/',
            updated_at=None
        )]
        
        context = ExtendedRAGContext(
            query="test",
            optimized_query=None,
            layer_a=layer_a,
            layer_b=[],
            layer_c=[],
            all_items=layer_a,
            summary="Test"
        )
        
        text = context.to_context_text()
        
        self.assertIn('score=0.95', text)
        self.assertIn('Link: /comment/1/', text)


class BuildExtendedContextTestCase(TestCase):
    """Test the main build_extended_context function."""
    
    @patch('core.services.rag.extended_service.ExtendedRAGPipelineService._perform_search')
    @patch('core.services.rag.extended_service.ExtendedRAGPipelineService._optimize_question')
    def test_build_extended_context_returns_valid_context(self, mock_optimize, mock_search):
        """build_extended_context should return valid ExtendedRAGContext."""
        # Mock optimization
        mock_optimize.return_value = OptimizedQuery(
            language="de",
            core="test query",
            synonyms=["synonym"],
            phrases=["phrase"],
            entities={},
            tags=["tag1", "tag2"],
            ban=[],
            followup_questions=[]
        )
        
        # Mock search results
        mock_search.return_value = [
            {'object_id': '1', 'object_type': 'item', 'score': 0.8, 'content': 'Test', 'title': 'Item 1'},
        ]
        
        context = build_extended_context(
            query="test query",
            project_id="1"
        )
        
        self.assertIsInstance(context, ExtendedRAGContext)
        self.assertEqual(context.query, "test query")
        self.assertIsNotNone(context.optimized_query)
        self.assertGreater(len(context.all_items), 0)
    
    @patch('core.services.rag.extended_service.ExtendedRAGPipelineService._perform_search')
    @patch('core.services.rag.extended_service.ExtendedRAGPipelineService._optimize_question')
    def test_build_extended_context_fallback_on_optimization_failure(self, mock_optimize, mock_search):
        """build_extended_context should fallback to raw query if optimization fails."""
        # Mock optimization failure
        mock_optimize.return_value = None
        
        # Mock search results
        mock_search.return_value = []
        
        context = build_extended_context(
            query="test query",
            skip_optimization=False
        )
        
        self.assertIsInstance(context, ExtendedRAGContext)
        self.assertEqual(context.query, "test query")
        # Should have created a fallback OptimizedQuery
        self.assertFalse(context.stats.get('optimization_success', False))
    
    @patch('core.services.rag.extended_service.ExtendedRAGPipelineService._perform_search')
    def test_build_extended_context_skip_optimization(self, mock_search):
        """build_extended_context should skip optimization when requested."""
        mock_search.return_value = []
        
        context = build_extended_context(
            query="test query",
            skip_optimization=True
        )
        
        self.assertIsInstance(context, ExtendedRAGContext)
        self.assertIsNone(context.optimized_query)
        self.assertEqual(context.stats.get('optimization_success', False), False)
    
    @patch('core.services.rag.extended_service.ExtendedRAGPipelineService._perform_search')
    @patch('core.services.rag.extended_service.ExtendedRAGPipelineService._optimize_question')
    def test_build_extended_context_includes_debug_info(self, mock_optimize, mock_search):
        """build_extended_context should include debug info when requested."""
        mock_optimize.return_value = OptimizedQuery(
            language="de",
            core="test",
            synonyms=[],
            phrases=[],
            entities={},
            tags=[],
            ban=[],
            followup_questions=[]
        )
        mock_search.return_value = []
        
        context = build_extended_context(
            query="test",
            include_debug=True
        )
        
        self.assertIsNotNone(context.debug)
        self.assertIn('queries', context.debug)
        self.assertIn('optimized_query', context.debug)
    
    @patch('core.services.rag.extended_service.ExtendedRAGPipelineService._perform_search')
    @patch('core.services.rag.extended_service.ExtendedRAGPipelineService._optimize_question')
    def test_build_extended_context_ignores_unsupported_params(self, mock_optimize, mock_search):
        """build_extended_context should ignore unsupported parameters like max_results and enable_optimization."""
        mock_optimize.return_value = OptimizedQuery(
            language="en",
            core="test",
            synonyms=[],
            phrases=[],
            entities={},
            tags=[],
            ban=[],
            followup_questions=[]
        )
        mock_search.return_value = []
        
        # This should not raise TypeError even with unsupported parameters
        context = build_extended_context(
            query="test",
            max_results=10,  # Unsupported parameter
            enable_optimization=True,  # Unsupported parameter
        )
        
        self.assertIsInstance(context, ExtendedRAGContext)
        self.assertEqual(context.query, "test")


class JSONSerializationTestCase(TestCase):
    """Test JSON serialization for RAG data structures."""
    
    def test_rag_context_object_to_dict(self):
        """RAGContextObject.to_dict() should produce JSON-serializable dict."""
        obj = RAGContextObject(
            object_type='item',
            object_id='123',
            title='Test Item',
            content='Test content',
            source='agira',
            relevance_score=0.85,
            link='http://example.com/item/123',
            updated_at='2024-01-01 12:00:00'
        )
        
        result = obj.to_dict()
        
        # Should be a dict
        self.assertIsInstance(result, dict)
        
        # Should have all fields
        self.assertEqual(result['object_type'], 'item')
        self.assertEqual(result['object_id'], '123')
        self.assertEqual(result['title'], 'Test Item')
        self.assertEqual(result['content'], 'Test content')
        self.assertEqual(result['source'], 'agira')
        self.assertEqual(result['relevance_score'], 0.85)
        self.assertEqual(result['link'], 'http://example.com/item/123')
        self.assertEqual(result['updated_at'], '2024-01-01 12:00:00')
        
        # Should be JSON serializable
        json_str = json.dumps(result)
        self.assertIsInstance(json_str, str)
    
    def test_optimized_query_to_dict(self):
        """OptimizedQuery.to_dict() should produce JSON-serializable dict."""
        query = OptimizedQuery(
            language='en',
            core='test query',
            synonyms=['alternative query'],
            phrases=['test', 'query'],
            entities={'type': ['value']},
            tags=['tag1', 'tag2'],
            ban=['stopword'],
            followup_questions=['What else?'],
            raw_response='{"test": "data"}'
        )
        
        result = query.to_dict()
        
        # Should be a dict
        self.assertIsInstance(result, dict)
        
        # Should have all fields
        self.assertEqual(result['language'], 'en')
        self.assertEqual(result['core'], 'test query')
        self.assertEqual(result['synonyms'], ['alternative query'])
        self.assertEqual(result['phrases'], ['test', 'query'])
        self.assertEqual(result['entities'], {'type': ['value']})
        self.assertEqual(result['tags'], ['tag1', 'tag2'])
        self.assertEqual(result['ban'], ['stopword'])
        self.assertEqual(result['followup_questions'], ['What else?'])
        self.assertEqual(result['raw_response'], '{"test": "data"}')
        
        # Should be JSON serializable
        json_str = json.dumps(result)
        self.assertIsInstance(json_str, str)
    
    def test_extended_rag_context_to_dict(self):
        """ExtendedRAGContext.to_dict() should produce JSON-serializable dict."""
        # Create sample objects
        item1 = RAGContextObject(
            object_type='item',
            object_id='1',
            title='Item 1',
            content='Content 1',
            source='agira',
            relevance_score=0.9,
            link='http://example.com/1',
            updated_at='2024-01-01'
        )
        item2 = RAGContextObject(
            object_type='attachment',
            object_id='2',
            title='Attachment 2',
            content='Content 2',
            source='agira',
            relevance_score=0.8,
            link='http://example.com/2',
            updated_at='2024-01-02'
        )
        
        optimized = OptimizedQuery(
            language='en',
            core='test',
            synonyms=[],
            phrases=[],
            entities={},
            tags=[],
            ban=[],
            followup_questions=[]
        )
        
        context = ExtendedRAGContext(
            query='test query',
            optimized_query=optimized,
            layer_a=[item2],
            layer_b=[item1],
            layer_c=[],
            all_items=[item2, item1],
            summary='Found 2 items',
            stats={'total': 2},
            debug={'debug_info': 'test'}
        )
        
        result = context.to_dict()
        
        # Should be a dict
        self.assertIsInstance(result, dict)
        
        # Should have all fields
        self.assertEqual(result['query'], 'test query')
        self.assertIsNotNone(result['optimized_query'])
        self.assertEqual(len(result['layer_a']), 1)
        self.assertEqual(len(result['layer_b']), 1)
        self.assertEqual(len(result['layer_c']), 0)
        self.assertEqual(len(result['all_items']), 2)
        self.assertEqual(result['summary'], 'Found 2 items')
        self.assertEqual(result['stats'], {'total': 2})
        self.assertEqual(result['debug'], {'debug_info': 'test'})
        
        # Should be JSON serializable
        json_str = json.dumps(result)
        self.assertIsInstance(json_str, str)
        
        # Verify deserialized data
        deserialized = json.loads(json_str)
        self.assertEqual(deserialized['query'], 'test query')
        self.assertEqual(len(deserialized['all_items']), 2)
    
    def test_extended_rag_context_to_dict_without_optimized_query(self):
        """ExtendedRAGContext.to_dict() should handle None optimized_query."""
        item = RAGContextObject(
            object_type='item',
            object_id='1',
            title='Item 1',
            content='Content 1',
            source='agira',
            relevance_score=0.9,
            link=None,
            updated_at=None
        )
        
        context = ExtendedRAGContext(
            query='test',
            optimized_query=None,  # No optimization
            layer_a=[],
            layer_b=[item],
            layer_c=[],
            all_items=[item],
            summary='Found 1 item',
            stats={},
            debug=None
        )
        
        result = context.to_dict()
        
        # Should handle None optimized_query
        self.assertIsNone(result['optimized_query'])
        
        # Should be JSON serializable
        json_str = json.dumps(result)
        self.assertIsInstance(json_str, str)
    
    def test_rag_context_to_dict(self):
        """RAGContext.to_dict() should produce JSON-serializable dict."""
        from core.services.rag.models import RAGContext
        
        item = RAGContextObject(
            object_type='item',
            object_id='1',
            title='Item 1',
            content='Content 1',
            source='agira',
            relevance_score=0.9,
            link='http://example.com/1',
            updated_at='2024-01-01'
        )
        
        context = RAGContext(
            query='test query',
            alpha=0.5,
            summary='Found 1 item',
            items=[item],
            stats={'total': 1},
            debug={'debug_info': 'test'}
        )
        
        result = context.to_dict()
        
        # Should be a dict
        self.assertIsInstance(result, dict)
        
        # Should have all fields
        self.assertEqual(result['query'], 'test query')
        self.assertEqual(result['alpha'], 0.5)
        self.assertEqual(result['summary'], 'Found 1 item')
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['stats'], {'total': 1})
        self.assertEqual(result['debug'], {'debug_info': 'test'})
        
        # Should be JSON serializable
        json_str = json.dumps(result)
        self.assertIsInstance(json_str, str)



class PrimaryAttachmentBoostTestCase(TestCase):
    """Test Primary Attachment Boost feature (Issue #416)."""
    
    def test_extract_filenames_from_text(self):
        """Should extract filenames from text."""
        from core.services.rag.extended_service import _extract_filenames_from_text
        
        # Test with markdown filename
        text = "Check the EXTENDED_RAG_PIPELINE_IMPLEMENTATION.md file"
        filenames = _extract_filenames_from_text(text)
        self.assertIn("extended_rag_pipeline_implementation.md", filenames)
        
        # Test with multiple filenames
        text = "See config.py and test_rag.py for details"
        filenames = _extract_filenames_from_text(text)
        self.assertIn("config.py", filenames)
        self.assertIn("test_rag.py", filenames)
        
        # Test with no filenames
        text = "This is just a regular query"
        filenames = _extract_filenames_from_text(text)
        self.assertEqual(len(filenames), 0)
    
    def test_primary_attachment_by_filename_match(self):
        """Should select primary attachment by filename match."""
        results = [
            {
                "object_id": "att-1",
                "object_type": "attachment",
                "title": "EXTENDED_RAG_PIPELINE_IMPLEMENTATION.md",
                "content": "RAG pipeline docs",
                "final_score": 0.7,
            },
            {
                "object_id": "att-2",
                "object_type": "attachment",
                "title": "other_doc.md",
                "content": "Other docs",
                "final_score": 0.9,  # Higher score but not filename match
            },
        ]
        
        query = "How does EXTENDED_RAG_PIPELINE_IMPLEMENTATION.md work?"
        
        primary_id = ExtendedRAGPipelineService._determine_primary_attachment(
            results, query, None
        )
        
        # Should select att-1 even though att-2 has higher score
        self.assertEqual(primary_id, "att-1")
    
    def test_primary_attachment_by_best_score(self):
        """Should select primary attachment by best score when no filename match."""
        results = [
            {
                "object_id": "att-1",
                "object_type": "attachment",
                "title": "doc1.md",
                "content": "Docs",
                "final_score": 0.7,
            },
            {
                "object_id": "att-2",
                "object_type": "attachment",
                "title": "doc2.md",
                "content": "More docs",
                "final_score": 0.9,
            },
        ]
        
        query = "How does the RAG pipeline work?"
        
        primary_id = ExtendedRAGPipelineService._determine_primary_attachment(
            results, query, None
        )
        
        # Should select att-2 with highest score
        self.assertEqual(primary_id, "att-2")
    
    def test_primary_attachment_fallback_first_attachment(self):
        """Should use first attachment when scores are missing."""
        results = [
            {
                "object_id": "att-1",
                "object_type": "attachment",
                "title": "doc1.md",
                "content": "Docs",
                "final_score": None,  # No score
            },
            {
                "object_id": "att-2",
                "object_type": "attachment",
                "title": "doc2.md",
                "content": "More docs",
                "final_score": None,  # No score
            },
        ]
        
        query = "How does the RAG pipeline work?"
        
        primary_id = ExtendedRAGPipelineService._determine_primary_attachment(
            results, query, None
        )
        
        # Should select first attachment when scores are all 0/None
        self.assertEqual(primary_id, "att-1")
    
    def test_no_primary_when_no_attachments(self):
        """Should return None when no attachments in results."""
        results = [
            {
                "object_id": "item-1",
                "object_type": "item",
                "title": "Some item",
                "content": "Content",
                "final_score": 0.9,
            },
        ]
        
        query = "test query"
        
        primary_id = ExtendedRAGPipelineService._determine_primary_attachment(
            results, query, None
        )
        
        self.assertIsNone(primary_id)
    
    def test_get_primary_content_length(self):
        """Should return appropriate primary content length based on thinking level."""
        from core.services.rag.config import (
            PRIMARY_MAX_CONTENT_LENGTH_STANDARD,
            PRIMARY_MAX_CONTENT_LENGTH_EXTENDED,
            PRIMARY_MAX_CONTENT_LENGTH_PRO,
        )
        
        # Standard level (6000)
        length = ExtendedRAGPipelineService._get_primary_content_length(6000)
        self.assertEqual(length, PRIMARY_MAX_CONTENT_LENGTH_STANDARD)
        
        # Extended level (10000)
        length = ExtendedRAGPipelineService._get_primary_content_length(10000)
        self.assertEqual(length, PRIMARY_MAX_CONTENT_LENGTH_EXTENDED)
        
        # Pro level (15000+)
        length = ExtendedRAGPipelineService._get_primary_content_length(15000)
        self.assertEqual(length, PRIMARY_MAX_CONTENT_LENGTH_PRO)
    
    def test_parse_markdown_sections(self):
        """Should parse markdown into sections."""
        from core.services.rag.extended_service import _parse_markdown_sections
        
        markdown = """# Introduction
This is the intro.

## Section 1
Content for section 1.

## Section 2
Content for section 2.

### Subsection 2.1
Subsection content.
"""
        
        sections = _parse_markdown_sections(markdown)
        
        # Should find 4 sections
        self.assertEqual(len(sections), 4)
        self.assertEqual(sections[0]["heading"], "Introduction")
        self.assertEqual(sections[0]["level"], 1)
        self.assertEqual(sections[1]["heading"], "Section 1")
        self.assertEqual(sections[1]["level"], 2)
        self.assertEqual(sections[2]["heading"], "Section 2")
        self.assertEqual(sections[3]["heading"], "Subsection 2.1")
        self.assertEqual(sections[3]["level"], 3)
    
    def test_generate_toc(self):
        """Should generate table of contents from sections."""
        from core.services.rag.extended_service import _generate_toc
        
        sections = [
            {"heading": "Introduction", "level": 1},
            {"heading": "Section 1", "level": 2},
            {"heading": "Section 2", "level": 2},
        ]
        
        toc = _generate_toc(sections)
        
        self.assertIn("Table of Contents", toc)
        self.assertIn("Introduction", toc)
        self.assertIn("Section 1", toc)
        self.assertIn("Section 2", toc)
    
    def test_score_section(self):
        """Should score sections based on keyword overlap."""
        from core.services.rag.extended_service import _score_section
        
        section = {
            "heading": "RAG Pipeline Fusion",
            "content": "This section describes the fusion process in detail.",
        }
        
        query_terms = ["rag", "fusion", "pipeline"]
        bonus_keywords = ["fusion", "scoring"]
        
        score = _score_section(section, query_terms, bonus_keywords)
        
        # Should have positive score due to keyword matches
        self.assertGreater(score, 0)
    
    @patch("core.services.rag.extended_service.ENABLE_PRIMARY_ATTACHMENT_BOOST", True)
    def test_small_doc_included_full(self):
        """Small primary attachments should be included in full."""
        from core.services.rag.config import SMALL_DOC_THRESHOLD
        
        # Create a small document (below threshold)
        small_content = "a" * (SMALL_DOC_THRESHOLD - 100)
        
        results = [
            {
                "object_id": "att-1",
                "object_type": "attachment",
                "title": "small_doc.md",
                "content": small_content,
                "final_score": 0.9,
            },
        ]
        
        query = "test query"
        optimized = OptimizedQuery(
            language="en",
            core="test",
            synonyms=[],
            phrases=[],
            entities={},
            tags=[],
            ban=[],
            followup_questions=[],
        )
        
        layer_a, layer_b, layer_c = ExtendedRAGPipelineService._separate_into_layers(
            results,
            max_content_length=6000,
            query=query,
            optimized=optimized,
        )
        
        # Should have one item in layer_a (attachment)
        self.assertEqual(len(layer_a), 1)
        
        # Content should be complete (not truncated)
        self.assertEqual(len(layer_a[0].content), len(small_content))
    
    @patch("core.services.rag.extended_service.ENABLE_PRIMARY_ATTACHMENT_BOOST", True)
    def test_large_doc_section_aware_trim_respects_budget(self):
        """Large primary attachments should use section-aware trimming."""
        from core.services.rag.config import SMALL_DOC_THRESHOLD, PRIMARY_MAX_CONTENT_LENGTH_STANDARD
        
        # Create a large markdown document
        large_content = """# Introduction
This is the introduction section with some content.

## RAG Pipeline
This section describes the RAG pipeline in detail. """ + ("x" * 10000) + """

## Fusion Process
This section describes the fusion process. """ + ("y" * 10000) + """

## Conclusion
Final thoughts.
"""
        
        results = [
            {
                "object_id": "att-1",
                "object_type": "attachment",
                "title": "large_doc.md",
                "content": large_content,
                "final_score": 0.9,
            },
        ]
        
        query = "How does the RAG pipeline work?"
        optimized = OptimizedQuery(
            language="en",
            core="RAG pipeline",
            synonyms=[],
            phrases=["RAG pipeline"],
            entities={},
            tags=["rag", "pipeline"],
            ban=[],
            followup_questions=[],
        )
        
        layer_a, layer_b, layer_c = ExtendedRAGPipelineService._separate_into_layers(
            results,
            max_content_length=6000,
            query=query,
            optimized=optimized,
        )
        
        # Should have one item in layer_a
        self.assertEqual(len(layer_a), 1)
        
        # Content should be trimmed to primary budget
        self.assertLessEqual(len(layer_a[0].content), PRIMARY_MAX_CONTENT_LENGTH_STANDARD)
        
        # Should contain TOC or relevant sections (section-aware)
        content = layer_a[0].content
        self.assertTrue(
            "Table of Contents" in content or "RAG Pipeline" in content,
            "Smart-trimmed content should include TOC or relevant sections"
        )
    
    @patch("core.services.rag.extended_service.ENABLE_PRIMARY_ATTACHMENT_BOOST", True)
    def test_non_primary_docs_still_truncated_to_max_content_length(self):
        """Non-primary documents should use normal truncation."""
        from core.services.rag.config import MAX_CONTENT_LENGTH
        
        # Create two attachments
        large_content = "a" * 20000
        
        results = [
            {
                "object_id": "att-1",
                "object_type": "attachment",
                "title": "primary_doc.md",
                "content": large_content,
                "final_score": 0.9,  # Highest score - will be primary
            },
            {
                "object_id": "att-2",
                "object_type": "attachment",
                "title": "other_doc.md",
                "content": large_content,
                "final_score": 0.7,  # Lower score - not primary
            },
        ]
        
        query = "test query"
        optimized = OptimizedQuery(
            language="en",
            core="test",
            synonyms=[],
            phrases=[],
            entities={},
            tags=[],
            ban=[],
            followup_questions=[],
        )
        
        layer_a, layer_b, layer_c = ExtendedRAGPipelineService._separate_into_layers(
            results,
            max_content_length=6000,
            query=query,
            optimized=optimized,
        )
        
        # Should have two items in layer_a
        self.assertEqual(len(layer_a), 2)
        
        # First item (primary) should have more content
        primary_item = layer_a[0]  # att-1 with score 0.9
        non_primary_item = layer_a[1]  # att-2 with score 0.7
        
        # Non-primary should be truncated to MAX_CONTENT_LENGTH
        # (with "..." added, so slightly longer)
        self.assertLessEqual(len(non_primary_item.content), MAX_CONTENT_LENGTH + 10)
        
        # Primary should have more content (using primary budget)
        self.assertGreater(len(primary_item.content), len(non_primary_item.content))

