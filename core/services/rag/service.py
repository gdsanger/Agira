"""
RAG Pipeline Service implementation.
"""

import logging
import re
from typing import Optional, List, Dict, Any
from datetime import datetime

from weaviate.classes.query import Filter, HybridFusion

from core.services.weaviate.client import get_client, is_available
from core.services.weaviate.schema import COLLECTION_NAME
from core.services.exceptions import ServiceDisabled

from .models import RAGContext, RAGContextObject
from .config import (
    DEFAULT_LIMIT,
    DEFAULT_ALPHA_KEYWORD,
    DEFAULT_ALPHA_SEMANTIC,
    DEFAULT_ALPHA_BALANCED,
    MAX_CONTENT_LENGTH,
    DEDUP_FETCH_MULTIPLIER,
    TYPE_PRIORITY,
    FIELD_MAPPING,
    ALLOWED_OBJECT_TYPES,
)

logger = logging.getLogger(__name__)


class RAGPipelineService:
    """
    RAG Pipeline Service for hybrid search and context aggregation.
    
    This service provides hybrid search (BM25 + Vector) over Weaviate data
    and returns structured, agent-ready context.
    """
    
    @staticmethod
    def _determine_alpha(query: str) -> float:
        """
        Determine optimal alpha value based on query characteristics.
        
        Alpha controls hybrid search weighting:
        - Low alpha (0.2) = more BM25/keyword weight (for structured queries)
        - High alpha (0.7) = more vector/semantic weight (for natural language)
        - Balanced (0.5) = equal weighting
        
        Args:
            query: Search query text
            
        Returns:
            Alpha value between 0 and 1
        """
        # Keyword-heavy indicators (must match whole words or be very specific)
        keyword_patterns = [
            r'#\d+',  # Issue IDs like #36
            r'\bv\d+(\.\d+)+\b',  # Version numbers like v1.2.3
            r'[A-Z][a-z]+[A-Z]',  # PascalCase (at least 2 capitals)
            r'[a-z]+[A-Z][a-z]+',  # camelCase
            r'\b[a-z]+_[a-z]+\b',  # snake_case
            r'(Exception|Error|Traceback|Stack)',  # Error keywords (matches anywhere, including NullPointerException)
            r'HTTP\s*[45]\d\d',  # HTTP error codes
            r'(Null|Undefined|Reference)',  # Common error terms (matches anywhere)
        ]
        
        # Check for keyword patterns
        keyword_count = sum(
            1 for pattern in keyword_patterns
            if re.search(pattern, query)
        )
        
        # Count special characters (excluding spaces)
        special_chars = len(re.findall(r'[^\w\s]', query))
        
        # Count words
        words = query.split()
        word_count = len(words)
        
        # Any keyword pattern present -> keyword search (unless very long query)
        if keyword_count > 0 and word_count <= 10:
            return DEFAULT_ALPHA_KEYWORD
        
        # Multiple keyword patterns detected -> keyword-heavy even for longer queries
        if keyword_count >= 2:
            return DEFAULT_ALPHA_KEYWORD
        
        # Long natural language queries -> semantic search
        if word_count > 10 and keyword_count == 0:
            return DEFAULT_ALPHA_SEMANTIC
        
        # Default: balanced
        return DEFAULT_ALPHA_BALANCED
    
    @staticmethod
    def _truncate_content(content: str, max_length: int = MAX_CONTENT_LENGTH) -> str:
        """
        Truncate content to a maximum length, respecting word boundaries.
        
        Args:
            content: Content text to truncate
            max_length: Maximum length in characters
            
        Returns:
            Truncated content with ellipsis if needed
        """
        if not content or len(content) <= max_length:
            return content
        
        # Find the last space before max_length
        truncated = content[:max_length]
        last_space = truncated.rfind(' ')
        
        if last_space > max_length * 0.8:  # Only use word boundary if it's not too far back
            truncated = truncated[:last_space]
        
        return truncated.rstrip() + "..."
    
    @staticmethod
    def _generate_summary(items: List[RAGContextObject]) -> str:
        """
        Generate a heuristic summary of the search results.
        
        Args:
            items: List of context objects
            
        Returns:
            Human-readable summary string
        """
        if not items:
            return "No related objects found."
        
        # Count by type
        type_counts = {}
        for item in items:
            type_counts[item.object_type] = type_counts.get(item.object_type, 0) + 1
        
        # Build summary parts
        total = len(items)
        parts = [f"{count} {obj_type}{'s' if count > 1 else ''}" 
                 for obj_type, count in sorted(type_counts.items())]
        
        summary = f"Found {total} related object{'s' if total != 1 else ''}: {', '.join(parts)}."
        
        # Add note about GitHub issues/PRs if present
        if 'github_issue' in type_counts or 'github_pr' in type_counts:
            summary += " Includes GitHub issues/PRs."
        
        return summary
    
    @staticmethod
    def _deduplicate_and_rank(
        results: List[Dict[str, Any]],
        limit: int
    ) -> List[Dict[str, Any]]:
        """
        Deduplicate results by object_id and rank by relevance and type priority.
        
        Args:
            results: Raw search results from Weaviate
            limit: Maximum number of results to return
            
        Returns:
            Deduplicated and ranked results
        """
        # Deduplicate by object_id, keeping the first (highest scored) occurrence
        seen_ids = set()
        unique_results = []
        
        for result in results:
            obj_id = result.get('object_id')
            if obj_id and obj_id not in seen_ids:
                seen_ids.add(obj_id)
                unique_results.append(result)
        
        # Sort by relevance score (primary) and type priority (secondary)
        def sort_key(result):
            score = result.get('score', 0) or 0
            obj_type = result.get('object_type', '')
            type_prio = TYPE_PRIORITY.get(obj_type, 0)
            
            # Return tuple: higher score first, then higher type priority
            # Negate values for descending order
            return (-score, -type_prio)
        
        unique_results.sort(key=sort_key)
        
        # Limit results
        return unique_results[:limit]
    
    @staticmethod
    def build_context(
        *,
        query: str,
        project_id: Optional[str] = None,
        item_id: Optional[str] = None,
        current_item_id: Optional[str] = None,
        object_types: Optional[list[str]] = None,
        limit: int = DEFAULT_LIMIT,
        alpha: Optional[float] = None,
        include_debug: bool = False,
    ) -> RAGContext:
        """
        Build RAG context from Weaviate hybrid search.
        
        This is the main entry point for the RAG pipeline. It performs hybrid
        search over Weaviate data and returns structured context for AI agents.
        
        Args:
            query: Search query text
            project_id: Optional project ID filter
            item_id: Optional item ID filter (filters on parent_object_id)
            current_item_id: Optional current item ID to exclude from results (Issue #392)
            object_types: Optional list of object types to filter (e.g., ["item", "github_issue", "github_pr", "file"]).
                         If None, defaults to ALLOWED_OBJECT_TYPES (item, github_issue, github_pr, file)
            limit: Maximum number of results (default: 20)
            alpha: Hybrid search alpha value (0-1). If None, determined by heuristic
            include_debug: Include debug information in response
            
        Returns:
            RAGContext object with search results and metadata
            
        Example:
            >>> context = RAGPipelineService.build_context(
            ...     query="login bug with special characters",
            ...     project_id="1",
            ...     current_item_id="123",  # Exclude item 123 from results
            ...     limit=10
            ... )
            >>> print(context.summary)
            >>> print(context.to_context_text())
        """
        # Determine alpha if not provided
        if alpha is None:
            alpha = RAGPipelineService._determine_alpha(query)
        
        # Initialize debug info
        debug_info = {
            'alpha_heuristic': alpha,
            'query_length': len(query),
            'word_count': len(query.split()),
        } if include_debug else None
        
        # Try to perform search, with graceful error handling
        items = []
        stats = {
            'total_results': 0,
            'deduplicated': 0,
            'error': None,
        }
        
        try:
            # Check if Weaviate is available
            if not is_available():
                logger.warning("Weaviate is not available, returning empty context")
                stats['error'] = 'Weaviate not configured or disabled'
                return RAGContext(
                    query=query,
                    alpha=alpha,
                    summary="Weaviate is not available.",
                    items=[],
                    stats=stats,
                    debug=debug_info,
                )
            
            # Get Weaviate client
            client = get_client()
            try:
                # Get collection
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
                    # Create OR filter for multiple types
                    type_filters = [
                        Filter.by_property(FIELD_MAPPING['object_type']).equal(obj_type)
                        for obj_type in object_types
                    ]
                    
                    if len(type_filters) == 1:
                        type_filter = type_filters[0]
                    else:
                        # Combine with OR
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
                
                # Perform hybrid search
                response = collection.query.hybrid(
                    query=query,
                    limit=limit * DEDUP_FETCH_MULTIPLIER,  # Fetch more for deduplication
                    alpha=alpha,
                    filters=where_filter,
                    fusion_type=HybridFusion.RELATIVE_SCORE,
                )
                
                # Extract results
                raw_results = []
                for obj in response.objects:
                    props = obj.properties
                    
                    # Map fields using FIELD_MAPPING
                    result = {
                        'object_id': props.get(FIELD_MAPPING['object_id']),
                        'object_type': props.get(FIELD_MAPPING['object_type']),
                        'title': props.get(FIELD_MAPPING['title']),
                        'content': props.get(FIELD_MAPPING['content'], ''),
                        'link': props.get(FIELD_MAPPING['link']),
                        'source': props.get(FIELD_MAPPING['source']),
                        'updated_at': props.get(FIELD_MAPPING['updated_at']),
                        'score': getattr(obj.metadata, 'score', None),
                    }
                    raw_results.append(result)
                
                stats['total_results'] = len(raw_results)
                
                # Deduplicate and rank
                unique_results = RAGPipelineService._deduplicate_and_rank(
                    raw_results,
                    limit
                )
                
                stats['deduplicated'] = len(unique_results)
                
                # Convert to RAGContextObject
                for result in unique_results:
                    # Truncate content
                    content = RAGPipelineService._truncate_content(
                        result.get('content', '')
                    )
                    
                    # Format updated_at if it's a datetime
                    updated_at = result.get('updated_at')
                    if isinstance(updated_at, datetime):
                        updated_at = updated_at.isoformat()
                    elif updated_at:
                        updated_at = str(updated_at)
                    
                    items.append(RAGContextObject(
                        object_type=result.get('object_type', 'unknown'),
                        object_id=str(result.get('object_id', '')),
                        title=result.get('title'),
                        content=content,
                        source=result.get('source'),
                        relevance_score=result.get('score'),
                        link=result.get('link'),
                        updated_at=updated_at,
                    ))
                
            finally:
                client.close()
        
        except ServiceDisabled as e:
            logger.warning(f"Weaviate service disabled: {e}")
            stats['error'] = str(e)
        except Exception as e:
            logger.error(f"Error during RAG search: {e}", exc_info=True)
            stats['error'] = str(e)
        
        # Generate summary
        summary = RAGPipelineService._generate_summary(items)
        
        return RAGContext(
            query=query,
            alpha=alpha,
            summary=summary,
            items=items,
            stats=stats,
            debug=debug_info,
        )


# Convenience function for direct access
def build_context(**kwargs) -> RAGContext:
    """
    Build RAG context from Weaviate hybrid search.
    
    This is a convenience wrapper around RAGPipelineService.build_context().
    See RAGPipelineService.build_context() for full documentation.
    """
    return RAGPipelineService.build_context(**kwargs)
