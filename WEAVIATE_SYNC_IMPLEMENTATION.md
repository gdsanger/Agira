# Weaviate Auto-Sync + UI Status Implementation

## Overview

This document describes the implementation of automatic Weaviate synchronization for Agira objects with UI status indicators and manual push capabilities, following the pattern established by similar features like the IdeaGraph integration.

**Implementation Date:** January 2026  
**Version:** v1.0

## Features

### Automatic Synchronization

All Agira objects are automatically synchronized to Weaviate when:
- **Created or Updated:** Django signals (`post_save`) trigger automatic upsert to Weaviate
- **Deleted:** Django signals (`post_delete`) trigger automatic deletion from Weaviate
- **Transaction Safety:** Uses `transaction.on_commit()` to ensure DB commits before Weaviate sync

### UI Status Indicators

Visual indicators show the Weaviate sync status for each object:
- **Green Button:** Object exists in Weaviate (synced)
- **Red Button:** Object not found in Weaviate (not synced)
- **Gray Button:** Weaviate service is disabled/not configured

### Manual Sync

Users can manually trigger synchronization via:
- **Status Button:** Click opens a modal showing sync status
- **Push Button:** Appears when object is not synced, triggers immediate sync
- **Re-sync Button:** Appears when object is synced, allows manual re-synchronization

## Architecture

### Supported Object Types

The following Django models are synchronized to Weaviate:
1. **Item** (`item`) - Issue/ticket items
2. **ItemComment** (`comment`) - Comments on items
3. **Attachment** (`attachment`) - File attachments
4. **Project** (`project`) - Project definitions
5. **Change** (`change`) - Change management records
6. **Node** (`node`) - Architecture/structure nodes
7. **Release** (`release`) - Release records
8. **ExternalIssueMapping** (`github_issue` / `github_pr`) - GitHub issue/PR mappings

### Core Components

#### 1. Service Layer (`core/services/weaviate/service.py`)

**New Public Functions:**

```python
# Get Weaviate type string for a model instance
get_weaviate_type(instance) -> str | None

# Check if instance exists in Weaviate
exists_instance(instance) -> bool

# Check if object exists by type and ID
exists_object(type: str, object_id: str) -> bool

# Fetch Weaviate object data for instance
fetch_object(instance) -> dict | None

# Fetch object data by type and ID
fetch_object_by_type(type: str, object_id: str) -> dict | None
```

**Key Features:**
- Deterministic UUID generation using UUID5 namespace
- Idempotent operations (same input = same UUID)
- Graceful error handling (never breaks DB operations)
- Client connection management with proper cleanup

#### 2. Django Signals (`core/services/weaviate/signals.py`)

**Enhanced Signal Handling:**

```python
@receiver(post_save, sender='core.Item')
def sync_item_to_weaviate(sender, instance, created, **kwargs):
    """Sync Item to Weaviate on save."""
    _safe_upsert(instance)

@receiver(post_delete, sender='core.Item')
def delete_item_from_weaviate(sender, instance, **kwargs):
    """Delete Item from Weaviate on delete."""
    _safe_delete(sender, instance)
```

**Safety Features:**
- `transaction.on_commit()` ensures DB transaction completes first
- Exception handling prevents signal failures from breaking saves
- Checks `is_available()` before attempting sync
- Detailed error logging for debugging

#### 3. HTMX Endpoints (`core/views.py`)

**New Views:**

```python
# GET: Check sync status and return button HTML
weaviate_status(request, object_type, object_id)

# GET: Fetch object data and return modal content
weaviate_object(request, object_type, object_id)

# POST: Manually push object to Weaviate
weaviate_push(request, object_type, object_id)
```

**URL Routes:**
```python
path('weaviate/status/<str:object_type>/<str:object_id>/', views.weaviate_status)
path('weaviate/object/<str:object_type>/<str:object_id>/', views.weaviate_object)
path('weaviate/push/<str:object_type>/<str:object_id>/', views.weaviate_push)
```

### Frontend Components

#### 1. Status Button (`templates/partials/weaviate_button.html`)

Reusable button component that:
- Loads status via HTMX on page load
- Shows green/red indicator based on sync status
- Opens modal on click
- Updates when object is synced

**Usage:**
```html
<div 
    hx-get="{% url 'weaviate-status' 'item' item.id %}"
    hx-trigger="load"
    hx-swap="innerHTML">
    <!-- Button will be loaded here -->
</div>
```

#### 2. Modal Content (`templates/partials/weaviate_modal_content.html`)

