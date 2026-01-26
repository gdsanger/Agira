"""
Weaviate service layer for Agira.

This module provides high-level APIs for storing, querying, and deleting
context documents in Weaviate for semantic search and AI agent retrieval.
"""

import logging
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

import weaviate
from weaviate.classes.query import Filter, HybridFusion, MetadataQuery

from core.services.weaviate.client import get_client
from core.services.weaviate.schema import ensure_schema as _ensure_schema_internal, COLLECTION_NAME

logger = logging.getLogger(__name__)

# Cache flag to avoid calling ensure_schema on every operation
_schema_ensured = False

# Namespace for deterministic UUID5 generation
UUID_NAMESPACE = uuid.UUID("a9c5e8d0-1234-5678-9abc-def012345678")

# Maximum distance value for near_text queries (Weaviate cosine distance typically 0-2)
# Used for converting distance to normalized score (0-1 range)
MAX_DISTANCE = 2.0

# Metadata query configurations for Weaviate queries
# For vector/semantic searches, request both score and distance
VECTOR_METADATA_QUERY = MetadataQuery(score=True, distance=True)
# For hybrid/keyword searches, only score is available
HYBRID_METADATA_QUERY = MetadataQuery(score=True)


@dataclass
class AgiraSearchHit:
    """Data transfer object for global search results."""
    type: str
    title: str
    url: Optional[str] = None
    object_id: Optional[str] = None
    project_id: Optional[str] = None
    score: Optional[float] = None
    updated_at: Optional[datetime] = None
    status: Optional[str] = None
    external_key: Optional[str] = None


def make_weaviate_uuid(type: str, object_id: str) -> str:
    """
    Generate a deterministic UUID5 based on type and object_id.
    
    This ensures idempotent upserts - the same object always maps to the
    same Weaviate UUID. This is the public API version of the helper.
    
    Args:
        type: Type of the object (e.g., "item", "comment")
        object_id: Unique identifier of the object
        
    Returns:
        Deterministic UUID as string
        
    Example:
        >>> uuid_str = make_weaviate_uuid("item", "123")
        >>> # Same input always returns same UUID
        >>> assert uuid_str == make_weaviate_uuid("item", "123")
    """
    stable_key = f"{type}:{object_id}"
    return str(uuid.uuid5(UUID_NAMESPACE, stable_key))


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
        _ensure_schema_internal(client)
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
        # Weaviate v4: Use replace() to update if exists, insert if not
        try:
            collection.data.replace(
                properties=properties,
                uuid=obj_uuid,
            )
        except Exception:
            # If replace fails (object doesn't exist), insert it
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
            return_metadata=VECTOR_METADATA_QUERY,
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
                # Get score from metadata (Weaviate v4 returns score or distance)
                # Use explicit None check to handle score=0 as a valid value
                "score": (score := getattr(obj.metadata, 'score', None)) if score is not None else getattr(obj.metadata, 'distance', None),
            }
            results.append(result)
        
        logger.debug(
            f"Query '{query_text}' in project {project_id_str} returned {len(results)} results"
        )
        
        return results
        
    finally:
        client.close()


