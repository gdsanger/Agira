# Attachment Storage Service

The Attachment Storage Service provides a robust, secure local filesystem storage solution for managing file attachments in Agira. Attachments can be linked to Projects, Items, and ItemComments.

## Overview

This service implements a clean separation between:
- **Storage**: Physical files stored on the local filesystem
- **Metadata**: Database records tracking attachment information
- **Links**: Associations between attachments and their target objects

## Architecture

### Package Structure
```
core/services/storage/
├── __init__.py         # Package exports
├── errors.py           # Exception classes
├── paths.py            # Path generation and sanitization
└── service.py          # Main service implementation
```

### Data Models

#### Attachment Model
Stores metadata about uploaded files.

**Fields:**
- `id` - Primary key
- `created_at` - Timestamp when attachment was created
- `created_by` - Foreign key to User (nullable)
- `original_name` - Original filename (sanitized)
- `content_type` - MIME type (e.g., `text/plain`, `image/jpeg`)
- `size_bytes` - File size in bytes
- `sha256` - SHA256 hash of file content (optional but recommended)
- `storage_path` - Relative path from `AGIRA_DATA_DIR`
- `is_deleted` - Soft delete flag

**Indexes:**
- `created_at` - For time-based queries
- `sha256` - For potential deduplication

#### AttachmentLink Model
Links attachments to target objects using Django's Generic Foreign Keys.

**Fields:**
- `id` - Primary key
- `attachment` - Foreign key to Attachment
- `target_content_type` - ContentType of the target object
- `target_object_id` - ID of the target object
- `target` - GenericForeignKey combining the above two fields
- `role` - Role/purpose of the attachment (see AttachmentRole choices)
- `created_at` - Timestamp when link was created

**Constraints:**
- Unique constraint on `(attachment, target_content_type, target_object_id, role)`

**AttachmentRole Choices:**
- `PROJECT_FILE` - File attached to a project
- `ITEM_FILE` - File attached to an item
- `COMMENT_ATTACHMENT` - File attached to a comment

## Configuration

### Settings

Add to your `settings.py`:

```python
# Attachment Storage Configuration
AGIRA_DATA_DIR = BASE_DIR / 'data'  # Base directory for attachments
AGIRA_MAX_ATTACHMENT_SIZE_MB = 25    # Maximum file size in MB
```

Environment variables:
- `AGIRA_DATA_DIR` - Override the data directory path
- `AGIRA_MAX_ATTACHMENT_SIZE_MB` - Override the max file size

## Path Strategy

### Directory Structure

Files are stored with a stable, hierarchical path structure:

```
data/
└── projects/
    └── {project_id}/
        ├── project/
        │   └── {attachment_id}__{safe_filename}
        └── items/
            └── {item_id}/
                ├── item/
                │   └── {attachment_id}__{safe_filename}
                └── comments/
                    └── {comment_id}/
                        └── comment/
                            └── {attachment_id}__{safe_filename}
```

### Path Components

1. **Target Type Path**: Indicates what the attachment is linked to
   - `projects/{project_id}/project/` - Project-level files
   - `projects/{project_id}/items/{item_id}/item/` - Item-level files
   - `projects/{project_id}/items/{item_id}/comments/{comment_id}/comment/` - Comment attachments

2. **Filename**: `{attachment_id}__{safe_filename}`
   - `attachment_id` ensures uniqueness
   - `safe_filename` is the sanitized original name

### Filename Sanitization

The service sanitizes filenames to prevent security issues:
- Removes directory traversal attempts (`../`, etc.)
- Replaces unsafe characters with underscores
- Preserves file extensions
- Limits filename length to 100 characters
- Provides default name if sanitization results in empty string

## Service API

### Initialization

```python
from core.services.storage import AttachmentStorageService

# Use default settings
service = AttachmentStorageService()

# Or specify custom settings
service = AttachmentStorageService(
    data_dir='/custom/path',
    max_size_mb=50
)
```

### Store Attachment

Store a new file and create attachment metadata.

```python
from django.core.files.uploadedfile import UploadedFile

attachment = service.store_attachment(
    file=uploaded_file,          # UploadedFile or file-like object
    target=project,               # Project, Item, or ItemComment
    created_by=user,              # User object (optional)
    role='ProjectFile',           # AttachmentRole (optional, auto-determined)
    compute_hash=True             # Compute SHA256 (default: True)
)
```

**Returns:** `Attachment` instance

**Raises:**
- `AttachmentTooLarge` - File exceeds size limit
- `AttachmentWriteError` - File cannot be written to storage

### Link Existing Attachment

Link an existing attachment to another target (e.g., reuse file).

```python
link = service.link_attachment(
    attachment=existing_attachment,
    target=item,
    role='ItemFile'  # Optional, auto-determined if not provided
)
```

**Returns:** `AttachmentLink` instance

### Get File Path

Get the absolute filesystem path for an attachment.

```python
from pathlib import Path

file_path: Path = service.get_file_path(attachment)
# Use file_path for reading, sending via email, etc.
```

**Returns:** `Path` object (absolute path)

**Raises:**
- `AttachmentNotFound` - File doesn't exist or path is invalid

### Delete Attachment

