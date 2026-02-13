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

# Deduplication
DEDUP_FETCH_MULTIPLIER = 2  # Fetch this many times limit for deduplication

# Allowed object types for RAG search (based on Issue #392)
# Only search in: Item, GitHub Issues, GitHubPRs, and Files (not Comments)
ALLOWED_OBJECT_TYPES = [
    "item",
    "github_issue",
    "github_pr",
    "attachment",
]

# Type priority for ranking (higher number = higher priority)
# Note: Even though ALLOWED_OBJECT_TYPES excludes some types (like comment, change, etc.),
# we keep all priorities here for:
# 1. Custom searches that override object_types
# 2. Backward compatibility with existing code
# 3. Future flexibility
TYPE_PRIORITY = {
    "item": 6,
    "attachment": 5,    
    "github_pr": 5,    
    "github_issue": 4,
    "comment": 3,    
    "change": 2,
    "file": 1,
    "project": 0,
}
