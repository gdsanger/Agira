# RAG Pipeline Service

The RAG (Retrieval-Augmented Generation) Pipeline is a core service in Agira that provides hybrid search capabilities over structured Agira data stored in Weaviate.

## Purpose

This service is designed to be a **context provider** for AI agents (e.g., `github-issue-creation-agent`). It performs semantic and keyword-based search to retrieve relevant context from:

- Items
- Comments
- Attachments
- Projects
- Changes
- GitHub Issues/PRs

The pipeline enriches this data and formats it in an agent-friendly way, but **does not make decisions** or generate prompts itself.

## Key Features

### 1. Hybrid Search (BM25 + Vector)

The service uses Weaviate's hybrid search combining:
- **Vector Search**: Semantic similarity using embeddings
- **BM25 Search**: Keyword-based text matching

The balance is controlled by an `alpha` parameter (0-1):
- `alpha = 0.2`: Keyword-heavy (good for technical queries, IDs, code)
- `alpha = 0.7`: Semantic-heavy (good for natural language questions)
- `alpha = 0.5`: Balanced

### 2. Automatic Alpha Heuristic

When `alpha` is not provided, the service automatically determines the best value based on query characteristics:

**Keyword-heavy queries** (alpha = 0.2):
- Issue IDs: `#36`, `#142`
- Version numbers: `v1.2.3`, `v2.0.0`
- Code patterns: `handleSubmit`, `UserController`, `user_service`
- Error keywords: `Exception`, `Error`, `Traceback`, `NullPointerException`
- HTTP errors: `HTTP 404`, `500 error`

**Semantic-heavy queries** (alpha = 0.7):
- Long natural language: "I need to implement a feature that allows users to export their data"
- Requirement descriptions
- General questions

**Balanced queries** (alpha = 0.5):
- Medium-length mixed queries
- Default fallback

### 3. Filtering

Support for multiple filter types:
- `project_id`: Filter by project
- `item_id`: Filter by parent item (for comments, attachments)
- `object_types`: Filter by type (e.g., `["item", "comment"]`)

### 4. Result Processing

- **Deduplication**: Removes duplicate results by `object_id`
- **Ranking**: Sorts by relevance score and type priority
- **Type Priority**: `item > github_issue/pr > comment > change > attachment > project`
- **Content Truncation**: Limits content to 600 characters with word-boundary respect
- **Limit**: Configurable maximum results (default: 20)

### 5. Agent-Friendly Output

The service returns structured data in two formats:

**1. Structured Objects** (`RAGContext`):
```python
{
    "query": "login bug",
    "alpha": 0.5,
    "summary": "Found 3 related objects: 2 items, 1 comment.",
    "items": [
        {
            "object_type": "item",
            "object_id": "123",
            "title": "Login Issue",
            "content": "Users cannot log in with special characters...",
            "source": "agira",
            "relevance_score": 0.85,
            "link": "/items/123/",
            "updated_at": "2024-01-01T10:00:00"
        }
    ],
    "stats": {
        "total_results": 5,
        "deduplicated": 3
    }
}
```

**2. Context Text** (for LLM prompts):
```text
[CONTEXT]
1) (type=item score=0.85) Title: Login Issue
   Link: /items/123/
   Snippet: Users cannot log in with special characters...

2) (type=comment score=0.72) 
   Link: /comments/456/
   Snippet: This might be related to encoding...
[/CONTEXT]

[SOURCES]
- item:123 -> /items/123/
- comment:456 -> /comments/456/
[/SOURCES]
```

### 6. Error Handling

The service handles errors gracefully:
- **Weaviate down**: Returns empty context with error in `stats`
- **No results**: Returns empty context with appropriate summary
- **Connection errors**: Logs error, returns empty context (no exceptions thrown)

This ensures AI agents don't crash when Weaviate is unavailable.

## Usage

### Basic Usage