Dynamic modal content showing:
- **Synced Object:** JSON data viewer + Re-sync button
- **Unsynced Object:** Warning message + Push to Weaviate button
- **Error State:** Error message display
- **Success State:** Confirmation message after sync

**Features:**
- CSRF protection via `hx-headers`
- Pretty-printed JSON display
- Real-time updates via HTMX swap

#### 3. Modal Container (`templates/partials/weaviate_modal.html`)

Bootstrap 5.3 modal structure:
- Loading spinner while fetching data
- Consistent styling across pages
- Accessible (ARIA labels)
- Responsive design

### Integration Points

#### Item Detail Page

```html
<!-- Header button -->
<div 
    hx-get="{% url 'weaviate-status' 'item' item.id %}"
    hx-trigger="load"
    hx-swap="innerHTML">
</div>

<!-- Modal at page bottom -->
{% include 'partials/weaviate_modal.html' %}
```

#### Project Detail Page

Same pattern as Item Detail, with `object_type='project'`

#### Comments Tab

Button appears next to each comment timestamp:
```html
<div class="d-flex gap-2 align-items-center">
    <small class="text-muted">{{ comment.created_at|date:"Y-m-d H:i" }}</small>
    <div hx-get="{% url 'weaviate-status' 'comment' comment.id %}" ...>
    </div>
</div>
```

#### Attachments Tab

Button appears in dedicated table column:
```html
<thead>
    <tr>
        <th>Filename</th>
        <th>Size</th>
        <th>Uploaded</th>
        <th>Uploaded By</th>
        <th>Weaviate</th>  <!-- New column -->
    </tr>
</thead>
```

## Data Flow

### Automatic Sync Flow

```
1. User saves/creates object in Django
   ↓
2. Django commits to database
   ↓
3. post_save signal fires
   ↓
4. transaction.on_commit() callback queued
   ↓
5. DB transaction completes
   ↓
6. Weaviate sync executes:
   - Serialize Django object
   - Generate deterministic UUID
   - Upsert to Weaviate
   ↓
7. On error: Log but don't break
```

### Manual Sync Flow (Push Button)

```
1. User clicks "Push to Weaviate" button
   ↓
2. HTMX POST to /weaviate/push/<type>/<id>/
   ↓
3. View loads Django object by type/ID
   ↓
4. Serialize and upsert to Weaviate
   ↓
5. Fetch newly created object
   ↓
6. Return modal content with JSON + success message
   ↓
7. HTMX swaps modal body (button now shows green)
```

### Status Check Flow

```
1. Page loads with HTMX trigger
   ↓
2. GET /weaviate/status/<type>/<id>/
   ↓
3. Check Weaviate for object existence:
   - Generate deterministic UUID
   - Query Weaviate by UUID
   ↓
4. Return button HTML (green/red/gray)
   ↓
5. HTMX swaps into placeholder div
```

## Configuration

### Weaviate Setup

Weaviate must be configured in Django admin:

1. Navigate to **Admin → Weaviate Configuration**
2. Set the following:
   - **URL:** Weaviate instance URL (e.g., `http://localhost:8080` or `http://192.168.1.100`)
   - **HTTP Port:** Port for HTTP connections (default: 8080, local installs often use 8081)
   - **gRPC Port:** Port for gRPC connections (default: 50051)
   - **API Key:** Optional authentication key (leave empty for local installations without auth)
   - **Enabled:** Check to enable Weaviate integration

**Example for Local Installation:**
- URL: `http://192.168.1.100`
- HTTP Port: `8081`
- gRPC Port: `50051`
- API Key: (empty)
- Enabled: ✓

### Feature Toggle

The feature gracefully degrades when Weaviate is disabled:
- Auto-sync signals check `is_available()` before syncing
- UI buttons show gray "disabled" state
- Manual sync operations return helpful error messages

## Testing

### Unit Tests

Comprehensive tests in `core/services/weaviate/test_weaviate.py`:

```python
class GetWeaviateTypeTestCase(TestCase):
    """Test get_weaviate_type function."""
    # Tests for type detection

class ExistsObjectTestCase(TestCase):
    """Test exists_object and exists_instance."""
    # Tests for existence checking

class FetchObjectTestCase(TestCase):
    """Test fetch_object and fetch_object_by_type."""
    # Tests for object fetching
```

**Coverage:**
- ✅ Type detection for all models
- ✅ Object existence checking with mocked Weaviate
- ✅ Object fetching with error handling
- ✅ Deterministic UUID generation
- ✅ Error scenarios (not found, connection errors)

### Manual Testing Checklist

