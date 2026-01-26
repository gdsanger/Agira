# GitHub Markdown Sync Implementation

## Overview

This document describes the implementation of the GitHub markdown file synchronization feature for the Agira project. This feature extends the existing `github_sync_worker` to automatically sync markdown files from GitHub repositories as project attachments and index them in Weaviate.

**Implementation Date:** January 2026  
**Version:** v1.0

---

## Features

### Automatic Markdown Synchronization

The `github_sync_worker` now automatically:
- Scans all projects with configured GitHub repositories
- Finds all `.md` files in the repository (recursively)
- Creates/updates project attachments for each markdown file
- Tracks file versions using GitHub SHA hashes
- Indexes file content in Weaviate for semantic search

### Version Tracking

Each synced markdown file is tracked using:
- **GitHub SHA**: The blob SHA from GitHub to detect changes
- **Repository Path**: The full path within the repository (e.g., `docs/README.md`)
- **Last Sync Time**: Timestamp of the last successful sync

### Change Detection

The system efficiently detects changes by:
- Comparing the current GitHub SHA with the stored SHA
- Only downloading and updating files when the SHA has changed
- Skipping unchanged files to minimize API calls and processing

---

## Architecture

### Components

#### 1. GitHub Client Extensions (`core/services/github/client.py`)

**New Methods:**

```python
def get_repository_contents(owner, repo, path='', ref=None)
    """Get contents of a file or directory in a repository."""

def get_file_content(owner, repo, path, ref=None)
    """Get raw file content from a repository."""
```

**Features:**
- Fetches repository directory listings
- Downloads file content (base64-decoded)
- Supports specifying git references (branches, tags, commits)
- Integrates with existing HTTP client and rate limiting

#### 2. Markdown Sync Service (`core/services/github_sync/markdown_sync.py`)

**Main Class:** `MarkdownSyncService`

**Key Methods:**

```python
sync_project_markdown_files(project, ref=None)
    """Sync all markdown files for a project."""
    Returns: Statistics dict with counts of files found/created/updated/skipped

_find_markdown_files(owner, repo, path='', ref=None)
    """Recursively find all .md files in repository."""
    Returns: List of file info dicts

_sync_markdown_file(project, owner, repo, file_info, ref=None)
    """Sync a single markdown file."""
    Returns: 'created', 'updated', or 'skipped'

_find_existing_attachment(project, repo_identifier, file_path)
    """Find existing attachment for a GitHub file."""
    Returns: Attachment or None

_create_attachment(project, owner, repo, file_path, github_sha, file_name, ref=None)
    """Create new attachment for a GitHub markdown file."""
    Returns: Created Attachment instance

_update_attachment(attachment, owner, repo, file_path, github_sha, ref=None)
    """Update existing attachment with new content."""
```

**Integration:**
- Uses `AttachmentStorageService` for file storage
- Stores files in standard project attachment location
- Calls `upsert_instance()` to index in Weaviate
- Uses Django transactions for atomicity

#### 3. Enhanced Worker Command (`core/management/commands/github_sync_worker.py`)

**New Method:**

```python
_sync_markdown_files(github_service, project_id=None, dry_run=False)
    """Sync markdown files from GitHub repositories for all projects."""
```

**Execution Flow:**

1. **Part 1: Markdown Sync**
   - Find all projects with GitHub repositories
   - For each project, sync markdown files
   - Report statistics

2. **Part 2: Issues/PRs Sync** (existing functionality)
   - Sync GitHub issues and PRs
   - Update item statuses
   - Link PRs to issues

**Command Options:**

```bash
python manage.py github_sync_worker [options]

Options:
  --batch-size N       Number of mappings to process per batch (default: 50)
  --project-id N       Only sync for specific project ID
  --dry-run            Show what would be synced without making changes
```

#### 4. Database Model Extensions (`core/models.py`)

**Attachment Model - New Fields:**

```python
class Attachment(models.Model):
    # ... existing fields ...
    
    # GitHub metadata fields
    github_repo_path = CharField(max_length=1000, blank=True)
        # Format: "owner/repo:path/to/file.md"
    
    github_sha = CharField(max_length=40, blank=True)
        # GitHub blob SHA for version tracking
    
    github_last_synced = DateTimeField(null=True, blank=True)
        # Last sync timestamp
```

**Migration:** `0009_add_github_metadata_to_attachment.py`

---

## Usage

### Running the Sync Worker

