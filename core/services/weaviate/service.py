"""
Weaviate service layer for Agira.

This module provides high-level APIs for storing, querying, and deleting
context documents in Weaviate for semantic search and AI agent retrieval.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any

import weaviate
from weaviate.classes.query import Filter

from core.services.weaviate.client import get_client
from core.services.weaviate.schema import ensure_schema, COLLECTION_NAME

logger = logging.getLogger(__name__)

# Cache flag to avoid calling ensure_schema on every operation
_schema_ensured = False

# Namespace for deterministic UUID5 generation
UUID_NAMESPACE = uuid.UUID("a9c5e8d0-1234-5678-9abc-def012345678")


def _get_deterministic_uuid(source_type: str, source_id: str) -> uuid.UUID:
    """
    Generate a deterministic UUID5 based on source_type and source_id.
    
    This ensures idempotent upserts - the same source always maps to the
    same Weaviate object UUID.
    
    Args:
        source_type: Type of the source (e.g., "item", "node")
        source_id: Unique identifier of the source
        
    Returns:
        Deterministic UUID
    """
    # Create a stable string representation
    stable_key = f"{source_type}:{source_id}"
    return uuid.uuid5(UUID_NAMESPACE, stable_key)


def _ensure_schema_once(client: weaviate.WeaviateClient) -> None:
    """
    Ensure schema exists, but only check once per process.
    
    Args:
        client: Connected Weaviate client
    """
    global _schema_ensured
    if not _schema_ensured:
        ensure_schema(client)
        _schema_ensured = True


def upsert_document(
    source_type: str,
    source_id: str | int,
    project_id: str | int,
    title: str,
    text: str,
    tags: Optional[List[str]] = None,
    url: Optional[str] = None,
    updated_at: Optional[datetime] = None,
) -> str:
    """
    Upsert a document into Weaviate.
    
    This operation is idempotent - calling it multiple times with the same
    source_type and source_id will update the existing document.
    
    Args:
        source_type: Type of source (e.g., "item", "item_comment", "node")
        source_id: Unique identifier from Postgres (UUID or int)
        project_id: Project foreign key for filtering
        title: Short title or subject
        text: Main content text (Markdown allowed)
        tags: Optional list of tags (e.g., ["bug", "backend"])
        url: Optional URL to detail view in Agira
        updated_at: Last update timestamp (defaults to now)
        
    Returns:
        Weaviate object UUID as string
        
    Raises:
        ServiceDisabled: If Weaviate is not enabled
        ServiceNotConfigured: If Weaviate configuration is incomplete
        
    Example:
        >>> obj_id = upsert_document(
        ...     source_type="item",
        ...     source_id="123",
        ...     project_id="proj-1",
        ...     title="Bug in login",
        ...     text="Users cannot log in with special characters",
        ...     tags=["bug", "security"],
        ...     url="/items/123"
        ... )
    """
    # Convert IDs to strings
    source_id_str = str(source_id)
    project_id_str = str(project_id)
    
    # Generate deterministic UUID
    obj_uuid = _get_deterministic_uuid(source_type, source_id_str)
    
    # Default updated_at to now if not provided
    if updated_at is None:
        updated_at = datetime.now()
    
    # Get client and ensure schema
    client = get_client()
    try:
        _ensure_schema_once(client)
        
        # Get collection
        collection = client.collections.get(COLLECTION_NAME)
        
        # Prepare properties
        properties = {
            "source_type": source_type,
            "source_id": source_id_str,
            "project_id": project_id_str,
            "title": title,
            "text": text,
            "updated_at": updated_at,
        }
        
        # Add optional properties
        if tags is not None:
            properties["tags"] = tags
        if url is not None:
            properties["url"] = url
        
        # Upsert using deterministic UUID
        # This will insert if not exists, or update if exists
        collection.data.insert(
            properties=properties,
            uuid=obj_uuid,
        )
        
        logger.debug(
            f"Upserted document: {source_type}:{source_id_str} -> {obj_uuid}"
        )
        
        return str(obj_uuid)
        
    finally:
        client.close()


def delete_document(source_type: str, source_id: str | int) -> bool:
    """
    Delete a document from Weaviate.
    
    Args:
        source_type: Type of source
        source_id: Unique identifier of the source
        
    Returns:
        True if document was deleted, False if it didn't exist
        
    Raises:
        ServiceDisabled: If Weaviate is not enabled
        ServiceNotConfigured: If Weaviate configuration is incomplete
        
    Example:
        >>> deleted = delete_document("item", "123")
        >>> if deleted:
        ...     print("Document deleted")
    """
    # Convert ID to string
    source_id_str = str(source_id)
    
    # Generate deterministic UUID
    obj_uuid = _get_deterministic_uuid(source_type, source_id_str)
    
    # Get client
    client = get_client()
    try:
        # Get collection
        collection = client.collections.get(COLLECTION_NAME)
        
        # Try to delete
        try:
            collection.data.delete_by_id(obj_uuid)
            logger.debug(f"Deleted document: {source_type}:{source_id_str}")
            return True
        except Exception as e:
            # Object might not exist
            logger.debug(
                f"Could not delete {source_type}:{source_id_str} (might not exist): {e}"
            )
            return False
            
    finally:
        client.close()


def query(
    project_id: str | int,
    query_text: str,
    top_k: int = 10,
    filters: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Query documents using semantic search.
    
    Args:
        project_id: Project ID to filter by (required)
        query_text: Search query text
        top_k: Maximum number of results to return
        filters: Optional additional filters (e.g., {"source_type": "item"})
        
    Returns:
        List of matching documents with metadata:
        - source_type: Type of the source
        - source_id: ID of the source
        - title: Document title
        - text_preview: First 200 characters of text
        - url: URL to detail view (if available)
        - score: Relevance score/distance
        
    Raises:
        ServiceDisabled: If Weaviate is not enabled
        ServiceNotConfigured: If Weaviate configuration is incomplete
        
    Example:
        >>> results = query(
        ...     project_id="proj-1",
        ...     query_text="login bug",
        ...     top_k=5,
        ...     filters={"source_type": "item"}
        ... )
        >>> for result in results:
        ...     print(f"{result['title']}: {result['score']}")
    """
    # Convert project_id to string
    project_id_str = str(project_id)
    
    # Get client and ensure schema
    client = get_client()
    try:
        _ensure_schema_once(client)
        
        # Get collection
        collection = client.collections.get(COLLECTION_NAME)
        
        # Build filter for project_id
        where_filter = Filter.by_property("project_id").equal(project_id_str)
        
        # Add additional filters if provided
        if filters:
            for key, value in filters.items():
                where_filter = where_filter & Filter.by_property(key).equal(str(value))
        
        # Execute semantic search
        response = collection.query.near_text(
            query=query_text,
            limit=top_k,
            where=where_filter,
        )
        
        # Format results
        results = []
        for obj in response.objects:
            props = obj.properties
            
            # Create text preview (first 200 chars)
            text = props.get("text", "")
            text_preview = text[:200] + "..." if len(text) > 200 else text
            
            result = {
                "source_type": props.get("source_type"),
                "source_id": props.get("source_id"),
                "title": props.get("title"),
                "text_preview": text_preview,
                "url": props.get("url"),
                "score": obj.metadata.distance if hasattr(obj.metadata, 'distance') else None,
            }
            results.append(result)
        
        logger.debug(
            f"Query '{query_text}' in project {project_id_str} returned {len(results)} results"
        )
        
        return results
        
    finally:
        client.close()