- [ ] Create new item → Verify auto-sync to Weaviate
- [ ] Update existing item → Verify re-sync
- [ ] Delete item → Verify deletion from Weaviate
- [ ] Check status button colors (green/red/gray)
- [ ] Click button → Modal opens with correct content
- [ ] Push unsynced object → Status changes to green
- [ ] Re-sync existing object → New data appears
- [ ] Test with Weaviate disabled → Gray buttons appear
- [ ] Test all object types (Item, Project, Comment, Attachment)

## Security

### CodeQL Analysis

✅ **No security alerts** - Passed CodeQL scan

### CSRF Protection

All POST endpoints use Django CSRF protection:
```html
<button hx-post="..." hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>
```

### Error Handling

- Service exceptions don't expose internal details
- Graceful degradation when Weaviate unavailable
- No sensitive data logged in error messages

## Performance Considerations

### Optimizations

1. **Schema Caching:** `_schema_ensured` flag prevents redundant schema checks
2. **Deterministic UUIDs:** No database lookups needed for sync
3. **Lazy Loading:** Status checks only run when UI requests them
4. **Connection Management:** Client properly closed after each operation

### Potential Future Improvements

1. **Batch Sync:** Add management command for bulk re-sync
2. **Status Caching:** Cache sync status in DB (WeaviateSyncState table)
3. **Background Workers:** Use Celery for async sync
4. **Retry Logic:** Add exponential backoff for failed syncs

## Migration Path

### From No Weaviate Sync

1. Deploy code changes
2. Configure Weaviate in admin
3. Enable feature (Weaviate Configuration → Enabled)
4. Objects sync automatically on next save

### Initial Data Load

For existing data, run sync command (if implemented):
```bash
python manage.py sync_weaviate --project-id=1
```

Or use the existing service API:
```python
from core.services.weaviate.service import sync_project
stats = sync_project(project_id="1")
# Returns: {'item': 42, 'comment': 15, 'change': 3, ...}
```

## Troubleshooting

### Common Issues

**Issue:** Buttons show gray (disabled)  
**Solution:** Check Weaviate Configuration in admin, ensure enabled and URL is set

**Issue:** Auto-sync not working  
**Solution:** Check logs for signal errors, verify `transaction.on_commit()` is being called

**Issue:** Modal shows "Connection error"  
**Solution:** Verify Weaviate service is running and accessible

**Issue:** Objects not found after sync  
**Solution:** Check Weaviate logs, verify schema is created, check UUID generation

### Debug Commands

```python
# Check if service is available
from core.services.weaviate.client import is_available
print(is_available())  # Should return True

# Test object sync
from core.models import Item
from core.services.weaviate.service import exists_instance, upsert_instance
item = Item.objects.get(pk=1)
upsert_instance(item)
print(exists_instance(item))  # Should return True

# Fetch object data
from core.services.weaviate.service import fetch_object
data = fetch_object(item)
print(data)  # Should show object properties
```

## Maintenance

### Regular Tasks

- Monitor Weaviate disk usage (vector database can grow large)
- Review sync error logs periodically
- Update schema if new fields are added to models
- Test feature after Django/Weaviate upgrades

### Schema Updates

If model fields change, update serializers in:
`core/services/weaviate/serializers.py`

Then recreate Weaviate collection or add migration.

## References

- **Weaviate Docs:** https://weaviate.io/developers/weaviate
- **Django Signals:** https://docs.djangoproject.com/en/5.0/topics/signals/
- **HTMX:** https://htmx.org/docs/
- **Bootstrap 5.3 Modals:** https://getbootstrap.com/docs/5.3/components/modal/

## Implementation Summary

**Total Changes:**
- 7 new service functions
- 3 new view endpoints
- 3 new UI templates
- 4 page integrations
- 197 lines of tests

**Files Modified:**
- `core/services/weaviate/service.py` - Core sync logic
- `core/services/weaviate/signals.py` - Signal handlers
- `core/views.py` - HTMX endpoints
- `core/urls.py` - URL routing
- `templates/item_detail.html` - Item page integration
- `templates/project_detail.html` - Project page integration
- `templates/partials/item_comments_tab.html` - Comment buttons
- `templates/partials/item_attachments_tab.html` - Attachment buttons

**New Files:**
- `templates/partials/weaviate_button.html`
- `templates/partials/weaviate_modal.html`
- `templates/partials/weaviate_modal_content.html`

**Test Coverage:**
- Unit tests for all new service functions
- Mocked Weaviate client for isolation
- Edge case coverage (errors, not found, etc.)
