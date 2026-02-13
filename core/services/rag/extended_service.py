"""
Extended RAG Pipeline Service with Question Optimization, Hybrid Search and A/B/C-Fusion.

This service extends the basic RAG pipeline with:
1. Question optimization via AI agent (semantic simplification, synonym enrichment)
2. Parallel search paths (semantic/hybrid + keyword/tag)
3. Advanced fusion and reranking
4. A/B/C-Layer context bundling (Thread/Task, Item, Global)
"""

import json
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from core.services.agents.agent_service import AgentService
from core.services.weaviate.client import get_client, is_available
from core.services.weaviate.schema import COLLECTION_NAME
from core.services.exceptions import ServiceDisabled
from weaviate.classes.query import Filter, HybridFusion

from .models import RAGContextObject
from .config import FIELD_MAPPING, MAX_CONTENT_LENGTH, TYPE_PRIORITY, ALLOWED_OBJECT_TYPES

logger = logging.getLogger(__name__)


@dataclass
class OptimizedQuery:
    """
    Optimized query from question-optimization-agent.
    
    Attributes:
        language: Detected language (e.g., "de", "en")
        core: Core question in 3-5 words
        synonyms: List of synonyms/alternative formulations
        phrases: List of key phrases
        entities: Dictionary of recognized entities
        tags: List of technical/domain tags
        ban: Words to exclude from search
        followup_questions: Potential follow-up questions
        raw_response: Raw JSON response from agent
    """
    language: str
    core: str
    synonyms: List[str]
    phrases: List[str]
    entities: Dict[str, List[str]]
    tags: List[str]
    ban: List[str]
    followup_questions: List[str]
    raw_response: Optional[str] = None


@dataclass
class ExtendedRAGContext:
    """
    Extended RAG context with A/B/C-layer bundling.
    
    Attributes:
        query: Original query
        optimized_query: Optimized query from agent
        layer_a: Thread/Task-related snippets (2-3)
        layer_b: Item context snippets (2-3)
        layer_c: Global background snippets (1-2)
        all_items: All retrieved items (before layer separation)
        summary: Human-readable summary
        stats: Statistics about the retrieval
        debug: Optional debug information
    """
    query: str
    optimized_query: Optional[OptimizedQuery]
    layer_a: List[RAGContextObject]
    layer_b: List[RAGContextObject]
    layer_c: List[RAGContextObject]
    all_items: List[RAGContextObject]
    summary: str
    stats: Dict[str, Any] = field(default_factory=dict)
    debug: Optional[Dict[str, Any]] = None
    
    def to_context_text(self) -> str:
        """
        Generate LLM-friendly context text with A/B/C layer markers.
        
        Returns:
            Formatted context text with layer indicators
        """
        lines = ["CONTEXT:"]
        
        # Layer A: Thread/Task-related
        if self.layer_a:
            for idx, item in enumerate(self.layer_a, 1):
                score_str = f"score={item.relevance_score:.2f}" if item.relevance_score else "score=N/A"
                header = f"[#A{idx}] (type={item.object_type} {score_str})"
                if item.title:
                    header += f" {item.title}"
                lines.append(header)
                if item.link:
                    lines.append(f"       Link: {item.link}")
                lines.append(f"       {item.content}")
                lines.append("")
        
        # Layer B: Item context
        if self.layer_b:
            for idx, item in enumerate(self.layer_b, 1):
                score_str = f"score={item.relevance_score:.2f}" if item.relevance_score else "score=N/A"
                header = f"[#B{idx}] (type={item.object_type} {score_str})"
                if item.title:
                    header += f" {item.title}"
                lines.append(header)
                if item.link:
                    lines.append(f"       Link: {item.link}")
                lines.append(f"       {item.content}")
                lines.append("")
        
        # Layer C: Global background
        if self.layer_c:
            for idx, item in enumerate(self.layer_c, 1):
                score_str = f"score={item.relevance_score:.2f}" if item.relevance_score else "score=N/A"
                header = f"[#C{idx}] (type={item.object_type} {score_str})"
                if item.title:
                    header += f" {item.title}"
                lines.append(header)
                if item.link:
                    lines.append(f"       Link: {item.link}")
                lines.append(f"       {item.content}")
                lines.append("")
        
        return "\n".join(lines)


