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
import os
import re
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field

from core.services.agents.agent_service import AgentService
from core.services.weaviate.client import get_client, is_available
from core.services.weaviate.schema import COLLECTION_NAME
from core.services.exceptions import ServiceDisabled
from weaviate.classes.query import Filter, HybridFusion, MetadataQuery

from .models import RAGContextObject
from .config import (
    FIELD_MAPPING, MAX_CONTENT_LENGTH, TYPE_PRIORITY, ALLOWED_OBJECT_TYPES,
    ENABLE_PRIMARY_ATTACHMENT_BOOST,
    PRIMARY_ATTACHMENT_MIN_SCORE_THRESHOLD,
    PRIMARY_MAX_CONTENT_LENGTH_STANDARD,
    PRIMARY_MAX_CONTENT_LENGTH_EXTENDED,
    PRIMARY_MAX_CONTENT_LENGTH_PRO,
    SMALL_DOC_THRESHOLD,
)

# Configure logger for RAG pipeline with dedicated log file
logger = logging.getLogger(__name__)

# Setup RAG pipeline logger with file handler
rag_logger = logging.getLogger('rag_pipeline')
rag_logger.setLevel(logging.DEBUG)

# Create logs directory if it doesn't exist
# Get base directory (project root): core/services/rag/extended_service.py -> Agira/
try:
    from pathlib import Path
    base_dir = Path(__file__).parents[3]
    log_dir = base_dir / 'logs'
    log_dir.mkdir(exist_ok=True)
except Exception:
    # Fallback for older Python or if pathlib fails
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    log_dir = os.path.join(base_dir, 'logs')
    os.makedirs(log_dir, exist_ok=True)

# Add file handler if not already present
if not rag_logger.handlers:
    log_file = str(log_dir / 'rag_pipeline.log') if isinstance(log_dir, Path) else os.path.join(log_dir, 'rag_pipeline.log')
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    rag_logger.addHandler(file_handler)


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
    
    def to_dict(self) -> dict:
        """
        Convert to JSON-serializable dictionary.
        
        Returns:
            Dictionary with all fields as primitive types
        """
        return {
            'language': self.language,
            'core': self.core,
            'synonyms': self.synonyms,
            'phrases': self.phrases,
            'entities': self.entities,
            'tags': self.tags,
            'ban': self.ban,
            'followup_questions': self.followup_questions,
            'raw_response': self.raw_response,
        }