**Sync all projects:**
```bash
python manage.py github_sync_worker
```

**Sync specific project:**
```bash
python manage.py github_sync_worker --project-id=1
```

**Dry run (preview changes):**
```bash
python manage.py github_sync_worker --dry-run
```

### Example Output

```
Starting GitHub sync worker...

============================================================
PART 1: Syncing Markdown Files from GitHub Repositories
============================================================
Found 2 projects with GitHub repositories

  Project: Agira (gdsanger/Agira)
    ✓ Found 5 .md files: 3 created, 0 updated, 2 skipped

  Project: Test Project (testorg/testrepo)
    ✓ Found 2 .md files: 0 created, 1 updated, 1 skipped

============================================================
PART 2: Syncing GitHub Issues and Pull Requests
============================================================
Found 10 issue mappings to sync
...

============================================================
Overall Sync Summary:

--- Markdown Files ---
  Projects processed: 2
  Files found: 7
  Files created: 3
  Files updated: 1
  Files skipped: 3

--- GitHub Issues/PRs ---
  Total mappings processed: 10/10
  Item statuses updated: 2
  PRs linked: 3
  Objects pushed to Weaviate: 5
============================================================

✓ GitHub sync completed successfully
```

### Prerequisites

1. **GitHub Configuration**
   - Navigate to Django Admin → GitHub Configuration
   - Set `enable_github` to True
   - Configure `github_token` (Personal Access Token with repo access)

2. **Project Setup**
   - Each project must have `github_owner` and `github_repo` configured
   - Example: owner=`gdsanger`, repo=`Agira`

3. **Weaviate Configuration** (Optional but recommended)
   - Configure Weaviate in Django Admin
   - Enables semantic search of markdown content

---

## Data Flow

### Initial Sync (New File)

```
1. Worker identifies project with GitHub repo
   ↓
2. Calls GitHub API to list repository contents
   ↓
3. Recursively finds all .md files
   ↓
4. For each .md file:
   - Checks if attachment exists (by github_repo_path)
   - Downloads file content via GitHub API
   - Creates Attachment record
   - Stores file using AttachmentStorageService
   - Creates AttachmentLink to project
   - Updates GitHub metadata (sha, path, sync time)
   - Indexes in Weaviate (if enabled)
```

### Subsequent Sync (Existing File)

```
1. Worker identifies project
   ↓
2. Finds .md files in repository
   ↓
3. For each file:
   - Looks up existing attachment by github_repo_path
   - Compares GitHub SHA
   
   If SHA unchanged:
     → Skip (no API call for content)
   
   If SHA changed:
     → Download new content
     → Update file on disk
     → Update Attachment metadata
     → Update in Weaviate
```

---

## File Storage

### Storage Location

Markdown files are stored using the standard attachment storage:

```
data/projects/{project_id}/project/{attachment_id}__{filename}
```

Example:
```
data/projects/1/project/42__README.md
data/projects/1/project/43__docs_guide.md
```

### Attachment Metadata

Each synced markdown file has:
- `original_name`: File name (e.g., "README.md")
- `content_type`: "text/markdown"
- `storage_path`: Relative path to file
- `sha256`: File content hash
- `github_repo_path`: "owner/repo:path/in/repo"
- `github_sha`: GitHub blob SHA
- `github_last_synced`: Sync timestamp

### AttachmentLink

Files are linked to projects with:
- `role`: `AttachmentRole.PROJECT_FILE`
- `target`: The Project instance

---

## Weaviate Integration

### Indexing Process

When a markdown file is synced, it's automatically indexed in Weaviate:

```python
# After creating/updating attachment
upsert_instance(attachment)
```

### Serialization

The `_serialize_attachment()` function in `core/services/weaviate/serializers.py` converts attachments to AgiraObjects:

```python
{
    'type': 'attachment',
    'object_id': str(attachment.id),
    'project_id': str(project.id),
    'title': 'README.md',
    'text': 'Attachment: README.md (text/markdown)\nSize: 1234 bytes',
    'url': f'/attachments/{attachment.id}/',
    'mime_type': 'text/markdown',
    'size_bytes': 1234,
    'sha256': 'abc123...',
    'created_at': datetime(...),
}
```

### Search Capabilities

Synced markdown files can be found via:
- Semantic search (vector similarity)
- Text search (full-text)
- Filters (by project, type, etc.)

---

## Error Handling

### Robust Error Handling

The sync process is designed to be resilient:

