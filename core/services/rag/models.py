"""
Data models for RAG Pipeline responses.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RAGContextObject:
    """
    A single context object from the RAG pipeline.
    
    Attributes:
        object_type: Type of object (item, comment, github_issue, etc.)
        object_id: Unique identifier of the object
        title: Title or subject of the object
        content: Main content text (truncated/snippet)
        source: Source system (agira, github, etc.)
        relevance_score: Relevance score from search (0-1, higher is better)
        link: URL/link to the object
        updated_at: Last update timestamp as string
    """
    object_type: str
    object_id: str
    title: Optional[str]
    content: str
    source: Optional[str]
    relevance_score: Optional[float]
    link: Optional[str]
    updated_at: Optional[str]


@dataclass
class RAGContext:
    """
    Complete RAG context response for AI agents.
    
    Attributes:
        query: The original search query
        alpha: Hybrid search alpha value used (0-1, higher = more vector weight)
        summary: Human-readable summary of results
        items: List of context objects
        stats: Statistics about the results
        debug: Optional debug information (only if include_debug=True)
    """
    query: str
    alpha: float
    summary: str
    items: list[RAGContextObject]
    stats: dict = field(default_factory=dict)
    debug: Optional[dict] = None
    
    def to_context_text(self) -> str:
        """
        Generate agent-friendly context text from the results.
        
        Returns:
            Formatted context text with sections for context and sources
        """
        lines = ["[CONTEXT]"]
        
        for idx, item in enumerate(self.items, 1):
            # Build header line
            score_str = f"score={item.relevance_score:.2f}" if item.relevance_score else "score=N/A"
            header = f"{idx}) (type={item.object_type} {score_str})"
            
            # Add title if available
            if item.title:
                header += f" Title: {item.title}"
            
            lines.append(header)
            
            # Add link if available
            if item.link:
                lines.append(f"   Link: {item.link}")
            
            # Add content snippet
            lines.append(f"   Snippet: {item.content}")
            
            # Empty line between items (except last)
            if idx < len(self.items):
                lines.append("")
        
        lines.append("[/CONTEXT]")
        lines.append("")
        lines.append("[SOURCES]")
        
        # Add sources
        for item in self.items:
            source_line = f"- {item.object_type}:{item.object_id}"
            if item.link:
                source_line += f" -> {item.link}"
            lines.append(source_line)
        
        lines.append("[/SOURCES]")
        
        return "\n".join(lines)