def global_search(
    query: str,
    *,
    limit: int = 25,
    alpha: float = 0.5,
    filters: Optional[Dict[str, Any]] = None,
    mode: str = 'hybrid',
) -> List[AgiraSearchHit]:
    """
    Perform global search using Weaviate search.
    
    This function searches across all AgiraObject instances using different
    search modes: hybrid (BM25 + Vector), semantic (vector only), or keyword (BM25 only).
    
    Args:
        query: Search query text (minimum 2 characters recommended)
        limit: Maximum number of results to return (default: 25)
        alpha: Balance between BM25 and vector search (0.0 = BM25 only, 1.0 = vector only, default: 0.5)
        filters: Optional filters (e.g., {"type": "item", "project_id": "123"})
        mode: Search mode - 'hybrid' (default), 'similar' (semantic/vector), or 'keyword' (BM25)
        
    Returns:
        List of AgiraSearchHit objects with search results
        
    Raises:
        Exception: If Weaviate is not available or configured
        
    Example:
        >>> results = global_search("login bug", limit=10)
        >>> for hit in results:
        ...     print(f"{hit.type}: {hit.title} (score: {hit.score})")
        
        >>> # Filter by type
        >>> results = global_search("API", filters={"type": "item"})
        
        >>> # Semantic search only
        >>> results = global_search("authentication issues", mode="similar")
        
        >>> # Keyword search only
        >>> results = global_search("bug #123", mode="keyword")
    """
    # Get client and ensure schema
    client = get_client()
    try:
        _ensure_schema_once(client)
        
        # Get collection
        collection = client.collections.get(COLLECTION_NAME)
        
        # Build filter if provided
        where_filter = None
        if filters:
            filter_conditions = []
            for key, value in filters.items():
                filter_conditions.append(Filter.by_property(key).equal(str(value)))
            
            # Combine filters with AND
            if len(filter_conditions) == 1:
                where_filter = filter_conditions[0]
            else:
                where_filter = filter_conditions[0]
                for condition in filter_conditions[1:]:
                    where_filter = where_filter & condition
        
        # Execute search based on mode
        # Note: The collection is configured with vectorizer set to 'none', so:
        # - 'hybrid' mode: Uses BM25 keyword matching (vectorizer='none' means no vector component)
        # - 'similar' mode: Attempts near_text but falls back to BM25 if no vectorizer configured
        # - 'keyword' mode: Pure BM25 keyword search
        # For full semantic/vector search, configure a vectorizer (e.g., text2vec-transformers) in the schema.
        # Using RELATIVE_SCORE fusion ensures consistent score calculation for ranking.
        
        try:
            if mode == 'similar':
                # Semantic/vector search (near_text)
                # Note: This requires a configured vectorizer. With vectorizer='none',
                # Weaviate may return an error or fall back to keyword search.
                # We handle this gracefully by catching errors and falling back to hybrid search.
                try:
                    response = collection.query.near_text(
                        query=query,
                        limit=limit,
                        where=where_filter,
                        return_metadata=VECTOR_METADATA_QUERY,
                    )
                except (AttributeError, ValueError, RuntimeError) as e:
                    # Catch specific errors related to missing vectorizer or invalid query
                    logger.warning(
                        f"near_text query failed (vectorizer may not be configured), "
                        f"falling back to hybrid search: {type(e).__name__}: {e}"
                    )
                    # Fall back to hybrid search if near_text fails
                    response = collection.query.hybrid(
                        query=query,
                        limit=limit,
                        alpha=alpha,
                        filters=where_filter,
                        fusion_type=HybridFusion.RELATIVE_SCORE,
                        return_metadata=HYBRID_METADATA_QUERY,
                    )
            elif mode == 'keyword':
                # Pure BM25 keyword search (alpha=0 means BM25 only)
                response = collection.query.hybrid(
                    query=query,
                    limit=limit,
                    alpha=0.0,  # Pure BM25
                    filters=where_filter,
                    fusion_type=HybridFusion.RELATIVE_SCORE,
                    return_metadata=HYBRID_METADATA_QUERY,
                )
            else:
                # Hybrid search (default) - combines BM25 and vector
                response = collection.query.hybrid(
                    query=query,
                    limit=limit,
                    alpha=alpha,
                    filters=where_filter,
                    fusion_type=HybridFusion.RELATIVE_SCORE,
                    return_metadata=HYBRID_METADATA_QUERY,
                )
        except Exception as e:
            # Log and re-raise unexpected errors
            logger.error(f"Search query failed with unexpected error: {type(e).__name__}: {e}")
            raise
        
        # Format results as AgiraSearchHit objects
        results = []
        for obj in response.objects:
            props = obj.properties
            
            # Get score from metadata (different attributes for different query types)
            score = None
            if hasattr(obj.metadata, 'score'):
                score = obj.metadata.score
            elif hasattr(obj.metadata, 'distance'):
                # For near_text queries, distance is available (cosine distance)
                # Convert distance to normalized score (0-1 range)
                # Lower distance = higher similarity = higher score
                # Ensure distance stays within valid range even in edge cases
                distance = obj.metadata.distance
                if distance is not None:
                    # Clamp distance to [0, MAX_DISTANCE] before conversion
                    normalized_distance = min(distance / MAX_DISTANCE, 1.0)
                    score = max(0.0, 1.0 - normalized_distance)
            
            hit = AgiraSearchHit(
                type=props.get("type", "unknown"),
                title=props.get("title", "Untitled"),
                url=props.get("url"),
                object_id=props.get("object_id"),
                project_id=props.get("project_id"),
                score=score,
                updated_at=props.get("updated_at"),
                status=props.get("status"),
                external_key=props.get("external_key"),
            )
            results.append(hit)
        
        # Sort results by score descending (highest relevance first)
        # Use 0 as fallback for None scores (represents no relevance)
        results.sort(key=lambda x: x.score if x.score is not None else 0, reverse=True)
        
        logger.debug(
            f"Global search ({mode}) for '{query}' returned {len(results)} results"
        )
        
        return results
        
    finally:
        client.close()