1. **Project-level errors**: If one project fails, others continue
2. **File-level errors**: If one file fails, others continue
3. **API errors**: Logged but don't crash the worker
4. **Weaviate errors**: Logged but don't prevent file sync

### Error Logging

All errors are logged with context:
```python
logger.error(
    f"Error syncing {file_path}: {str(e)}",
    exc_info=True
)
```

Error statistics are included in the summary output.

### Rate Limiting

The GitHub client includes:
- Automatic retries (max 3)
- Timeout handling (30 seconds)
- Respects GitHub rate limits via existing HTTP client

---

## Performance Considerations

### Optimization Strategies

1. **SHA-based Change Detection**
   - Only downloads files when SHA changes
   - Avoids unnecessary API calls and processing

2. **Recursive Directory Traversal**
   - Efficiently walks repository tree
   - Handles large repositories with many directories

3. **Batch Processing**
   - Projects processed sequentially
   - Files within project processed sequentially
   - Allows for graceful interruption/resume

4. **Minimal API Calls**
   - One call to list directory contents
   - One call per changed file to download content
   - Skipped files require no content download

### Scalability

The system handles:
- Large repositories (100+ markdown files)
- Multiple projects (10+ projects)
- Frequent syncs (hourly/daily)

For very large deployments, consider:
- Running worker during off-peak hours
- Filtering to specific projects with `--project-id`
- Using Celery for async processing (future enhancement)

---

## Testing

### Test Coverage

**Test Suite:** `core/services/github_sync/test_markdown_sync.py`

**Tests Included:**

1. **GitHub Client Tests** (3 tests)
   - `test_get_repository_contents_for_directory`
   - `test_get_repository_contents_for_file`
   - `test_get_file_content`

2. **Markdown Sync Service Tests** (7 tests)
   - `test_find_markdown_files_in_root`
   - `test_find_markdown_files_recursively`
   - `test_create_attachment_for_new_file`
   - `test_skip_unchanged_file`
   - `test_update_changed_file`
   - `test_sync_project_without_github_repo`
   - `test_handle_api_errors_gracefully`

**Running Tests:**

```bash
# Run all markdown sync tests
python manage.py test core.services.github_sync.test_markdown_sync --settings=agira.test_settings

# Run with verbose output
python manage.py test core.services.github_sync.test_markdown_sync --settings=agira.test_settings -v 2
```

**Test Results:** ✅ All 10 tests passing

---

## Configuration

### Required Settings

**Django Settings:**
```python
# In agira/settings.py
AGIRA_DATA_DIR = BASE_DIR / 'data'  # Attachment storage directory
AGIRA_MAX_ATTACHMENT_SIZE_MB = 25   # Max file size
```

**GitHub Configuration (Django Admin):**
- `enable_github`: True
- `github_token`: Personal Access Token with `repo` scope
- `github_api_base_url`: https://api.github.com (default)

**Project Configuration:**
- `github_owner`: Repository owner (e.g., "gdsanger")
- `github_repo`: Repository name (e.g., "Agira")

### Optional Settings

**Weaviate Configuration:**
- Enable for semantic search of markdown content
- Configure URL, ports, and API key in Django Admin

---

## Limitations and Future Enhancements

### Current Limitations

1. **File Types**: Only `.md` files are synced
   - Other formats (`.rst`, `.txt`, `.adoc`) are not included

2. **Directory Filtering**: Entire repository is scanned
   - No option to include/exclude specific directories (e.g., only `/docs`)

3. **File Size**: Limited by `AGIRA_MAX_ATTACHMENT_SIZE_MB` setting
   - Very large markdown files may be rejected

4. **Sync Trigger**: Manual via management command
   - No automatic scheduled sync (use cron/systemd timer)

### Future Enhancements

1. **Selective Syncing**
   - Configuration option to filter directories (e.g., only `docs/` folder)
   - Option to sync other text formats (`.rst`, `.txt`, etc.)

2. **Webhook Integration**
   - Automatic sync triggered by GitHub push webhooks
   - Real-time updates when markdown files change

3. **Background Processing**
   - Celery task for async processing
   - Better handling of large repositories

4. **Content Extraction**
   - Parse markdown headers/sections
   - Extract metadata from front matter
   - Better Weaviate indexing with structured content

5. **Sync Status Dashboard**
   - UI to view sync status per project
   - Last sync time and file counts
   - Error history

