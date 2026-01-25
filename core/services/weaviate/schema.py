"""
Weaviate schema management for Agira.

This module defines and manages the Weaviate schema (collections/classes)
for storing Agira context data.
"""

import logging
from weaviate.classes.config import Configure, Property, DataType
import weaviate

logger = logging.getLogger(__name__)

# Schema version for future upgrades
SCHEMA_VERSION = "v1"

# Collection name (fixed for v1)
COLLECTION_NAME = "AgiraObject"


def ensure_schema(client: weaviate.WeaviateClient) -> None:
    """
    Ensure the Weaviate schema exists, creating it if necessary.
    
    This function checks if the AgiraObject collection exists and creates it
    with the v1 schema if it doesn't exist.
    
    Args:
        client: Connected Weaviate client instance
        
    Example:
        >>> client = get_client()
        >>> ensure_schema(client)
        >>> client.close()
        
    Note:
        For future schema upgrades (v2):
        - Add a schema_version property to track versions
        - Implement migration logic to upgrade existing collections
        - Consider using Weaviate's collection.update() for non-breaking changes
    """
    # Check if collection already exists
    if client.collections.exists(COLLECTION_NAME):
        logger.debug(f"Collection '{COLLECTION_NAME}' already exists")
        return
    
    logger.info(f"Creating collection '{COLLECTION_NAME}' with schema {SCHEMA_VERSION}")
    
    # Create the AgiraObject collection with v1 schema
    client.collections.create(
        name=COLLECTION_NAME,
        properties=[
            # Required fields
            Property(
                name="type",
                data_type=DataType.TEXT,
                description="Type of object (e.g., item, comment, attachment, project, change, github_issue, github_pr)"
            ),
            Property(
                name="object_id",
                data_type=DataType.TEXT,
                description="ID of the Django object (PK/UUID as string)"
            ),
            Property(
                name="project_id",
                data_type=DataType.TEXT,
                description="Project ID for filtering (optional for org-only objects)",
                skip_vectorization=True
            ),
            Property(
                name="title",
                data_type=DataType.TEXT,
                description="Title or subject of the object"
            ),
            Property(
                name="text",
                data_type=DataType.TEXT,
                description="Semantic body content (RAG Content)"
            ),
            Property(
                name="created_at",
                data_type=DataType.DATE,
                description="Creation timestamp"
            ),
            Property(
                name="updated_at",
                data_type=DataType.DATE,
                description="Last update timestamp"
            ),
            # Optional/Recommended fields
            Property(
                name="org_id",
                data_type=DataType.TEXT,
                description="Organization ID (nullable)",
                skip_vectorization=True
            ),
            Property(
                name="status",
                data_type=DataType.TEXT,
                description="Status (e.g., item.status, change.status, github state)",
                skip_vectorization=True
            ),
            Property(
                name="url",
                data_type=DataType.TEXT,
                description="Internal UI route (e.g., /items/123/)",
                skip_vectorization=True
            ),
            Property(
                name="source_system",
                data_type=DataType.TEXT,
                description="Source system: agira|github|mail|zammad (default agira)",
                skip_vectorization=True
            ),
            Property(
                name="external_key",
                data_type=DataType.TEXT,
                description="External key (e.g., owner/repo#123 for GitHub)",
                skip_vectorization=True
            ),
            Property(
                name="parent_object_id",
                data_type=DataType.TEXT,
                description="Parent object ID (e.g., comment belongs to item)",
                skip_vectorization=True
            ),
            # Attachment metadata (optional)
            Property(
                name="mime_type",
                data_type=DataType.TEXT,
                description="MIME type for attachments",
                skip_vectorization=True
            ),
            Property(
                name="size_bytes",
                data_type=DataType.INT,
                description="File size in bytes for attachments"
            ),
            Property(
                name="sha256",
                data_type=DataType.TEXT,
                description="SHA256 hash for attachments",
                skip_vectorization=True
            ),
        ],
        # Use text2vec-transformers for semantic search
        # Note: Requires a vectorizer module to be configured in Weaviate
        # If using local Weaviate, you can configure transformers, openai, cohere, etc.
        # If no vectorizer is available, remove this parameter and Weaviate will use default
        # vectorizer_config can be omitted to use Weaviate's default configuration
    )
    
    logger.info(f"Collection '{COLLECTION_NAME}' created successfully")


def get_collection_name() -> str:
    """
    Get the name of the AgiraObject collection.
    
    Returns:
        Collection name string
    """
    return COLLECTION_NAME


def get_schema_version() -> str:
    """
    Get the current schema version.
    
    Returns:
        Schema version string (e.g., "v1")
    """
    return SCHEMA_VERSION