class ExtendedRAGPipelineService:
    """
    Extended RAG Pipeline Service with AI-powered query optimization and multi-path retrieval.
    """
    
    @staticmethod
    def _optimize_question(query: str, user=None, client_ip: Optional[str] = None) -> Optional[OptimizedQuery]:
        """
        Optimize question using question-optimization-agent.
        
        Args:
            query: Raw user question
            user: Optional user for AI tracking
            client_ip: Optional client IP
            
        Returns:
            OptimizedQuery object or None if optimization fails
        """
        try:
            agent_service = AgentService()
            response = agent_service.execute_agent(
                filename='question-optimization-agent.yml',
                input_text=query,
                user=user,
                client_ip=client_ip
            )
            
            # Clean response: remove markdown code fences if present
            cleaned_response = response.strip()
            if cleaned_response.startswith('```'):
                # Remove code fences
                lines = cleaned_response.split('\n')
                # Find first and last fence
                start_idx = 0
                end_idx = len(lines)
                for i, line in enumerate(lines):
                    if line.startswith('```'):
                        if start_idx == 0:
                            start_idx = i + 1
                        else:
                            end_idx = i
                            break
                cleaned_response = '\n'.join(lines[start_idx:end_idx])
            
            # Parse JSON
            data = json.loads(cleaned_response)
            
            # Validate required fields
            required_fields = ['language', 'core', 'synonyms', 'phrases', 'entities', 'tags', 'ban', 'followup_questions']
            for field in required_fields:
                if field not in data:
                    logger.warning(f"Missing field '{field}' in question optimization response")
                    return None
            
            return OptimizedQuery(
                language=data.get('language', 'de'),
                core=data.get('core', ''),
                synonyms=data.get('synonyms', []),
                phrases=data.get('phrases', []),
                entities=data.get('entities', {}),
                tags=data.get('tags', []),
                ban=data.get('ban', []),
                followup_questions=data.get('followup_questions', []),
                raw_response=cleaned_response
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse question optimization response as JSON: {e}")
            logger.debug(f"Raw response: {response}")
            return None
        except Exception as e:
            logger.error(f"Error optimizing question: {e}", exc_info=True)
            return None
    
    @staticmethod
    def _build_semantic_query(optimized: OptimizedQuery) -> str:
        """
        Build semantic/hybrid search query from optimized question.
        
        Uses: core + top 3 synonyms + top 2 phrases + top 2 tags
        
        Args:
            optimized: Optimized query
            
        Returns:
            Query string for semantic search
        """
        parts = [optimized.core]
        
        # Add top 3 synonyms
        parts.extend(optimized.synonyms[:3])
        
        # Add top 2 phrases
        parts.extend(optimized.phrases[:2])
        
        # Add top 2 tags
        parts.extend(optimized.tags[:2])
        
        return ' '.join(parts)
    
    @staticmethod
    def _build_keyword_query(optimized: OptimizedQuery) -> str:
        """
        Build keyword/tag search query from optimized question.
        
        Uses: tags + core
        
        Args:
            optimized: Optimized query
            
        Returns:
            Query string for keyword search
        """
        parts = optimized.tags.copy()
        parts.append(optimized.core)
        return ' '.join(parts)
    
    @staticmethod
    def _perform_search(
        query_text: str,
        alpha: float,
        project_id: Optional[str] = None,
        item_id: Optional[str] = None,
        current_item_id: Optional[str] = None,
        object_types: Optional[List[str]] = None,
        limit: int = 24
    ) -> List[Dict[str, Any]]:
        """
        Perform a single Weaviate hybrid search.
        
        Args:
            query_text: Query string
            alpha: Hybrid search alpha (0-1)
            project_id: Optional project filter
            item_id: Optional item filter
            current_item_id: Optional current item ID to exclude from results (Issue #392)
            object_types: Optional type filter (e.g., ["item", "github_issue", "github_pr", "file"]).
                         If None, defaults to ALLOWED_OBJECT_TYPES (item, github_issue, github_pr, file)
            limit: Maximum results
            
        Returns:
            List of result dictionaries
        """
        if not is_available():
            logger.warning("Weaviate is not available")
            return []
        
        try:
            client = get_client()
            try:
                collection = client.collections.get(COLLECTION_NAME)
                
                # Build filters
                where_filter = None
                
                # Default to ALLOWED_OBJECT_TYPES if not specified (Issue #392)
                if object_types is None:
                    object_types = ALLOWED_OBJECT_TYPES
                
                if project_id:
                    where_filter = Filter.by_property(
                        FIELD_MAPPING['project_id']
                    ).equal(str(project_id))
                
                if item_id:
                    item_filter = Filter.by_property(
                        FIELD_MAPPING['item_id']
                    ).equal(str(item_id))
                    where_filter = (
                        where_filter & item_filter
                        if where_filter
                        else item_filter
                    )
                
                # Exclude current item from results (Issue #392)
                if current_item_id:
                    current_item_filter = Filter.by_property(
                        FIELD_MAPPING['object_id']
                    ).not_equal(str(current_item_id))
                    
                    where_filter = (
                        where_filter & current_item_filter
                        if where_filter
                        else current_item_filter
                    )
                
                if object_types:
                    type_filters = [
                        Filter.by_property(FIELD_MAPPING['object_type']).equal(obj_type)
                        for obj_type in object_types
                    ]
                    if len(type_filters) == 1:
                        type_filter = type_filters[0]
                    else:
                        type_filter = type_filters[0]
                        for tf in type_filters[1:]:
                            type_filter = type_filter | tf
                    where_filter = (
                        where_filter & type_filter
                        if where_filter
                        else type_filter
                    )
                
                # Exclude files without text content (Issue #392)
                # Files with only title but no text are worthless
                # is_none(False) means: keep only items where text IS NOT NULL
                text_filter = Filter.by_property(FIELD_MAPPING['content']).is_none(False)
                
                where_filter = (
                    where_filter & text_filter
                    if where_filter
                    else text_filter
                )
                
                # Perform search
                response = collection.query.hybrid(
                    query=query_text,
                    limit=limit,
                    alpha=alpha,
                    filters=where_filter,
                    fusion_type=HybridFusion.RELATIVE_SCORE,
                )
                
                # Extract results
                results = []
                for obj in response.objects:
                    props = obj.properties
                    result = {
                        'object_id': props.get(FIELD_MAPPING['object_id']),
                        'object_type': props.get(FIELD_MAPPING['object_type']),
                        'title': props.get(FIELD_MAPPING['title']),
                        'content': props.get(FIELD_MAPPING['content'], ''),
                        'link': props.get(FIELD_MAPPING['link']),
                        'source': props.get(FIELD_MAPPING['source']),
                        'updated_at': props.get(FIELD_MAPPING['updated_at']),
                        'score': getattr(obj.metadata, 'score', None),
                        'search_type': 'semantic' if alpha >= 0.5 else 'keyword'
                    }
                    results.append(result)
                
                return results
                
            finally:
                client.close()
                
        except Exception as e:
            logger.error(f"Error performing Weaviate search: {e}", exc_info=True)
            return []
    
    @staticmethod
    def _fuse_and_rerank(
        sem_results: List[Dict[str, Any]],
        kw_results: List[Dict[str, Any]],
        item_id: Optional[str] = None,
        limit: int = 6
    ) -> List[Dict[str, Any]]:
        """
        Fuse and rerank results from semantic and keyword searches.
        
        Scoring formula:
        final_score = 0.6*sim_sem + 0.2*bm25 + 0.15*tag_match + 0.05*same_item
        
        Args:
            sem_results: Results from semantic search
            kw_results: Results from keyword search
            item_id: Optional item ID for same-item bonus
            limit: Top N results to return
            
        Returns:
            Top-N fused and reranked results
        """
        # Deduplicate by object_id, keeping both scores
        results_map = {}
        
        for result in sem_results:
            obj_id = result.get('object_id')
            if obj_id:
                results_map[obj_id] = {
                    **result,
                    'sem_score': result.get('score', 0) or 0,
                    'kw_score': 0,
                }
        
        for result in kw_results:
            obj_id = result.get('object_id')
            if obj_id:
                if obj_id in results_map:
                    # Update keyword score
                    results_map[obj_id]['kw_score'] = result.get('score', 0) or 0
                else:
                    # New result from keyword search
                    results_map[obj_id] = {
                        **result,
                        'sem_score': 0,
                        'kw_score': result.get('score', 0) or 0,
                    }
        
        # Calculate fusion scores
        fused_results = []
        for obj_id, result in results_map.items():
            sem_score = result['sem_score']
            kw_score = result['kw_score']
            
            # Tag match score: higher if from keyword search
            tag_match_score = 1.0 if kw_score > 0 else 0.5
            
            # Same item bonus
            same_item_score = 1.0 if item_id and str(result.get('object_id')) == str(item_id) else 0.0
            
            # Final fusion score
            final_score = (
                0.6 * sem_score +
                0.2 * kw_score +
                0.15 * tag_match_score +
                0.05 * same_item_score
            )
            
            result['final_score'] = final_score
            result['score'] = final_score  # Update score for consistency
            fused_results.append(result)
        
        # Sort by final score descending
        fused_results.sort(key=lambda x: (-x['final_score'], -TYPE_PRIORITY.get(x.get('object_type', ''), 0)))
        
        # Return top N
        return fused_results[:limit]
    
    @staticmethod
    def _separate_into_layers(
        results: List[Dict[str, Any]],
        item_id: Optional[str] = None
    ) -> Tuple[List[RAGContextObject], List[RAGContextObject], List[RAGContextObject]]:
        """
        Separate results into A/B/C layers.
        
        Layer A: Thread/Task-related (2-3 snippets) - comments, related items
        Layer B: Item context (2-3 snippets) - same item or closely related
        Layer C: Global background (1-2 snippets) - general context
        
        Args:
            results: Fused and ranked results
            item_id: Optional item ID for context
            
        Returns:
            Tuple of (layer_a, layer_b, layer_c)
        """
        layer_a = []
        layer_b = []
        layer_c = []
        
        for result in results:
            obj_type = result.get('object_type', '')
            obj_id = str(result.get('object_id', ''))
            
            # Truncate content
            content = result.get('content', '')
            if len(content) > MAX_CONTENT_LENGTH:
                content = content[:MAX_CONTENT_LENGTH].rstrip() + "..."
            
            # Create RAGContextObject
            item = RAGContextObject(
                object_type=obj_type,
                object_id=obj_id,
                title=result.get('title'),
                content=content,
                source=result.get('source'),
                relevance_score=result.get('final_score') or result.get('score'),
                link=result.get('link'),
                updated_at=str(result.get('updated_at')) if result.get('updated_at') else None,
            )
            
            # Classify into layers
            # Layer A: Comments and closely related items (high relevance)
            if obj_type == 'comment' and len(layer_a) < 3:
                layer_a.append(item)
            # Layer B: Same item or item-level context
            elif (obj_type == 'item' or (item_id and obj_id == item_id)) and len(layer_b) < 3:
                layer_b.append(item)
            # Layer C: Global background
            elif len(layer_c) < 2:
                layer_c.append(item)
            # Overflow: add to appropriate layer if space available
            elif len(layer_a) < 3:
                layer_a.append(item)
            elif len(layer_b) < 3:
                layer_b.append(item)
            elif len(layer_c) < 2:
                layer_c.append(item)
        
        return layer_a, layer_b, layer_c
    
    @staticmethod
    def build_extended_context(
        *,
        query: str,
        project_id: Optional[str] = None,
        item_id: Optional[str] = None,
        current_item_id: Optional[str] = None,
        object_types: Optional[List[str]] = None,
        user=None,
        client_ip: Optional[str] = None,
        skip_optimization: bool = False,
        include_debug: bool = False,
    ) -> ExtendedRAGContext:
        """
        Build extended RAG context with question optimization and A/B/C-layer bundling.
        
        This is the main entry point for the extended RAG pipeline. It:
        1. Optimizes the question using AI agent
        2. Performs parallel semantic and keyword searches
        3. Fuses and reranks results
        4. Separates into A/B/C layers
        
        Args:
            query: Raw user question
            project_id: Optional project filter
            item_id: Optional item filter
            current_item_id: Optional current item ID to exclude from results (Issue #392)
            object_types: Optional object types filter (e.g., ["item", "github_issue", "github_pr", "file"]).
                         If None, defaults to ALLOWED_OBJECT_TYPES (item, github_issue, github_pr, file)
            user: Optional user for AI tracking
            client_ip: Optional client IP
            skip_optimization: Skip question optimization (use raw query)
            include_debug: Include debug information
            
        Returns:
            ExtendedRAGContext with layered results
        """
        stats = {
            'optimization_success': False,
            'sem_results': 0,
            'kw_results': 0,
            'fused_results': 0,
            'layer_a_count': 0,
            'layer_b_count': 0,
            'layer_c_count': 0,
        }
        
        debug_info = {} if include_debug else None
        
        # Step 1: Optimize question
        optimized = None
        if not skip_optimization:
            optimized = ExtendedRAGPipelineService._optimize_question(
                query, user=user, client_ip=client_ip
            )
            if optimized:
                stats['optimization_success'] = True
                if include_debug:
                    debug_info['optimized_query'] = {
                        'core': optimized.core,
                        'synonyms': optimized.synonyms,
                        'tags': optimized.tags,
                        'phrases': optimized.phrases,
                    }
        
        # Fallback: use raw query if optimization failed
        if not optimized:
            logger.info("Question optimization failed or skipped, using raw query")
            # Create a minimal OptimizedQuery
            optimized = OptimizedQuery(
                language='unknown',
                core=query,
                synonyms=[],
                phrases=[],
                entities={},
                tags=[],
                ban=[],
                followup_questions=[],
            )
        
        # Step 2: Build queries
        sem_query = ExtendedRAGPipelineService._build_semantic_query(optimized)
        kw_query = ExtendedRAGPipelineService._build_keyword_query(optimized)
        
        if include_debug:
            debug_info['queries'] = {
                'semantic': sem_query,
                'keyword': kw_query,
            }
        
        # Step 3: Parallel searches
        # Semantic/Hybrid search (alpha ≈ 0.6)
        sem_results = ExtendedRAGPipelineService._perform_search(
            query_text=sem_query,
            alpha=0.6,
            project_id=project_id,
            item_id=item_id,
            current_item_id=current_item_id,
            object_types=object_types,
            limit=24,
        )
        stats['sem_results'] = len(sem_results)
        
        # Keyword/Tag search (alpha = 0.3 for more BM25/keyword weight)
        kw_results = ExtendedRAGPipelineService._perform_search(
            query_text=kw_query,
            alpha=0.3,  # Lower alpha = more BM25/keyword weight
            project_id=project_id,
            item_id=item_id,
            current_item_id=current_item_id,
            object_types=object_types,
            limit=24,
        )
        stats['kw_results'] = len(kw_results)
        
        # Step 4: Fusion and reranking
        fused_results = ExtendedRAGPipelineService._fuse_and_rerank(
            sem_results=sem_results,
            kw_results=kw_results,
            item_id=item_id,
            limit=6,
        )
        stats['fused_results'] = len(fused_results)
        
        # Step 5: Separate into A/B/C layers
        layer_a, layer_b, layer_c = ExtendedRAGPipelineService._separate_into_layers(
            fused_results,
            item_id=item_id
        )
        
        stats['layer_a_count'] = len(layer_a)
        stats['layer_b_count'] = len(layer_b)
        stats['layer_c_count'] = len(layer_c)
        
        # Create all_items list
        all_items = layer_a + layer_b + layer_c
        
        # Generate summary
        total_items = len(all_items)
        summary = f"Retrieved {total_items} relevant items across {stats['layer_a_count']} thread-related, {stats['layer_b_count']} item-context, and {stats['layer_c_count']} background snippets."
        
        return ExtendedRAGContext(
            query=query,
            optimized_query=optimized if stats['optimization_success'] else None,
            layer_a=layer_a,
            layer_b=layer_b,
            layer_c=layer_c,
            all_items=all_items,
            summary=summary,
            stats=stats,
            debug=debug_info,
        )


# Convenience function
def build_extended_context(**kwargs) -> ExtendedRAGContext:
    """
    Build extended RAG context with question optimization and A/B/C-layer bundling.
    
    Convenience wrapper around ExtendedRAGPipelineService.build_extended_context().
    See ExtendedRAGPipelineService.build_extended_context() for full documentation.
    """
    return ExtendedRAGPipelineService.build_extended_context(**kwargs)