Delete an attachment (soft or hard delete).

```python
# Soft delete (mark as deleted, keep file)
service.delete_attachment(attachment, hard=False)

# Hard delete (remove file and DB record)
service.delete_attachment(attachment, hard=True)
```

## Usage Examples

### Upload File to Project

```python
from core.services.storage import AttachmentStorageService
from core.models import Project

service = AttachmentStorageService()

# From Django view with file upload
def upload_project_file(request, project_id):
    project = Project.objects.get(id=project_id)
    uploaded_file = request.FILES['file']
    
    attachment = service.store_attachment(
        file=uploaded_file,
        target=project,
        created_by=request.user
    )
    
    return {'id': attachment.id, 'name': attachment.original_name}
```

### Attach File to Item Comment

```python
from core.models import ItemComment

comment = ItemComment.objects.get(id=comment_id)

attachment = service.store_attachment(
    file=request.FILES['attachment'],
    target=comment,
    created_by=request.user
)
```

### Send Attachment via Email

```python
from core.services.storage import AttachmentStorageService

service = AttachmentStorageService()
attachment = Attachment.objects.get(id=attachment_id)

# Get file path for reading
file_path = service.get_file_path(attachment)

# Use with email/Graph API
with open(file_path, 'rb') as f:
    file_content = f.read()
    # Send via Graph Mail API or similar
```

### Share Attachment Between Targets

```python
# Attachment already exists on project
project_attachment = Attachment.objects.get(id=1)

# Link to item without duplicating file
service.link_attachment(
    attachment=project_attachment,
    target=item
)
```

## Size Limits

Default maximum file size is **25 MB**.

Override via:
1. Settings: `AGIRA_MAX_ATTACHMENT_SIZE_MB = 50`
2. Environment: `AGIRA_MAX_ATTACHMENT_SIZE_MB=50`
3. Service initialization: `AttachmentStorageService(max_size_mb=50)`

## Security Considerations

### Path Traversal Prevention
- All filenames are sanitized using `sanitize_filename()`
- Directory traversal attempts (`../`, etc.) are stripped
- Resolved paths are validated to be within `AGIRA_DATA_DIR`

### File Size Limits
- Enforced at upload time
- Prevents DoS via large file uploads
- Configurable per deployment needs

### Hash Verification
- SHA256 hashing enabled by default
- Useful for integrity verification
- Can detect duplicate files (future deduplication)

### Access Control
- Service doesn't enforce permissions (do this in views/APIs)
- Track `created_by` for audit trails
- Use `is_deleted` for soft deletes

## Error Handling

### Exception Classes

```python
from core.services.storage import (
    StorageError,           # Base exception
    AttachmentTooLarge,     # File too large
    AttachmentNotFound,     # File not found
    AttachmentWriteError,   # Cannot write file
)

try:
    attachment = service.store_attachment(file, target, created_by=user)
except AttachmentTooLarge as e:
    # Handle oversized file
    return {'error': str(e)}
except AttachmentWriteError as e:
    # Handle storage failure
    return {'error': 'Failed to save file'}
```

## Admin Interface

Attachments can be managed via Django Admin:

### Attachment Admin
- **List Display**: created_at, original_name, file size, created_by, is_deleted
- **Filters**: is_deleted, created_at
- **Search**: original_name, sha256
- **Read-only**: created_at, sha256, storage_path, file size

### AttachmentLink Admin
- **List Display**: attachment, role, target_content_type, target_object_id, created_at
- **Filters**: role, target_content_type, created_at
- **Search**: attachment__original_name

## Future Enhancements

Version 1 intentionally omits features that can be added later:

### Planned Features
- **Cloud Storage**: S3-compatible storage backend
- **Virus Scanning**: Integrate with ClamAV or similar
- **Deduplication**: Use SHA256 to avoid storing duplicate files
- **Image Processing**: Thumbnails, resizing for image attachments
- **Weaviate Integration**: Index document content for semantic search
- **Retention Policies**: Automatic cleanup of old/deleted files

### Extensibility
The service is designed to be extended without breaking existing code:
- Abstract storage backend interface
- Pluggable hash algorithms
- Custom path strategies
- Event hooks (pre/post upload, delete)

## Migration Notes

If migrating from the old `Attachment` model with `FileField`:

1. Old attachments used `project` FK and `file` FileField
2. New attachments use `AttachmentLink` for any target and `storage_path`
3. A data migration may be needed to:
   - Create AttachmentLink records for existing attachments
   - Copy files to new path structure
   - Update storage_path fields

## Testing

Comprehensive tests are available in `core/services/storage/test_storage.py`:

```bash
# Run all storage tests
python manage.py test core.services.storage --settings=agira.test_settings

# Run specific test class
python manage.py test core.services.storage.test_storage.AttachmentStorageServiceTestCase --settings=agira.test_settings
```

Test coverage includes:
- Filename sanitization
- Path generation
- File storage and retrieval
- Size limit enforcement
- Hash computation
- Link management
- Soft and hard deletes
- Error conditions

## Support

For issues or questions about the Attachment Storage Service:
1. Check this documentation
2. Review test cases for usage examples
3. Open an issue in the repository
