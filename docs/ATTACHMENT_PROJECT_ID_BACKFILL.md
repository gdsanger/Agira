# Backfill Attachment Project IDs in Weaviate

This document describes the `backfill_attachment_project_ids` management command, which updates Weaviate to include the correct `project_id` for all attachments.

## Background

Attachments in Weaviate's `AgiraObject` collection were missing the `project_id` field, which prevented them from being found in RAG searches that operate within a project context. This has been fixed in the serializer, but existing attachments in Weaviate need to be updated.

## The Fix

Two changes were made to address this issue:

1. **Serializer Fix** (`core/services/weaviate/serializers.py`):
   - Updated `_serialize_attachment()` to correctly extract `project_id` for all attachment types
   - For Project attachments: Uses `target.id` (since the target IS the project)
   - For Item/Comment attachments: Uses `target.project_id` (from the parent object)

2. **Backfill Script** (`core/management/commands/backfill_attachment_project_ids.py`):
   - CLI command to update existing attachments in Weaviate
   - Extracts `project_id` via AttachmentLink relationships
   - Supports dry-run mode and project filtering

## Usage

### Preview Changes (Dry Run)

To see what would be updated without making changes:

```bash
python manage.py backfill_attachment_project_ids --dry-run
```

### Update All Attachments

To update all attachments in Weaviate with the correct project_id:

```bash
python manage.py backfill_attachment_project_ids
```

### Update Specific Project

To update only attachments for a specific project (e.g., project ID 1):

```bash
python manage.py backfill_attachment_project_ids --project-id 1
```

### Dry Run for Specific Project

To preview changes for a specific project:

```bash
python manage.py backfill_attachment_project_ids --dry-run --project-id 1
```

## What Gets Updated

The script:

1. Fetches all attachments with their related AttachmentLink relationships
2. For each attachment:
   - Determines the `project_id` via the link target:
     - If linked to a Project: uses the project's ID
     - If linked to an Item/Comment: uses the item's project_id
   - Calls `upsert_instance(attachment)` to update Weaviate
3. Reports statistics on attachments processed, updated, skipped, and any errors

## Output Example

```
Found 523 total attachments to check...
  Processed 100 attachments...
  Processed 200 attachments...
  Processed 300 attachments...

============================================================
Backfill Summary:
  Total attachments checked: 523
  Attachments processed: 485
  Attachments updated: 485
  Attachments skipped (no project_id): 38
============================================================

✓ Successfully backfilled project_id for 485 attachments in Weaviate.
```

## When to Run

Run this command:

- **Once** after deploying the serializer fix to backfill existing attachments
- Optionally after bulk imports or data migrations if attachments are missing project_id

## Notes

- The script is idempotent - safe to run multiple times
- Skipped attachments (no project_id) are typically orphaned or system attachments
- Future attachments will have project_id set automatically via the fixed serializer
- The backfill uses the same logic as the serializer to ensure consistency

## Related Files

- **Serializer**: `core/services/weaviate/serializers.py` - `_serialize_attachment()`
- **Backfill Script**: `core/management/commands/backfill_attachment_project_ids.py`
- **Signals**: `core/services/weaviate/signals.py` - Auto-sync on save
- **Upload Views**: `core/views.py` - `item_upload_attachment()`, `project_upload_attachment()`
- **GitHub Sync**: `core/services/github_sync/markdown_sync.py` - Markdown file sync
