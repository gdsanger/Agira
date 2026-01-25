"""
Weaviate service package for Agira.

This package provides integration with Weaviate vector database for:
- Storing context data from various Agira sources
- Semantic search and retrieval for AI agents
- Future features like AI chat, auto-triage, suggestions, Q&A

Public API:
- make_weaviate_uuid: Generate deterministic UUID for an object
- ensure_schema: Ensure AgiraObject collection exists
- upsert_object: Upsert object by type and ID
- delete_object: Delete object by type and ID
- upsert_instance: Upsert a Django model instance
- sync_project: Sync all objects for a project
- upsert_document: Store or update a context document (legacy)
- delete_document: Remove a context document (legacy)
- query: Search documents semantically
- is_available: Check if Weaviate is configured and enabled

Example:
    >>> from core.services.weaviate import upsert_instance, query
    >>> 
    >>> # Store a Django object
    >>> from core.models import Item
    >>> item = Item.objects.get(pk=1)
    >>> uuid_str = upsert_instance(item)
    >>> 
    >>> # Query documents
    >>> results = query(
    ...     project_id="1",
    ...     query_text="login issues",
    ...     top_k=5
    ... )
"""

from core.services.weaviate.service import (
    make_weaviate_uuid,
    ensure_schema,
    upsert_object,
    delete_object,
    upsert_instance,
    sync_project,
    upsert_document,
    delete_document,
    query,
)
from core.services.weaviate.client import is_available, get_client
from core.services.weaviate.serializers import to_agira_object

__all__ = [
    "make_weaviate_uuid",
    "ensure_schema",
    "upsert_object",
    "delete_object",
    "upsert_instance",
    "sync_project",
    "upsert_document",
    "delete_document",
    "query",
    "is_available",
    "get_client",
    "to_agira_object",
]

