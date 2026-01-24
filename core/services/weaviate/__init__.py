"""
Weaviate service package for Agira.

This package provides integration with Weaviate vector database for:
- Storing context data from various Agira sources
- Semantic search and retrieval for AI agents
- Future features like AI chat, auto-triage, suggestions, Q&A

Public API:
- upsert_document: Store or update a context document
- delete_document: Remove a context document
- query: Search documents semantically
- is_available: Check if Weaviate is configured and enabled

Example:
    >>> from core.services.weaviate import upsert_document, query
    >>> 
    >>> # Store a document
    >>> doc_id = upsert_document(
    ...     source_type="item",
    ...     source_id="123",
    ...     project_id="proj-1",
    ...     title="Bug in login",
    ...     text="Users cannot log in",
    ...     tags=["bug"]
    ... )
    >>> 
    >>> # Query documents
    >>> results = query(
    ...     project_id="proj-1",
    ...     query_text="login issues",
    ...     top_k=5
    ... )
"""

from core.services.weaviate.service import (
    upsert_document,
    delete_document,
    query,
)
from core.services.weaviate.client import is_available

__all__ = [
    "upsert_document",
    "delete_document",
    "query",
    "is_available",
]