@dataclass
class ExtendedRAGContext:
    """
    Extended RAG context with A/B/C-layer bundling (Issue #407).
    
    Attributes:
        query: Original query
        optimized_query: Optimized query from agent
        layer_a: Documentation-focused snippets (2-3) - attachment + github_pr
        layer_b: Item context snippets (2-3) - item + github_issue
        layer_c: Global background snippets (1-2) - rest
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
    
    def to_dict(self) -> dict:
        """
        Convert to JSON-serializable dictionary.
        
        Returns:
            Dictionary with all fields as primitive types
        """
        return {
            'query': self.query,
            'optimized_query': self.optimized_query.to_dict() if self.optimized_query else None,
            'layer_a': [item.to_dict() for item in self.layer_a],
            'layer_b': [item.to_dict() for item in self.layer_b],
            'layer_c': [item.to_dict() for item in self.layer_c],
            'all_items': [item.to_dict() for item in self.all_items],
            'summary': self.summary,
            'stats': self.stats,
            'debug': self.debug,
        }
    
    def to_context_text(self) -> str:
        """
        Generate LLM-friendly context text with A/B/C layer markers.
        
        Returns:
            Formatted context text with layer indicators
        """
        lines = ["CONTEXT:"]
        
        # Layer A: Documentation-focused (attachment + github_pr)
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
        
        # Layer B: Item context (item + github_issue)
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


# Helper functions for Primary Attachment Boost (Issue #416)

# Constants for smart trimming and filename extraction
_MIN_FILE_EXTENSION_LEN = 2  # Minimum extension length (e.g., .py, .md)
_MAX_FILE_EXTENSION_LEN = 4  # Maximum extension length (e.g., .json, .yaml)
_MIN_QUERY_TERM_LEN = 3  # Minimum word length for query term extraction
_MAX_QUERY_TERMS = 10  # Maximum number of query terms to extract
_INTRO_TEXT_MAX_CHARS = 1500  # Maximum intro text length in smart trimming
_SECTION_SAFETY_MARGIN = 100  # Safety margin for content budget calculations
_SECTION_SEPARATOR_OVERHEAD = 50  # Overhead for section separators
_MAX_SECTIONS_IN_TRIM = 4  # Maximum sections to include in smart trim
_CONTENT_LENGTH_SCORE_DIVISOR = 1000  # Divisor for content length scoring bonus

# Bonus keywords for RAG-related queries (section scoring)
_RAG_BONUS_KEYWORDS = [
    'fusion', 'scoring', 'bm25', 'hybrid', 'alpha', 'rerank', 'dedup',
    'layer', 'weaviate', 'pipeline', 'question', 'optimization',
    'search', 'retrieval', 'semantic', 'keyword', 'tag'
]


def _extract_filenames_from_text(text: str) -> List[str]:
    """
    Extract potential filenames from text (query or optimized query).
    
    Looks for patterns like:
    - EXTENDED_RAG_PIPELINE_IMPLEMENTATION.md
    - some-file.txt
    - document.pdf
    
    Args:
        text: Text to search for filenames
        
    Returns:
        List of potential filenames (lowercase for matching)
    """
    if not text:
        return []
    
    # Pattern components (verbose regex for readability):
    # - Uppercase start pattern: [A-Z_][A-Z0-9_]* (e.g., EXTENDED_RAG_PIPELINE)
    # - Regular filename pattern: [a-zA-Z0-9_-]+ (e.g., config, test-file)
    # - Extension: \.[a-zA-Z0-9]{min,max} (e.g., .py, .md, .json)
    # Extension length limited to common file extensions (.py, .md, .txt, .json, .yaml)
    uppercase_pattern = rf'[A-Z_][A-Z0-9_]*\.[a-z]{{{_MIN_FILE_EXTENSION_LEN},{_MAX_FILE_EXTENSION_LEN}}}'
    regular_pattern = rf'[a-zA-Z0-9_-]+\.[a-zA-Z0-9]{{{_MIN_FILE_EXTENSION_LEN},{_MAX_FILE_EXTENSION_LEN}}}'
    pattern = rf'\b({uppercase_pattern}|{regular_pattern})\b'
    
    try:
        matches = re.findall(pattern, text, re.IGNORECASE)
        # Return unique filenames in lowercase for case-insensitive matching
        return list(set(m.lower() for m in matches))
    except (re.error, AttributeError):
        # Handle regex errors or None text gracefully
        return []


def _parse_markdown_sections(content: str) -> List[Dict[str, Any]]:
    """
    Parse markdown content into sections based on headings.
    
    Args:
        content: Markdown content
        
    Returns:
        List of sections with 'heading', 'level', 'content', 'start_pos'
    """
    sections = []
    lines = content.split('\n')
    current_section = None
    current_content = []
    
    for i, line in enumerate(lines):
        # Check if line is a heading (# to ###)
        heading_match = re.match(r'^(#{1,3})\s+(.+)$', line)
        
        if heading_match:
            # Save previous section if exists
            if current_section is not None:
                current_section['content'] = '\n'.join(current_content).strip()
                sections.append(current_section)
            
            # Start new section
            level = len(heading_match.group(1))
            heading = heading_match.group(2).strip()
            current_section = {
                'heading': heading,
                'level': level,
                'start_line': i,
                'raw_heading_line': line,
            }
            current_content = []
        else:
            # Add to current section content
            if current_section is not None:
                current_content.append(line)
    
    # Save last section
    if current_section is not None:
        current_section['content'] = '\n'.join(current_content).strip()
        sections.append(current_section)
    
    return sections


def _generate_toc(sections: List[Dict[str, Any]]) -> str:
    """
    Generate a table of contents from sections.
    
    Args:
        sections: List of section dictionaries
        
    Returns:
        Formatted TOC string
    """
    if not sections:
        return ""
    
    toc_lines = ["## Table of Contents", ""]
    for section in sections:
        indent = "  " * (section['level'] - 1)
        toc_lines.append(f"{indent}- {section['heading']}")
    
    return '\n'.join(toc_lines)


def _score_section(section: Dict[str, Any], query_terms: List[str], bonus_keywords: List[str]) -> float:
    """
    Score a section based on keyword overlap with query.
    
    Args:
        section: Section dictionary with 'heading' and 'content'
        query_terms: Terms from the query to match
        bonus_keywords: Additional bonus keywords (RAG-related terms)
        
    Returns:
        Score (higher is better)
    """
    text = (section['heading'] + ' ' + section['content']).lower()
    score = 0.0
    
    # Check query terms (case-insensitive)
    for term in query_terms:
        if term.lower() in text:
            # Heading matches count more
            if term.lower() in section['heading'].lower():
                score += 2.0
            else:
                score += 1.0
    
    # Bonus keywords
    for keyword in bonus_keywords:
        if keyword.lower() in text:
            score += 0.5
    
    # Prefer longer sections (more substantial content)
    # Normalized by dividing by divisor to keep scores in reasonable range
    content_length_bonus = min(len(section['content']) / _CONTENT_LENGTH_SCORE_DIVISOR, 2.0)
    score += content_length_bonus
    
    return score


def _extract_query_terms(query: str, optimized: Optional[OptimizedQuery] = None) -> List[str]:
    """
    Extract key terms from query and optimized query for section scoring.
    
    Args:
        query: Original query
        optimized: Optimized query object (if available)
        
    Returns:
        List of terms to use for scoring
    """
    terms = []
    
    # Add words from original query (minimum length to avoid short/meaningless terms)
    query_words = [w.strip() for w in re.split(r'\W+', query) if len(w.strip()) >= _MIN_QUERY_TERM_LEN]
    terms.extend(query_words[:_MAX_QUERY_TERMS])  # Limit to top N words to avoid over-matching
    
    # Add from optimized query if available
    if optimized:
        if optimized.core:
            core_words = [w.strip() for w in re.split(r'\W+', optimized.core) if len(w.strip()) >= _MIN_QUERY_TERM_LEN]
            terms.extend(core_words)
        terms.extend(optimized.tags[:5])  # Top 5 tags
        terms.extend(optimized.phrases[:3])  # Top 3 phrases
    
    # Deduplicate and return
    return list(set(terms))


def _smart_trim_markdown(
    content: str,
    max_length: int,
    query: str,
    optimized: Optional[OptimizedQuery] = None
) -> str:
    """
    Smart section-aware trimming for large markdown documents.
    
    Instead of simple truncation, this:
    1. Parses markdown into sections
    2. Generates a TOC
    3. Scores sections by keyword overlap
    4. Returns: intro + TOC + top relevant sections within budget
    
    Args:
        content: Full markdown content
        max_length: Maximum characters to return
        query: Original query
        optimized: Optimized query (if available)
        
    Returns:
        Trimmed markdown with TOC and relevant sections
    """
    # If content is already within budget, return as-is
    if len(content) <= max_length:
        return content
    
    rag_logger.info(f"Smart trimming markdown: {len(content)} chars -> {max_length} max")
    
    # Parse sections
    sections = _parse_markdown_sections(content)
    
    if not sections:
        # No sections found, fallback to simple truncation
        rag_logger.warning("No markdown sections found, using simple truncation")
        return content[:max_length].rstrip() + "\n\n[...truncated for length...]"
    
    rag_logger.debug(f"Found {len(sections)} sections")
    
    # Generate TOC
    toc = _generate_toc(sections)
    
    # Extract query terms for scoring
    query_terms = _extract_query_terms(query, optimized)
    
    # Use module-level bonus keywords for RAG-related queries
    bonus_keywords = _RAG_BONUS_KEYWORDS
    
    # Score sections
    for section in sections:
        section['score'] = _score_section(section, query_terms, bonus_keywords)
    
    # Sort by score
    scored_sections = sorted(sections, key=lambda s: s['score'], reverse=True)
    
    # Build output
    output_parts = []
    
    # Add intro (first ~N chars or content before first section heading)
    intro_text = ""
    if sections:
        # Get content before first heading
        first_heading_line = sections[0]['start_line']
        intro_lines = content.split('\n')[:first_heading_line]
        intro_text = '\n'.join(intro_lines).strip()
        
        if len(intro_text) > _INTRO_TEXT_MAX_CHARS:
            intro_text = intro_text[:_INTRO_TEXT_MAX_CHARS].rstrip() + "..."
    
    if intro_text:
        output_parts.append(intro_text)
    
    # Add TOC
    output_parts.append(toc)
    
    # Calculate remaining budget with safety margin to avoid going over
    used_chars = sum(len(p) for p in output_parts) + len(output_parts) * 2  # +2 for newlines
    remaining = max_length - used_chars - _SECTION_SAFETY_MARGIN
    
    # Add top sections until budget exhausted
    selected_sections = []
    for section in scored_sections:
        section_text = f"{section['raw_heading_line']}\n{section['content']}"
        section_len = len(section_text)
        
        if used_chars + section_len + _SECTION_SEPARATOR_OVERHEAD <= max_length:
            selected_sections.append(section)
            used_chars += section_len + _SECTION_SEPARATOR_OVERHEAD
        
        # Stop if we have enough sections (2-4 is usually good for readability)
        if len(selected_sections) >= _MAX_SECTIONS_IN_TRIM:
            break
    
    # Add selected sections (in document order, not score order)
    if selected_sections:
        output_parts.append("\n## Selected Relevant Sections\n")
        
        # Sort by start_line to maintain document order
        selected_sections.sort(key=lambda s: s['start_line'])
        
        for section in selected_sections:
            section_text = f"{section['raw_heading_line']}\n{section['content']}"
            output_parts.append(section_text)
    
    result = '\n\n'.join(output_parts)
    
    # Final safety check
    if len(result) > max_length:
        result = result[:max_length].rstrip() + "\n\n[...trimmed for length...]"
    
    rag_logger.info(f"Smart trim complete: {len(result)} chars, {len(selected_sections)} sections included")
    
    return result


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
        rag_logger.info(f"Starting question optimization for query: {query[:100]}...")
        try:
            agent_service = AgentService()
            response = agent_service.execute_agent(
                filename='question-optimization-agent.yml',
                input_text=query,
                user=user,
                client_ip=client_ip
            )
            rag_logger.debug(f"Agent response received: {response[:200]}...")
            
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
                    rag_logger.warning(f"Question optimization failed: missing field '{field}'")
                    return None
            
            optimized = OptimizedQuery(
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
            
            rag_logger.info(f"Question optimization successful: core='{optimized.core}', tags={optimized.tags}")
            return optimized
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse question optimization response as JSON: {e}")
            rag_logger.error(f"Question optimization failed: JSON parse error - {e}")
            logger.debug(f"Raw response: {response}")
            return None
        except Exception as e:
            logger.error(f"Error optimizing question: {e}", exc_info=True)
            rag_logger.error(f"Question optimization failed: {e}", exc_info=True)
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
            item_id: DEPRECATED - No longer used (Issue #395). Will be removed in version 2.0.0.
                     This parameter is kept for backward compatibility but has no effect.
                     Use current_item_id instead.
            current_item_id: Optional current item ID to exclude from results (Issue #395)
            object_types: Optional type filter (e.g., ["item", "github_issue", "github_pr", "file"]).
                         If None, defaults to ALLOWED_OBJECT_TYPES (item, github_issue, github_pr, file)
            limit: Maximum results
            
        Returns:
            List of result dictionaries
        """
        # Log deprecation warning if item_id is used
        if item_id is not None:
            rag_logger.warning(
                f"Parameter 'item_id' is deprecated and will be removed in version 2.0.0. "
                f"It is being ignored. Use 'current_item_id' instead. (item_id={item_id})"
            )
        
        rag_logger.info(f"Starting search: query='{query_text[:50]}...', alpha={alpha}, project_id={project_id}, current_item_id={current_item_id}, limit={limit}")
        
        if not is_available():
            logger.warning("Weaviate is not available")
            rag_logger.warning("Search aborted: Weaviate not available")
            return []
        
        try:
            client = get_client()
            try:
                collection = client.collections.get(COLLECTION_NAME)
                
                # Build filters
                where_filter = None
                filter_details = []
                
                # Default to ALLOWED_OBJECT_TYPES if not specified (Issue #392)
                if object_types is None:
                    object_types = ALLOWED_OBJECT_TYPES
                
                if project_id:
                    where_filter = Filter.by_property(
                        FIELD_MAPPING['project_id']
                    ).equal(str(project_id))
                    filter_details.append(f"project_id={project_id}")
                
                # NOTE: item_id filter REMOVED in Issue #395
                # Previously this was filtering by item_id, which conflicted with current_item_id exclusion
                # Now we search across ALL items in the project, excluding only current_item_id
                
                # Exclude current item from results (Issue #395)
                # This prevents the item itself from appearing in its own RAG context
                if current_item_id:
                    current_item_filter = Filter.by_property(
                        FIELD_MAPPING['object_id']
                    ).not_equal(str(current_item_id))
                    
                    where_filter = (
                        where_filter & current_item_filter
                        if where_filter
                        else current_item_filter
                    )
                    filter_details.append(f"exclude_object_id={current_item_id}")
                
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
                    filter_details.append(f"object_types={object_types}")
                
                # Note: is_none filter removed (Issue #398)
                # Filter for empty content is now done in Python after query
                # to avoid Weaviate schema requirement for indexNullState.
                # Trade-off: This may retrieve some items that will be filtered out,
                # but in practice most items have content and this ensures the query works.
                
                rag_logger.debug(f"Applied filters: {', '.join(filter_details)}")
                
                # Perform search
                rag_logger.debug(f"Executing Weaviate hybrid search...")
                response = collection.query.hybrid(
                    query=query_text,
                    limit=limit,
                    alpha=alpha,
                    filters=where_filter,
                    fusion_type=HybridFusion.RELATIVE_SCORE,
                    return_metadata=MetadataQuery(score=True),
                )
                
                # Extract results and filter empty content (Issue #398)
                results = []
                for obj in response.objects:
                    props = obj.properties
                    
                    # Exclude files without text content (Issue #392, #398)
                    # Filter in Python to avoid Weaviate schema requirement
                    text = (props.get(FIELD_MAPPING['content']) or '').strip()
                    if not text:
                        continue
                    
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
                
                rag_logger.info(f"Search completed: {len(results)} results found")
                rag_logger.debug(f"Top 3 results: {[r['object_id'] + ' (' + r['object_type'] + ')' for r in results[:3]]}")
                return results
                
            finally:
                client.close()
                
        except Exception as e:
            logger.error(f"Error performing Weaviate search: {e}", exc_info=True)
            rag_logger.error(f"Search failed with error: {e}", exc_info=True)
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
        rag_logger.info(f"Starting fusion: {len(sem_results)} semantic + {len(kw_results)} keyword results")
        
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
        
        rag_logger.info(f"Fusion completed: {len(fused_results)} unique results, returning top {limit}")
        rag_logger.debug(f"Top fused results: {[(r['object_id'], r['object_type'], '{:.3f}'.format(r['final_score'])) for r in fused_results[:3]]}")
        
        # Log distribution by object_type for top results (Issue #407)
        top_results = fused_results[:limit]
        type_counts = {}
        for r in top_results:
            obj_type = r.get('object_type', 'unknown')
            type_counts[obj_type] = type_counts.get(obj_type, 0) + 1
        
        rag_logger.info(f"Top fused results by type:")
        for obj_type, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            rag_logger.info(f"  {obj_type}: {count}")
        
        # Log attachment count in top-N (Issue #407)
        attachment_count = type_counts.get('attachment', 0)
        if limit > 0:
            percentage = (attachment_count / limit) * 100
            rag_logger.info(f"Attachments in top-{limit}: {attachment_count} ({percentage:.1f}%)")
        else:
            rag_logger.info(f"Attachments in top-{limit}: {attachment_count}")
        
        # Return top N
        return fused_results[:limit]
    
    @staticmethod
    def _determine_primary_attachment(
        results: List[Dict[str, Any]],
        query: str,
        optimized: Optional[OptimizedQuery] = None
    ) -> Optional[str]:
        """
        Determine which attachment (if any) should be treated as primary.
        
        Priority:
        1. Filename match: If query/optimized query contains a filename and it's in results
        2. Best scoring attachment: Attachment with highest final_score
        
        In both cases, the attachment must have a score >= PRIMARY_ATTACHMENT_MIN_SCORE_THRESHOLD
        to be eligible for the primary boost (Issue #422).
        
        Args:
            results: Fused and ranked results
            query: Original query
            optimized: Optimized query (if available)
            
        Returns:
            object_id of primary attachment, or None if no attachments meet criteria
        """
        if not ENABLE_PRIMARY_ATTACHMENT_BOOST:
            return None
        
        # Get all attachments from results
        attachments = [r for r in results if r.get('object_type') == 'attachment']
        
        if not attachments:
            rag_logger.debug("No attachments in results, no primary attachment")
            return None
        
        # Priority 1: Filename match
        # Extract filenames from query
        query_filenames = _extract_filenames_from_text(query)
        if optimized and optimized.core:
            query_filenames.extend(_extract_filenames_from_text(optimized.core))
        if optimized and optimized.phrases:
            for phrase in optimized.phrases:
                query_filenames.extend(_extract_filenames_from_text(phrase))
        
        query_filenames = list(set(query_filenames))  # Deduplicate
        
        if query_filenames:
            rag_logger.debug(f"Found filenames in query: {query_filenames}")
            
            # Check each attachment's title/link for filename match
            for attachment in attachments:
                title = (attachment.get('title') or '').lower()
                link = (attachment.get('link') or '').lower()
                
                for filename in query_filenames:
                    # Exact match or contains
                    if filename in title or filename in link:
                        obj_id = attachment.get('object_id')
                        score = attachment.get('final_score', 0) or 0
                        
                        # Check score threshold (Issue #422)
                        if score >= PRIMARY_ATTACHMENT_MIN_SCORE_THRESHOLD:
                            rag_logger.info(
                                f"Primary attachment determined by filename match: {obj_id} "
                                f"(matched '{filename}', score={score:.3f})"
                            )
                            return obj_id
                        else:
                            rag_logger.info(
                                f"Filename match found for {obj_id} ('{filename}'), "
                                f"but score {score:.3f} < threshold {PRIMARY_ATTACHMENT_MIN_SCORE_THRESHOLD:.2f}, "
                                f"continuing search"
                            )
        
        # Priority 2: Best scoring attachment
        best_attachment = max(attachments, key=lambda a: a.get('final_score', 0) or 0)
        obj_id = best_attachment.get('object_id')
        score = best_attachment.get('final_score', 0) or 0
        
        # Check score threshold (Issue #422)
        if score >= PRIMARY_ATTACHMENT_MIN_SCORE_THRESHOLD:
            rag_logger.info(f"Primary attachment determined by best score: {obj_id} (score={score:.3f})")
            return obj_id
        else:
            rag_logger.info(
                f"Best attachment {obj_id} has score {score:.3f} < threshold "
                f"{PRIMARY_ATTACHMENT_MIN_SCORE_THRESHOLD:.2f}, no primary attachment boost"
            )
            return None
    
    @staticmethod
    def _get_primary_content_length(max_content_length: Optional[int] = None) -> int:
        """
        Get the appropriate content length for primary attachments.
        
        Uses the provided max_content_length to determine the thinking level,
        then returns the corresponding primary attachment budget.
        
        Args:
            max_content_length: Current max content length (determines level)
            
        Returns:
            Primary attachment content length
        """
        if not max_content_length:
            max_content_length = MAX_CONTENT_LENGTH
        
        # Determine thinking level based on max_content_length
        # Standard: 6000, Extended: ~10000, Pro: ~15000+
        if max_content_length <= 6000:
            return PRIMARY_MAX_CONTENT_LENGTH_STANDARD
        elif max_content_length <= 12000:
            return PRIMARY_MAX_CONTENT_LENGTH_EXTENDED
        else:
            return PRIMARY_MAX_CONTENT_LENGTH_PRO
    
    @staticmethod
    def _separate_into_layers(
        results: List[Dict[str, Any]],
        item_id: Optional[str] = None,
        max_content_length: Optional[int] = None,
        query: Optional[str] = None,
        optimized: Optional[OptimizedQuery] = None,
    ) -> Tuple[List[RAGContextObject], List[RAGContextObject], List[RAGContextObject]]:
        """
        Separate results into A/B/C layers (Issue #407, #416).
        
        Layer A: Documentation-focused (2-3 snippets) - attachment + github_pr (highest technical relevance)
        Layer B: Item context (2-3 snippets) - item + github_issue
        Layer C: Global background (1-2 snippets) - rest
        
        Primary Attachment Boost (Issue #416):
        If enabled, one attachment can be designated as "primary" and receive boosted content budget.
        
        Args:
            results: Fused and ranked results
            item_id: .. deprecated::
                Not used in layer separation logic. Kept for backward compatibility only.
                This parameter has no effect and will be removed in a future version.
            max_content_length: Maximum content length for truncation. If None, uses MAX_CONTENT_LENGTH from config
            query: Original query (used for primary attachment selection and smart trimming)
            optimized: Optimized query (used for primary attachment selection and smart trimming)
            
        Returns:
            Tuple of (layer_a, layer_b, layer_c)
        """
        # Use provided max_content_length or default from config
        content_length = max_content_length if max_content_length is not None else MAX_CONTENT_LENGTH
        
        # Determine primary attachment (Issue #416)
        primary_attachment_id = None
        primary_content_length = content_length
        
        if ENABLE_PRIMARY_ATTACHMENT_BOOST and query:
            primary_attachment_id = ExtendedRAGPipelineService._determine_primary_attachment(
                results, query, optimized
            )
            if primary_attachment_id:
                primary_content_length = ExtendedRAGPipelineService._get_primary_content_length(
                    max_content_length
                )
                rag_logger.info(
                    f"Primary attachment boost enabled: {primary_attachment_id}, "
                    f"budget={primary_content_length} (vs normal {content_length})"
                )
        
        rag_logger.info(f"Separating {len(results)} results into A/B/C layers")
        layer_a = []
        layer_b = []
        layer_c = []
        
        for result in results:
            obj_type = result.get('object_type', '')
            obj_id = str(result.get('object_id', ''))
            
            # Determine content length for this result (Issue #416)
            is_primary = (
                ENABLE_PRIMARY_ATTACHMENT_BOOST and
                obj_type == 'attachment' and
                obj_id == primary_attachment_id
            )
            
            result_content_length = primary_content_length if is_primary else content_length
            
            # Truncate content with smart trimming for primary attachments (Issue #416)
            content = result.get('content', '')
            original_length = len(content)
            
            if is_primary and original_length > SMALL_DOC_THRESHOLD:
                # Use section-aware smart trimming for large primary attachments
                rag_logger.info(
                    f"Applying smart section-aware trimming to primary attachment {obj_id}: "
                    f"{original_length} chars -> {result_content_length} max"
                )
                content = _smart_trim_markdown(content, result_content_length, query or '', optimized)
                rag_logger.info(f"Smart trimming result: {len(content)} chars")
            elif original_length > result_content_length:
                # Standard truncation
                content = content[:result_content_length].rstrip() + "..."
                if is_primary:
                    rag_logger.debug(f"Primary attachment {obj_id} truncated (small doc): {original_length} -> {len(content)} chars")
            elif is_primary:
                # Small doc, included in full
                rag_logger.debug(f"Primary attachment {obj_id} included in full: {original_length} chars (< {SMALL_DOC_THRESHOLD})")
            
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
            
            # Classify into layers (Issue #407: Documentation-centric)
            # Layer A: Attachments + GitHub PRs (highest technical relevance)
            if obj_type in {'attachment', 'github_pr'} and len(layer_a) < 3:
                layer_a.append(item)
            # Layer B: Items + GitHub Issues
            elif obj_type in {'item', 'github_issue'} and len(layer_b) < 3:
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
        
        rag_logger.info(f"Layer separation complete: A={len(layer_a)}, B={len(layer_b)}, C={len(layer_c)}")
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
        max_content_length: Optional[int] = None,
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
            item_id: DEPRECATED - No longer used (Issue #395)
            current_item_id: Optional current item ID to exclude from results (Issue #395)
            object_types: Optional object types filter (e.g., ["item", "github_issue", "github_pr", "file"]).
                         If None, defaults to ALLOWED_OBJECT_TYPES (item, github_issue, github_pr, file)
            user: Optional user for AI tracking
            client_ip: Optional client IP
            skip_optimization: Skip question optimization (use raw query)
            include_debug: Include debug information
            max_content_length: Optional max content length for truncation. If None, uses MAX_CONTENT_LENGTH from config
            
        Returns:
            ExtendedRAGContext with layered results
        """
        rag_logger.info("="*80)
        rag_logger.info(f"BUILD EXTENDED RAG CONTEXT - START")
        rag_logger.info(f"Query: {query[:100]}...")
        rag_logger.info(f"Filters: project_id={project_id}, current_item_id={current_item_id}")
        rag_logger.info(f"Options: skip_optimization={skip_optimization}, include_debug={include_debug}, max_content_length={max_content_length}")
        
        # Use provided max_content_length or default from config
        content_length = max_content_length if max_content_length is not None else MAX_CONTENT_LENGTH
        rag_logger.info(f"Using content_length={content_length}")
        
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
        rag_logger.info("STEP 1: Question Optimization")
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
        else:
            rag_logger.info("Question optimization skipped by request")
        
        # Fallback: use raw query if optimization failed
        if not optimized:
            logger.info("Question optimization failed or skipped, using raw query")
            rag_logger.info("Falling back to raw query (optimization failed or skipped)")
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
        rag_logger.info("STEP 2: Query Building")
        sem_query = ExtendedRAGPipelineService._build_semantic_query(optimized)
        kw_query = ExtendedRAGPipelineService._build_keyword_query(optimized)
        
        rag_logger.info(f"Semantic query: {sem_query[:80]}...")
        rag_logger.info(f"Keyword query: {kw_query[:80]}...")
        
        if include_debug:
            debug_info['queries'] = {
                'semantic': sem_query,
                'keyword': kw_query,
            }
        
        # Step 3: Parallel searches
        rag_logger.info("STEP 3: Parallel Searches")
        # Semantic/Hybrid search (alpha ≈ 0.6)
        rag_logger.info("Running semantic/hybrid search (alpha=0.6)...")
        sem_results = ExtendedRAGPipelineService._perform_search(
            query_text=sem_query,
            alpha=0.6,
            project_id=project_id,
            item_id=item_id,  # Deprecated but kept for backward compatibility
            current_item_id=current_item_id,
            object_types=object_types,
            limit=24,
        )
        stats['sem_results'] = len(sem_results)
        
        # Keyword/Tag search (alpha = 0.3 for more BM25/keyword weight)
        rag_logger.info("Running keyword/tag search (alpha=0.3)...")
        kw_results = ExtendedRAGPipelineService._perform_search(
            query_text=kw_query,
            alpha=0.3,  # Lower alpha = more BM25/keyword weight
            project_id=project_id,
            item_id=item_id,  # Deprecated but kept for backward compatibility
            current_item_id=current_item_id,
            object_types=object_types,
            limit=24,
        )
        stats['kw_results'] = len(kw_results)
        
        # Step 4: Fusion and reranking
        rag_logger.info("STEP 4: Fusion and Reranking")
        fused_results = ExtendedRAGPipelineService._fuse_and_rerank(
            sem_results=sem_results,
            kw_results=kw_results,
            item_id=item_id,  # Deprecated but kept for backward compatibility
            limit=6,
        )
        stats['fused_results'] = len(fused_results)
        
        # Step 5: Separate into A/B/C layers
        rag_logger.info("STEP 5: Layer Separation")
        layer_a, layer_b, layer_c = ExtendedRAGPipelineService._separate_into_layers(
            fused_results,
            item_id=item_id,  # Deprecated but kept for backward compatibility
            max_content_length=content_length,
            query=query,  # For primary attachment selection (Issue #416)
            optimized=optimized,  # For primary attachment selection (Issue #416)
        )
        
        stats['layer_a_count'] = len(layer_a)
        stats['layer_b_count'] = len(layer_b)
        stats['layer_c_count'] = len(layer_c)
        
        # Create all_items list
        all_items = layer_a + layer_b + layer_c
        
        # Generate summary
        total_items = len(all_items)
        summary = f"Retrieved {total_items} relevant items across {stats['layer_a_count']} thread-related, {stats['layer_b_count']} item-context, and {stats['layer_c_count']} background snippets."
        
        rag_logger.info("="*80)
        rag_logger.info(f"BUILD EXTENDED RAG CONTEXT - COMPLETE")
        rag_logger.info(f"Summary: {summary}")
        rag_logger.info(f"Stats: {stats}")
        rag_logger.info("="*80)
        
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


# Parameters that are not supported by ExtendedRAGPipelineService.build_extended_context()
# but may be passed by legacy callers. These are filtered out by the wrapper function.
_UNSUPPORTED_WRAPPER_PARAMS = frozenset({'max_results', 'enable_optimization'})


# Convenience function
def build_extended_context(**kwargs) -> ExtendedRAGContext:
    """
    Build extended RAG context with question optimization and A/B/C-layer bundling.
    
    Convenience wrapper around ExtendedRAGPipelineService.build_extended_context().
    See ExtendedRAGPipelineService.build_extended_context() for full documentation.
    
    Note: This wrapper filters out certain parameters to maintain compatibility with
    existing callers that may pass unsupported arguments. Specifically:
    - max_results: Not supported - the pipeline uses fixed limits internally (limit=24)
    - enable_optimization: Not supported - optimization is controlled by skip_optimization parameter
    
    These parameters are intentionally filtered (not just ignored) to prevent confusion
    about their actual effect on the pipeline behavior.
    """
    # Filter out parameters that are not accepted by the underlying service
    # These are legacy/misunderstood parameters that should not be passed through
    filtered_kwargs = {k: v for k, v in kwargs.items() if k not in _UNSUPPORTED_WRAPPER_PARAMS}
    
    return ExtendedRAGPipelineService.build_extended_context(**filtered_kwargs)
