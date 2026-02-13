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