def ensure_schema() -> None:
    """
    Ensure the Weaviate schema exists, creating it if necessary.
    
    This is a convenience wrapper that gets a client, ensures the schema,
    and closes the client.
    
    Raises:
        ServiceDisabled: If Weaviate is not enabled
        ServiceNotConfigured: If Weaviate configuration is incomplete
        
    Example:
        >>> from core.services.weaviate.service import ensure_schema
        >>> ensure_schema()  # Creates AgiraObject collection if needed
    """
    client = get_client()
    try:
        _ensure_schema_internal(client)
    finally:
        client.close()


def upsert_object(type: str, object_id: str) -> Optional[str]:
    """
    Upsert an object into Weaviate by loading it from Django and serializing.
    
    This method loads the Django object by type and ID, serializes it using
    the appropriate serializer, and upserts it into Weaviate.
    
    For GitHub issues/PRs (ExternalIssueMapping), this will fetch fresh data
    from the GitHub API to ensure the most up-to-date content is indexed.
    
    Args:
        type: Type of object (e.g., "item", "comment", "project", "github_issue", "github_pr")
        object_id: Django object ID (as string)
        
    Returns:
        Weaviate object UUID as string, or None if object not found or unsupported
        
    Raises:
        ServiceDisabled: If Weaviate is not enabled
        ServiceNotConfigured: If Weaviate configuration is incomplete
        
    Example:
        >>> uuid_str = upsert_object("item", "123")
        >>> if uuid_str:
        ...     print(f"Upserted with UUID: {uuid_str}")
    """
    from core.services.weaviate.serializers import to_agira_object
    
    # Load the Django object
    instance = _load_django_object(type, object_id)
    if instance is None:
        logger.warning(f"Object not found: {type}:{object_id}")
        return None
    
    # For GitHub issues/PRs, fetch fresh data from GitHub API
    fetch_from_github = type in ('github_issue', 'github_pr')
    
    # Serialize to AgiraObject dict
    obj_dict = to_agira_object(instance, fetch_from_github=fetch_from_github)
    if obj_dict is None:
        logger.warning(f"Could not serialize object: {type}:{object_id}")
        return None
    
    # Upsert using the new schema
    return _upsert_agira_object(obj_dict)


def delete_object(type: str, object_id: str) -> bool:
    """
    Delete an object from Weaviate using deterministic UUID.
    
    Args:
        type: Type of object (e.g., "item", "comment")
        object_id: Django object ID (as string)
        
    Returns:
        True if object was deleted, False if it didn't exist
        
    Raises:
        ServiceDisabled: If Weaviate is not enabled
        ServiceNotConfigured: If Weaviate configuration is incomplete
        
    Example:
        >>> deleted = delete_object("item", "123")
        >>> if deleted:
        ...     print("Object deleted from Weaviate")
    """
    # Convert to string and use deterministic UUID
    object_id_str = str(object_id)
    obj_uuid = _get_deterministic_uuid(type, object_id_str)
    
    # Get client
    client = get_client()
    try:
        # Get collection
        collection = client.collections.get(COLLECTION_NAME)
        
        # Try to delete
        try:
            collection.data.delete_by_id(obj_uuid)
            logger.debug(f"Deleted object: {type}:{object_id_str}")
            return True
        except Exception as e:
            # Object might not exist
            logger.debug(
                f"Could not delete {type}:{object_id_str} (might not exist): {e}"
            )
            return False
            
    finally:
        client.close()


def upsert_instance(instance, fetch_from_github: bool = False) -> Optional[str]:
    """
    Upsert a Django model instance into Weaviate.
    
    This method automatically detects the type from the instance's model class,
    serializes it, and upserts it into Weaviate.
    
    Args:
        instance: Django model instance (Item, Comment, Project, etc.)
        fetch_from_github: For ExternalIssueMapping, fetch fresh data from GitHub API
        
    Returns:
        Weaviate object UUID as string, or None if unsupported type
        
    Raises:
        ServiceDisabled: If Weaviate is not enabled
        ServiceNotConfigured: If Weaviate configuration is incomplete
        
    Example:
        >>> from core.models import Item
        >>> item = Item.objects.get(pk=1)
        >>> uuid_str = upsert_instance(item)
    """
    from core.services.weaviate.serializers import to_agira_object
    
    # Serialize to AgiraObject dict
    obj_dict = to_agira_object(instance, fetch_from_github=fetch_from_github)
    if obj_dict is None:
        logger.warning(f"Could not serialize instance: {instance.__class__.__name__} (pk={instance.pk})")
        return None
    
    # Upsert using the new schema
    return _upsert_agira_object(obj_dict)


