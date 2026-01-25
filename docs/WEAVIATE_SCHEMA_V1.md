# Weaviate Integration - Schema v1 Documentation

## Overview

This implementation provides a unified Weaviate collection (`AgiraObject`) for storing and querying all Agira entities semantically. It enables AI-powered search and context retrieval across items, comments, attachments, projects, changes, and more.

## Setup

### 1. Configure Weaviate

In Django admin, navigate to **Weaviate Configuration** and set:
- **URL**: Your Weaviate instance URL (e.g., `http://localhost:8080`)
- **API Key**: (Optional) Your Weaviate API key
- **Enabled**: Check this box to activate the integration

### 2. Initialize Schema

Run the management command to create the AgiraObject collection:

```bash
python manage.py weaviate_init
```

This creates the collection with all required properties for Schema v1.

## Automatic Synchronization

Once configured, Django signals automatically sync objects to Weaviate:

- **On Save**: Objects are upserted (created or updated) in Weaviate
- **On Delete**: Objects are removed from Weaviate

Supported models:
- Item
- ItemComment
- Attachment
- Project
- Change
- Node
- Release
- ExternalIssueMapping (GitHub issues/PRs)

**Note**: Signals fail silently if Weaviate is not configured, so save/delete operations never break.

## Manual Usage

### Import the API

```python
from core.services.weaviate import (
    make_weaviate_uuid,
    ensure_schema,
    upsert_object,
    delete_object,
    upsert_instance,
    sync_project,
)
```

### Generate Deterministic UUIDs

```python
# Generate a UUID for an object (idempotent)
uuid = make_weaviate_uuid("item", "123")
# Same input always generates the same UUID
assert uuid == make_weaviate_uuid("item", "123")
```

### Upsert Objects

#### By Instance
```python
from core.models import Item

item = Item.objects.get(pk=1)
uuid = upsert_instance(item)  # Auto-detects type and serializes
```

#### By Type and ID
```python
uuid = upsert_object("item", "123")  # Loads from DB and upserts
```

### Delete Objects

```python
deleted = delete_object("item", "123")
# Returns True if deleted, False if not found
```

### Sync Entire Project

```python
stats = sync_project("project-id")
# Returns: {'item': 10, 'comment': 25, 'change': 3, ...}
```

### Query (Semantic Search)

```python
from core.services.weaviate import query

results = query(
    project_id="1",
    query_text="login bug authentication",
    top_k=10,
    filters={"type": "item"}  # Optional
)

for result in results:
    print(f"{result['title']}: {result['score']}")
```

## Schema v1 Fields

### Required Fields
- **type**: Object type (item, comment, attachment, project, change, node, release, github_issue, github_pr)
- **object_id**: Django object ID (PK as string)
- **project_id**: Project ID for filtering (nullable for org-only objects)
- **title**: Object title or subject
- **text**: Semantic content (RAG body)
- **created_at**: Creation timestamp
- **updated_at**: Last update timestamp

### Optional Fields
- **org_id**: Organization ID
- **status**: Status (e.g., item.status, change.status)
- **url**: Internal UI route (e.g., /items/123/)
- **source_system**: agira|github|mail|zammad
- **external_key**: External identifier (e.g., owner/repo#123)
- **parent_object_id**: Parent object reference

### Attachment Metadata
- **mime_type**: MIME type
- **size_bytes**: File size in bytes
- **sha256**: SHA256 hash

## Serialization Rules

Each model type is serialized according to specific rules:

### Item
- **title**: item.title
- **text**: item.description + solution_description
- **status**: item.status

### Comment
- **title**: Comment subject or "Comment on {item.title}"
- **text**: comment.body
- **parent_object_id**: item.id

### Attachment
- **title**: filename
- **text**: Attachment metadata description
- **mime_type**, **size_bytes**, **sha256**: From attachment fields

### Project
- **title**: project.name
- **text**: project.description

### Change
- **title**: change.title
- **text**: change.description + rollback_plan

### GitHub Issue/PR
- **title**: GitHub title
- **text**: body + labels
- **external_key**: owner/repo#number
- **status**: open/closed/merged

## Architecture

```
core/services/weaviate/
├── __init__.py          # Public API exports
├── client.py            # Weaviate client management
├── schema.py            # Schema definition and creation
├── service.py           # High-level service methods
├── serializers.py       # Model-to-AgiraObject mapping
├── signals.py           # Django signal handlers
└── test_weaviate.py     # Unit tests
```

## Testing

Run the test suite:

```bash
python manage.py test core.services.weaviate.test_weaviate
```

All 29 tests should pass.

## Troubleshooting

### "Weaviate is not configured"
- Check that WeaviateConfiguration is set up in Django admin
- Ensure `enabled=True` and URL is set

### Signals not working
- Verify signals are imported in `core/apps.py`
- Check logs for any silent failures

### Collection not found
- Run `python manage.py weaviate_init`
- Check Weaviate connection and credentials

## Future Enhancements (v2)

The current implementation (v1) focuses on schema and synchronization. Future versions may add:

- Advanced RAG (Retrieval-Augmented Generation) features
- AI-powered triage and suggestions
- Project-wide Q&A capabilities
- Cross-project semantic search
- Custom vectorizers and embeddings
