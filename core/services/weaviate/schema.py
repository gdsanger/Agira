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
COLLECTION_NAME = "AgiraContext"


def ensure_schema(client: weaviate.WeaviateClient) -> None:
    """
    Ensure the Weaviate schema exists, creating it if necessary.
    
    This function checks if the AgiraContext collection exists and creates it
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
    
    # Create the AgiraContext collection with v1 schema
    client.collections.create(
        name=COLLECTION_NAME,
        properties=[
            Property(
                name="source_type",
                data_type=DataType.TEXT,
                description="Type of source (e.g., item, item_comment, node, project, change)"
            ),
            Property(
                name="source_id",
                data_type=DataType.TEXT,
                description="Unique identifier from Postgres (UUID or int as string)"
            ),
            Property(
                name="project_id",
                data_type=DataType.TEXT,
                description="Project foreign key as string for filtering"
            ),
            Property(
                name="title",
                data_type=DataType.TEXT,
                description="Short title or subject"
            ),
            Property(
                name="text",
                data_type=DataType.TEXT,
                description="Main context text (Markdown allowed)"
            ),
            Property(
                name="tags",
                data_type=DataType.TEXT_ARRAY,
                description="Optional tags (e.g., bug, backend, security)",
                skip_vectorization=True  # Tags are for filtering, not semantic search
            ),
            Property(
                name="url",
                data_type=DataType.TEXT,
                description="Link to detail view in Agira",
                skip_vectorization=True  # URLs don't need vectorization
            ),
            Property(
                name="updated_at",
                data_type=DataType.DATE,
                description="Last update timestamp for sync/refresh"
            ),
        ],
        # Configure vectorizer - using default text2vec for semantic search
        vectorizer_config=Configure.Vectorizer.text2vec_contextionary(),
    )
    
    logger.info(f"Collection '{COLLECTION_NAME}' created successfully")


def get_collection_name() -> str:
    """
    Get the name of the AgiraContext collection.
    
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