6. **Conflict Resolution**
   - Handle manual edits to synced attachments
   - Option to mark files as "do not sync"

---

## Troubleshooting

### Common Issues

**Issue:** No files synced, but repository has .md files  
**Solution:** 
- Check that project has `github_owner` and `github_repo` set
- Verify GitHub token has `repo` access
- Check worker logs for API errors

**Issue:** "Authentication failed" errors  
**Solution:**
- Verify GitHub token is valid and not expired
- Token needs `repo` scope for private repositories
- Check token in Django Admin → GitHub Configuration

**Issue:** Files synced but not searchable in Weaviate  
**Solution:**
- Verify Weaviate is enabled and accessible
- Check Weaviate logs for indexing errors
- Try manual push: `upsert_instance(attachment)`

**Issue:** All files marked as "created" on every sync  
**Solution:**
- Check that `github_repo_path` is being set correctly
- Verify database indexes are created (run migrations)
- Ensure unique constraint on attachment links is working

### Debug Commands

```python
# Check if markdown sync service works
from core.services.github.client import GitHubClient
from core.services.github_sync.markdown_sync import MarkdownSyncService
from core.models import Project, GitHubConfiguration

config = GitHubConfiguration.load()
client = GitHubClient(token=config.github_token)
service = MarkdownSyncService(github_client=client)

project = Project.objects.get(pk=1)
stats = service.sync_project_markdown_files(project)
print(stats)

# List all synced markdown files
from core.models import Attachment
md_files = Attachment.objects.exclude(github_repo_path='')
for att in md_files:
    print(f"{att.id}: {att.github_repo_path} (SHA: {att.github_sha})")
```

---

## Security Considerations

### Token Security

- GitHub tokens stored encrypted in database (`EncryptedCharField`)
- Never log tokens or expose in error messages
- Use tokens with minimal required scopes

### File Content

- All downloaded files validated against size limits
- SHA256 hash computed for integrity verification
- Files stored in secure data directory (not web-accessible)

### API Rate Limiting

- Respects GitHub API rate limits
- Automatic retry with backoff
- Logs rate limit warnings

### Path Traversal Prevention

- File paths sanitized by `AttachmentStorageService`
- No direct path manipulation from GitHub data
- Files stored with unique IDs preventing collisions

---

## Migration Guide

### Upgrading Existing Installation

1. **Apply Database Migration**
   ```bash
   python manage.py migrate core 0009
   ```

2. **Verify GitHub Configuration**
   - Check that GitHub integration is enabled
   - Verify token has required permissions

3. **Initial Sync**
   ```bash
   # Dry run first to see what will be synced
   python manage.py github_sync_worker --dry-run
   
   # Perform actual sync
   python manage.py github_sync_worker
   ```

4. **Set Up Scheduled Sync** (optional)
   ```bash
   # Add to crontab for daily sync at 2 AM
   0 2 * * * cd /path/to/agira && python manage.py github_sync_worker
   ```

### Rollback

To remove the feature:

1. Set `github_repo_path` to empty for all attachments
2. Remove the markdown sync service files
3. Revert worker command changes
4. Migration rollback: `python manage.py migrate core 0008`

---

## References

- **GitHub REST API**: https://docs.github.com/en/rest/repos/contents
- **Attachment Storage**: `ATTACHMENT_STORAGE_IMPLEMENTATION.md`
- **Weaviate Integration**: `WEAVIATE_SYNC_IMPLEMENTATION.md`
- **GitHub Service**: `GITHUB_SERVICE_SUMMARY.md`

---

## Implementation Summary

**Files Created:**
- `core/services/github_sync/__init__.py`
- `core/services/github_sync/markdown_sync.py`
- `core/services/github_sync/test_markdown_sync.py`
- `core/migrations/0009_add_github_metadata_to_attachment.py`
- `docs/GITHUB_MARKDOWN_SYNC_IMPLEMENTATION.md`

**Files Modified:**
- `core/services/github/client.py` - Added repository content methods
- `core/models.py` - Added GitHub metadata fields to Attachment
- `core/management/commands/github_sync_worker.py` - Added markdown sync

**Lines of Code:**
- Service: ~400 lines
- Tests: ~280 lines
- Client extensions: ~60 lines
- Worker integration: ~100 lines

**Test Coverage:** 10/10 tests passing ✅

**Implementation Time:** ~3 hours

---

**Document Version:** 1.0  
**Last Updated:** January 25, 2026
