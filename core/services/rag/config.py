"""
Configuration for RAG Pipeline Service.
"""

# Weaviate collection name (should match schema.py)
WEAVIATE_COLLECTION_NAME = "AgiraObject"

# Field mappings from Weaviate schema to RAG models
FIELD_MAPPING = {
    "object_id": "object_id",
    "object_type": "type",
    "title": "title",
    "content": "text",
    "link": "url",
    "project_id": "project_id",
    "item_id": "parent_object_id",  # parent_object_id may contain item_id for comments
    "updated_at": "updated_at",
    "source": "source_system",
}

# Default values
DEFAULT_LIMIT = 20
DEFAULT_ALPHA_KEYWORD = 0.2  # Low alpha = more BM25/keyword weight
DEFAULT_ALPHA_SEMANTIC = 0.7  # High alpha = more vector/semantic weight
DEFAULT_ALPHA_BALANCED = 0.5  # Balanced

# Content truncation
MAX_CONTENT_LENGTH = 600  # Maximum characters per content snippet

# Type priority for ranking (higher number = higher priority)
TYPE_PRIORITY = {
    "item": 6,
    "github_issue": 5,
    "github_pr": 5,
    "comment": 4,
    "change": 3,
    "attachment": 2,
    "project": 1,
}