```python
from core.services.rag import build_context

# Simple query
context = build_context(
    query="login bug with special characters"
)

# Use the context
print(context.summary)  # "Found 3 related objects: 2 items, 1 comment."
print(context.to_context_text())  # Agent-friendly formatted text
```

### With Filters

```python
# Filter by project
context = build_context(
    query="authentication issues",
    project_id="1",
    limit=10
)

# Filter by type
context = build_context(
    query="bug report",
    object_types=["item", "github_issue"],
    project_id="1"
)

# Filter by item (get related comments/attachments)
context = build_context(
    query="discussion",
    item_id="123"
)
```

### Custom Alpha

```python
# Force keyword search
context = build_context(
    query="some query",
    alpha=0.2
)

# Force semantic search
context = build_context(
    query="some query",
    alpha=0.7
)
```

### With Debug Info

```python
context = build_context(
    query="test query",
    include_debug=True
)

print(context.debug)
# {
#     'alpha_heuristic': 0.5,
#     'query_length': 10,
#     'word_count': 2
# }
```

## Integration with AI Agents

Example integration in an AI agent:

```python
from core.services.rag import build_context

def create_github_issue_with_context(user_request: str, project_id: str):
    # Get relevant context
    context = build_context(
        query=user_request,
        project_id=project_id,
        object_types=["item", "github_issue", "github_pr"],
        limit=15
    )
    
    # Build prompt with context
    prompt = f"""
You are creating a GitHub issue based on this user request:
{user_request}

Here is relevant context from the project:
{context.to_context_text()}

Summary: {context.summary}

Please create an appropriate GitHub issue...
"""
    
    # Use prompt with LLM...
```

## Configuration

Configuration is in `core/services/rag/config.py`:

```python
# Weaviate collection name
WEAVIATE_COLLECTION_NAME = "AgiraObject"

# Field mappings
FIELD_MAPPING = {
    "object_id": "object_id",
    "object_type": "type",
    "title": "title",
    "content": "text",
    ...
}

# Defaults
DEFAULT_LIMIT = 20
DEFAULT_ALPHA_KEYWORD = 0.2
DEFAULT_ALPHA_SEMANTIC = 0.7
DEFAULT_ALPHA_BALANCED = 0.5
MAX_CONTENT_LENGTH = 600

# Type priority (higher = more important)
TYPE_PRIORITY = {
    "item": 6,
    "github_issue": 5,
    ...
}
```

## Architecture

```
RAGPipelineService
├── _determine_alpha()          # Alpha heuristic logic
├── _truncate_content()         # Content snippet generation
├── _generate_summary()         # Result summary (heuristic)
├── _deduplicate_and_rank()     # Dedup and ranking
└── build_context()             # Main entry point
    ├── Query validation
    ├── Filter building
    ├── Weaviate hybrid search
    ├── Result processing
    └── Context formatting
```

## Testing

Run the tests:

```bash
python manage.py test core.services.rag.test_rag --settings=agira.test_settings
```

Test coverage includes:
- Alpha heuristic (10 tests)
- Content truncation (4 tests)
- Summary generation (4 tests)
- Deduplication and ranking (4 tests)
- Build context (9 tests)
- Context text generation (3 tests)

Total: 34 tests

## Limitations & Non-Goals

This service **does not**:
- Generate prompts (that's the agent's job)
- Make decisions (only provides context)
- Perform fine-tuning or learning
- Provide feedback loops
- Handle UI interactions
- Process external sources (only Weaviate)

## Future Enhancements (Not in v1)

- Chunking strategies for long attachments
- Relevance feedback/boosting
- Query expansion
- Multiple data source integration
- Caching layer
- UI indicators for Weaviate status

## See Also

- [Weaviate Service](../weaviate/) - Underlying vector database service
- [Weaviate Schema](../weaviate/schema.py) - Data model
- Issue: "RAG Pipeline Core Service (Hybrid Search, v1)"