def sync_project(project_id: str | int) -> Dict[str, int]:
    """
    Synchronize all objects for a project to Weaviate.
    
    This method loads all items, comments, changes, etc. for a project
    and upserts them into Weaviate.
    
    Args:
        project_id: Project ID to sync
        
    Returns:
        Dictionary with counts of synced objects by type
        
    Raises:
        ServiceDisabled: If Weaviate is not enabled
        ServiceNotConfigured: If Weaviate configuration is incomplete
        
    Example:
        >>> stats = sync_project("1")
        >>> print(f"Synced {stats['item']} items, {stats['comment']} comments")
    """
    from core.models import Item, ItemComment, Change, Node, Release
    from core.services.weaviate.serializers import to_agira_object
    
    project_id_str = str(project_id)
    stats = {
        'item': 0,
        'comment': 0,
        'change': 0,
        'node': 0,
        'release': 0,
    }
    
    logger.info(f"Starting sync for project {project_id_str}")
    
    # Sync items
    for item in Item.objects.filter(project_id=project_id_str):
        if upsert_instance(item):
            stats['item'] += 1
    
    # Sync comments (via items)
    for comment in ItemComment.objects.filter(item__project_id=project_id_str):
        if upsert_instance(comment):
            stats['comment'] += 1
    
    # Sync changes
    for change in Change.objects.filter(project_id=project_id_str):
        if upsert_instance(change):
            stats['change'] += 1
    
    # Sync nodes
    for node in Node.objects.filter(project_id=project_id_str):
        if upsert_instance(node):
            stats['node'] += 1
    
    # Sync releases
    for release in Release.objects.filter(project_id=project_id_str):
        if upsert_instance(release):
            stats['release'] += 1
    
    logger.info(f"Completed sync for project {project_id_str}: {stats}")
    return stats


def _load_django_object(type: str, object_id: str):
    """
    Load a Django object by type and ID.
    
    Args:
        type: Type string (e.g., "item", "comment")
        object_id: Object ID as string
        
    Returns:
        Django model instance or None if not found
    """
    from core.models import (
        Item, ItemComment, Attachment, Project, Change,
        Node, Release, ExternalIssueMapping
    )
    
    type_model_map = {
        'item': Item,
        'comment': ItemComment,
        'attachment': Attachment,
        'project': Project,
        'change': Change,
        'node': Node,
        'release': Release,
        'github_issue': ExternalIssueMapping,
        'github_pr': ExternalIssueMapping,
    }
    
    model_class = type_model_map.get(type)
    if model_class is None:
        logger.warning(f"Unknown type: {type}")
        return None
    
    try:
        return model_class.objects.get(pk=object_id)
    except model_class.DoesNotExist:
        return None
    except Exception as e:
        logger.error(f"Error loading {type}:{object_id}: {e}")
        return None


def get_weaviate_type(instance) -> Optional[str]:
    """
    Get the Weaviate type string for a Django model instance.
    
    This is the public API version that uses the serializer's type mapping.
    
    Args:
        instance: Django model instance
        
    Returns:
        Type string (e.g., "item", "comment") or None if unsupported
        
    Example:
        >>> from core.models import Item
        >>> item = Item.objects.get(pk=1)
        >>> type_str = get_weaviate_type(item)
        >>> # Returns "item"
    """
    from core.services.weaviate.serializers import _get_model_type
    return _get_model_type(instance)


def exists_instance(instance) -> bool:
    """
    Check if a Django model instance exists in Weaviate.
    
    Args:
        instance: Django model instance (Item, Comment, Project, etc.)
        
    Returns:
        True if object exists in Weaviate, False otherwise
        
    Example:
        >>> from core.models import Item
        >>> item = Item.objects.get(pk=1)
        >>> if exists_instance(item):
        ...     print("Item is synced to Weaviate")
    """
    obj_type = get_weaviate_type(instance)
    if obj_type is None:
        return False
    
    return exists_object(obj_type, str(instance.pk))


