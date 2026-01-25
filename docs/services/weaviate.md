# Weaviate Service

The Weaviate service provides semantic search and context storage capabilities for Agira using the [Weaviate vector database](https://weaviate.io/).

## Overview

The Weaviate service enables:
- **Context Storage**: Store content from various Agira sources (items, comments, nodes, projects, etc.)
- **Semantic Search**: Find relevant content using natural language queries
- **AI Agent Retrieval**: Provide context for AI-powered features like chat, auto-triage, and suggestions
- **Cross-Project Search**: Filter search results by project

## Architecture

### Package Structure

```
core/services/weaviate/
├── __init__.py       # Public API exports
├── client.py         # Client management and configuration
├── schema.py         # Schema definition and management
├── service.py        # High-level service APIs
└── test_weaviate.py  # Comprehensive tests
```

### Schema v1

The service uses a single collection named `AgiraContext` to store all context documents.

**Collection: AgiraContext**

| Property | Type | Description |
|----------|------|-------------|
| `source_type` | TEXT | Type of source (e.g., `item`, `item_comment`, `node`, `project`) |
| `source_id` | TEXT | Unique identifier from Postgres (UUID or int as string) |
| `project_id` | TEXT | Project foreign key for filtering |
| `title` | TEXT | Short title or subject |
| `text` | TEXT | Main content text (Markdown allowed) |
| `tags` | TEXT_ARRAY | Optional tags (e.g., `["bug", "backend", "security"]`) |
| `url` | TEXT | Link to detail view in Agira |
| `updated_at` | DATE | Last update timestamp for sync/refresh |

### Deterministic UUID Strategy

To ensure idempotent upserts, the service uses **deterministic UUID5 generation**:

```python
# UUID is generated from: source_type + ":" + source_id
# Example: "item:123" -> UUID5("a9c5e8d0-1234-5678-9abc-def012345678", "item:123")
```

**Benefits:**
- Same source always maps to the same Weaviate object UUID
- Multiple upserts with the same source_type and source_id update the existing document
- No need for separate existence checks before insert/update

**Implementation:**
```python
import uuid

UUID_NAMESPACE = uuid.UUID("a9c5e8d0-1234-5678-9abc-def012345678")

def _get_deterministic_uuid(source_type: str, source_id: str) -> uuid.UUID:
    stable_key = f"{source_type}:{source_id}"
    return uuid.uuid5(UUID_NAMESPACE, stable_key)
```

## Configuration

The service loads configuration from the `WeaviateConfiguration` singleton model in the database.

**Configuration Fields:**
- `url` (URLField): Weaviate server URL (e.g., `http://localhost:8080` or `http://192.168.1.100`)
- `http_port` (IntegerField): HTTP port for Weaviate (default: 8080, local installs often use 8081)
- `grpc_port` (IntegerField): gRPC port for Weaviate (default: 50051)
- `api_key` (EncryptedCharField): Optional API key for authentication
- `enabled` (BooleanField): Whether the service is enabled

**Django Admin:**
Configure Weaviate settings in Django Admin under "Weaviate Configuration".

**Port Configuration Notes:**
- If the URL includes a port (e.g., `http://localhost:9999`), it takes precedence over the `http_port` field
- For local installations, you typically need to configure the URL without a port and set the ports separately
- Example local setup: URL=`http://192.168.1.100`, HTTP Port=8081, gRPC Port=50051

## Public API

### Check Availability

```python
from core.services.weaviate import is_available

if is_available():
    # Weaviate is configured and enabled
    pass
```

### Upsert Document

Store or update a context document. This operation is **idempotent** - calling it multiple times with the same `source_type` and `source_id` will update the existing document.

```python
from core.services.weaviate import upsert_document

doc_id = upsert_document(
    source_type="item",
    source_id="123",
    project_id="proj-1",
    title="Bug in login",
    text="Users cannot log in with special characters in their password",
    tags=["bug", "security", "login"],
    url="/items/123",
    updated_at=datetime.now()  # Optional, defaults to now
)
# Returns: Weaviate object UUID as string
```

**Parameters:**
- `source_type` (str): Type of source (required)
- `source_id` (str|int): Unique identifier (required)
- `project_id` (str|int): Project foreign key (required)
- `title` (str): Short title (required)
- `text` (str): Main content text (required)
- `tags` (list[str]|None): Optional tags
- `url` (str|None): Optional URL to detail view
- `updated_at` (datetime|None): Optional timestamp (defaults to now)

**Raises:**
- `ServiceDisabled`: If Weaviate is not enabled
- `ServiceNotConfigured`: If Weaviate configuration is incomplete

### Query Documents

Search documents using semantic search with automatic project filtering.

```python
from core.services.weaviate import query

results = query(
    project_id="proj-1",
    query_text="login authentication issues",
    top_k=10,  # Optional, defaults to 10
    filters={"source_type": "item"}  # Optional additional filters
)

for result in results:
    print(f"{result['title']}: {result['score']}")
    print(f"  {result['text_preview']}")
    print(f"  {result['url']}")
```

**Parameters:**
- `project_id` (str|int): Project ID to filter by (required)
- `query_text` (str): Search query text (required)
- `top_k` (int): Maximum number of results (default: 10)
- `filters` (dict|None): Optional additional filters

**Returns:** List of dictionaries with:
- `source_type`: Type of the source
- `source_id`: ID of the source
- `title`: Document title
- `text_preview`: First 200 characters of text
- `url`: URL to detail view (if available)
- `score`: Relevance score/distance

### Delete Document

Remove a context document from Weaviate.

```python
from core.services.weaviate import delete_document

deleted = delete_document("item", "123")
if deleted:
    print("Document deleted successfully")
else:
    print("Document did not exist")
```

**Parameters:**
- `source_type` (str): Type of source (required)
- `source_id` (str|int): Unique identifier (required)

**Returns:** `bool` - True if deleted, False if didn't exist

## Usage Examples

### Store Item Content

```python
from core.services.weaviate import upsert_document

# Store an item
upsert_document(
    source_type="item",
    source_id=item.id,
    project_id=item.project_id,
    title=item.title,
    text=item.description,
    tags=["bug", "backend"] if item.is_bug else [],
    url=f"/items/{item.id}"
)
```

### Store Comment

```python
# Store a comment
upsert_document(
    source_type="item_comment",
    source_id=comment.id,
    project_id=comment.item.project_id,
    title=f"Comment on {comment.item.title}",
    text=comment.text,
    url=f"/items/{comment.item.id}#comment-{comment.id}"
)
```

### Search for Related Items

```python
from core.services.weaviate import query

# Find items related to a specific query
results = query(
    project_id="current-project-id",
    query_text="authentication and authorization bugs",
    top_k=5,
    filters={"source_type": "item"}
)

for result in results:
    print(f"Found: {result['title']}")
    print(f"  Relevance: {result['score']}")
```

### Delete Item Context on Deletion

```python
from core.services.weaviate import delete_document

# When an item is deleted
delete_document("item", item.id)

# Also delete related comments
for comment in item.comments.all():
    delete_document("item_comment", comment.id)
```

## Error Handling

The service raises consistent exceptions for error conditions:

```python
from core.services.weaviate import upsert_document
from core.services.exceptions import ServiceDisabled, ServiceNotConfigured

try:
    upsert_document(
        source_type="item",
        source_id="123",
        project_id="proj-1",
        title="Test",
        text="Test content"
    )
except ServiceDisabled:
    # Weaviate is explicitly disabled in configuration
    logger.info("Weaviate is disabled, skipping indexing")
except ServiceNotConfigured:
    # Weaviate is enabled but configuration is incomplete (e.g., missing URL)
    logger.warning("Weaviate is not properly configured")
```

**Best Practice:**
Services that optionally use Weaviate should catch these exceptions and gracefully degrade:

```python
def index_item(item):
    """Index an item, with graceful degradation if Weaviate is unavailable."""
    try:
        from core.services.weaviate import upsert_document
        upsert_document(
            source_type="item",
            source_id=item.id,
            project_id=item.project_id,
            title=item.title,
            text=item.description
        )
    except (ServiceDisabled, ServiceNotConfigured):
        # Weaviate is not available, but we can continue
        pass
```

## Operation

### Enable/Disable

1. Go to Django Admin
2. Navigate to "Weaviate Configuration"
3. Set `enabled` to True/False
4. Save

### Configure Connection

1. Go to Django Admin
2. Navigate to "Weaviate Configuration"
3. Set required fields:
   - **URL**: Weaviate server URL (e.g., `http://localhost:8080` or `http://192.168.1.100` for local installations)
   - **HTTP Port**: Port for HTTP connections (default: 8080, local installs often use 8081)
   - **gRPC Port**: Port for gRPC connections (default: 50051)
   - **API Key**: Optional, only if your Weaviate instance requires authentication (leave empty for local installations)
   - **Enabled**: Set to `True`
4. Save

**Example Configuration for Local Weaviate:**
- URL: `http://192.168.1.100`
- HTTP Port: `8081`
- gRPC Port: `50051`
- API Key: (empty)
- Enabled: ✓

### Test Connection

```python
from core.services.weaviate import is_available
from core.services.weaviate.client import get_client

# Check if configured
if is_available():
    # Try to connect
    try:
        client = get_client()
        print("Successfully connected to Weaviate")
        client.close()
    except Exception as e:
        print(f"Failed to connect: {e}")
else:
    print("Weaviate is not configured or disabled")
```

## Schema Management

The schema is automatically created when the first document is upserted. The `ensure_schema()` function:
- Checks if the `AgiraContext` collection exists
- Creates it with the v1 schema if it doesn't exist
- Skips creation if it already exists

**Manual Schema Creation:**
```python
from core.services.weaviate.client import get_client
from core.services.weaviate.schema import ensure_schema

client = get_client()
try:
    ensure_schema(client)
    print("Schema ensured")
finally:
    client.close()
```

## Future Enhancements

### Schema v2 (Planned)

Future versions may include:
- **schema_version** property to track schema versions
- Migration logic for upgrading existing collections
- Additional properties for more metadata
- Support for chunking long documents

**Migration Strategy:**
```python
# Example migration logic (not yet implemented)
def migrate_schema_v1_to_v2(client):
    """Migrate schema from v1 to v2."""
    collection = client.collections.get(COLLECTION_NAME)
    
    # Add new property
    collection.update(
        properties=[
            Property(name="schema_version", data_type=DataType.TEXT)
        ]
    )
    
    # Update existing objects with default version
    # ... migration logic ...
```

### Chunking Strategy (Planned)

For very long documents, future versions may implement chunking:
- Split long text into multiple chunks
- Store each chunk as a separate object
- Link chunks to parent document
- Merge results from multiple chunks in query

## Performance Considerations

### Caching

The service implements several caching strategies:
- **Configuration caching**: Configuration is cached for 60 seconds (via `core.services.config`)
- **Schema ensured flag**: Schema creation is checked only once per process

### Batch Operations (Future)

For bulk indexing, consider implementing batch operations in the future:
```python
# Future API (not yet implemented)
from core.services.weaviate import batch_upsert

batch_upsert([
    {"source_type": "item", "source_id": "1", ...},
    {"source_type": "item", "source_id": "2", ...},
    # ... many more documents
])
```

## Troubleshooting

### Connection Errors

**Problem:** `ServiceNotConfigured: Weaviate URL is not configured`

**Solution:** Ensure the Weaviate URL is set in Django Admin.

---

**Problem:** Connection timeout or refused

**Solutions:**
- Verify Weaviate is running
- Check the URL is correct
- Verify firewall settings allow connections

### Schema Issues

**Problem:** Schema creation fails

**Solutions:**
- Verify Weaviate server and client compatibility (Weaviate Python client v4.x required)
- Check Weaviate logs for errors
- Ensure sufficient permissions

### Query Returns No Results

**Possible Causes:**
- No documents indexed for the project
- Query text is too specific or uses wrong terminology
- Project ID filter is incorrect

**Debug:**
```python
# Check if documents exist
from core.services.weaviate.client import get_client

client = get_client()
try:
    collection = client.collections.get("AgiraContext")
    # Get count of all objects
    response = collection.aggregate.over_all(total_count=True)
    print(f"Total documents: {response.total_count}")
finally:
    client.close()
```

## Security

### API Key Storage

API keys are stored encrypted in the database using `django-encrypted-model-fields`.

### Best Practices

- Use authentication (API key) in production
- Use HTTPS for Weaviate connections in production
- Restrict network access to Weaviate server
- Regularly rotate API keys
- Don't log sensitive data (API keys, personal information)

## Dependencies

- **weaviate-client** (v4.x): Python client library for Weaviate (compatible with Weaviate server v1.23+)
- **Django** (v5.x): Web framework
- **django-encrypted-model-fields**: For secure API key storage

**Note:** The Weaviate Python client v4.x works with Weaviate server versions 1.23 and higher. Ensure your Weaviate server version is compatible.

## References

- [Weaviate Documentation](https://weaviate.io/developers/weaviate)
- [Weaviate Python Client](https://weaviate.io/developers/weaviate/client-libraries/python)
- [Core Services Configuration](./config.md)
