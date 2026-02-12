# HTMX Status Updates for Recent Items Sidebar - Implementation Summary

## Overview
This implementation adds automatic status updates for items in the right sidebar "Recent Items" section using HTMX polling.

## Changes Made

### 1. Status Endpoint (`/items/{id}/status/`)

**File:** `core/views.py`
- Added `item_status()` view function that returns the current status of an item as HTML fragment
- Uses `@login_required` decorator for authentication
- Returns 404 for non-existent items
- Uses existing `item_status_badge.html` template for consistent rendering

**File:** `core/urls.py`
- Added URL route: `path('items/<int:item_id>/status/', views.item_status, name='item-status')`

### 2. Sidebar Recent Items JavaScript Updates

**File:** `static/js/sidebar-recents.js`
- Modified `renderEntry()` function to add HTMX attributes to status container
- Each status element gets:
  - Unique ID: `id="recent-status-{item_id}"`
  - HTMX get endpoint: `hx-get="/items/{item_id}/status/"`
  - Polling trigger: `hx-trigger="load, every 30s"`
  - Swap strategy: `hx-swap="innerHTML"`
- Only applies HTMX to issue-type items (not projects)
- Added `htmx.process(container)` call after rendering to enable HTMX on dynamically generated content

### 3. CSS for Layout Stability

**File:** `static/css/site.css`
- Added `min-width: 80px` to `.recents-entry-status`
- Added `display: inline-block` and `text-align: left`
- Prevents layout shift when status text changes length

### 4. Tests

**File:** `core/test_item_status_endpoint.py`
- Created comprehensive test suite with 4 tests:
  - Authentication requirement
  - Status display
  - Status updates
  - 404 for non-existent items
- All tests passing ✓

## How It Works

1. **Initial Page Load:**
   - User visits any page with the sidebar
   - JavaScript loads recent items from localStorage
   - For each item, status container is rendered with HTMX attributes
   - HTMX processes the container and triggers initial load

2. **Status Update Flow:**
   - HTMX sends GET request to `/items/{id}/status/`
   - Server retrieves item from database
   - Server renders `item_status_badge.html` with current status
   - HTMX replaces `innerHTML` of status container
   - Process repeats every 30 seconds

3. **Security:**
   - Endpoint requires authentication (`@login_required`)
   - Uses same authorization logic as `item_detail` view
   - Returns 404 for non-existent items

## Example HTMX Markup Generated

```html
<span 
    id="recent-status-123" 
    class="recents-entry-status"
    hx-get="/items/123/status/"
    hx-trigger="load, every 30s"
    hx-swap="innerHTML">📥 Inbox</span>
```

## Benefits

- ✅ Automatic status updates without page reload
- ✅ Minimal server load (only status fragment, not full page)
- ✅ No layout shifts (fixed width CSS)
- ✅ Consistent with existing HTMX patterns in the codebase
- ✅ Properly authorized (login required)
- ✅ Well-tested (unit tests)

## Acceptance Criteria Met

- [x] Status updates per HTMX after initial render
- [x] Status reflects current DB value
- [x] Update without full page reload (only status fragment)
- [x] Endpoint secured with existing authorization logic
- [x] No visible UI artifacts (stable layout)
- [x] Updates on page load and every 30 seconds

## Testing

Run the test suite:
```bash
python manage.py test core.test_item_status_endpoint --settings=agira.test_settings
```

All 4 tests pass successfully.