def exists_object(type: str, object_id: str) -> bool:
    """
    Check if an object exists in Weaviate using deterministic UUID.
    
    Args:
        type: Type of object (e.g., "item", "comment")
        object_id: Django object ID (as string)
        
    Returns:
        True if object exists in Weaviate, False otherwise
        
    Example:
        >>> exists = exists_object("item", "123")
        >>> if exists:
        ...     print("Object exists in Weaviate")
    """
    # Convert to string and use deterministic UUID
    object_id_str = str(object_id)
    obj_uuid = _get_deterministic_uuid(type, object_id_str)
    
    # Get client
    client = get_client()
    try:
        # Get collection
        collection = client.collections.get(COLLECTION_NAME)
        
        # Try to fetch object by UUID
        try:
            obj = collection.query.fetch_object_by_id(obj_uuid)
            return obj is not None
        except Exception:
            # Object doesn't exist or other error
            return False
            
    except Exception as e:
        # Weaviate might not be configured or available
        logger.debug(f"Error checking existence of {type}:{object_id_str}: {e}")
        return False
    finally:
        try:
            client.close()
        except Exception:
            pass


def fetch_object(instance) -> Optional[Dict[str, Any]]:
    """
    Fetch the Weaviate object data for a Django model instance.
    
    Args:
        instance: Django model instance (Item, Comment, Project, etc.)
        
    Returns:
        Dictionary with object properties and UUID, or None if not found
        
    Example:
        >>> from core.models import Item
        >>> item = Item.objects.get(pk=1)
        >>> obj_data = fetch_object(item)
        >>> if obj_data:
        ...     print(obj_data['title'], obj_data['uuid'])
    """
    obj_type = get_weaviate_type(instance)
    if obj_type is None:
        return None
    
    return fetch_object_by_type(obj_type, str(instance.pk))


def fetch_object_by_type(type: str, object_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch an object from Weaviate using type and ID.
    
    Args:
        type: Type of object (e.g., "item", "comment")
        object_id: Django object ID (as string)
        
    Returns:
        Dictionary with object properties and UUID, or None if not found
        
    Example:
        >>> obj_data = fetch_object_by_type("item", "123")
        >>> if obj_data:
        ...     print(obj_data)
    """
    # Convert to string and use deterministic UUID
    object_id_str = str(object_id)
    obj_uuid = _get_deterministic_uuid(type, object_id_str)
    
    # Get client
    client = get_client()
    try:
        _ensure_schema_once(client)
        
        # Get collection
        collection = client.collections.get(COLLECTION_NAME)
        
        # Try to fetch object by UUID
        try:
            obj = collection.query.fetch_object_by_id(obj_uuid)
            if obj is None:
                return None
            
            # Convert to dict with UUID
            result = dict(obj.properties)
            result['uuid'] = str(obj.uuid)
            return result
            
        except Exception as e:
            logger.debug(f"Could not fetch {type}:{object_id_str}: {e}")
            return None
            
    except Exception as e:
        logger.error(f"Error fetching object {type}:{object_id_str}: {e}")
        return None
    finally:
        try:
            client.close()
        except Exception:
            pass


def _upsert_agira_object(obj_dict: Dict[str, Any]) -> str:
    """
    Upsert an AgiraObject dictionary into Weaviate.
    
    Args:
        obj_dict: Dictionary with AgiraObject properties
        
    Returns:
        Weaviate object UUID as string
    """
    # Extract required fields
    obj_type = obj_dict['type']
    object_id = str(obj_dict['object_id'])
    
    # Generate deterministic UUID
    obj_uuid = _get_deterministic_uuid(obj_type, object_id)
    
    # Get client and ensure schema
    client = get_client()
    try:
        _ensure_schema_once(client)
        
        # Get collection
        collection = client.collections.get(COLLECTION_NAME)
        
        # Prepare properties (filter out None values for optional fields)
        properties = {k: v for k, v in obj_dict.items() if v is not None}
        
        # Ensure datetime objects are present
        if 'created_at' not in properties or properties['created_at'] is None:
            properties['created_at'] = datetime.now()
        if 'updated_at' not in properties or properties['updated_at'] is None:
            properties['updated_at'] = datetime.now()
        
        # Upsert using deterministic UUID
        try:
            collection.data.replace(
                properties=properties,
                uuid=obj_uuid,
            )
        except Exception:
            # If replace fails (object doesn't exist), insert it
            collection.data.insert(
                properties=properties,
                uuid=obj_uuid,
            )
        
        logger.debug(
            f"Upserted AgiraObject: {obj_type}:{object_id} -> {obj_uuid}"
        )
        
        return str(obj_uuid)
        
    finally:
        client.close()

