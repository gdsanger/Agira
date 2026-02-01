# Customer Portal Embed Enhancements - Implementation Summary

## Overview
This implementation addresses issue #211: Comprehensive enhancements to the Customer Portal Embed, including migration to django-tables2/django-filter, KPI dashboard, new "Solution Release" column, and critical security improvements to hide internal items.

## Changes Made

### 1. Django Tables2/Filters Migration (A1)

#### Files Modified:
- **core/tables.py**: Added `EmbedItemTable` class
  - Columns: ID, Title, Type, Status, Updated, Solution Release, Solution
  - Custom renderers for badges, links, and solution indicators
  - Token-aware URL generation for embed portal

- **core/filters.py**: Added `EmbedItemFilter` class
  - Filter fields: search (q), status, type
  - Custom status filter supporting 'closed' and 'not_closed'
  - **Security**: Overridden `qs` property to always exclude `intern=True` items

- **core/views_embed.py**: Updated `embed_project_issues` view
  - Migrated from manual filtering/sorting/pagination to django-tables2/django-filter
  - Uses `RequestConfig` for table pagination (25 items per page)
  - Calculates KPIs for dashboard display
  - **Security**: Base queryset filters `intern=False`

- **templates/embed/issue_list.html**: Complete rewrite
  - Now uses `{% render_table table %}` for table rendering
  - Filter form integrated with django-filter
  - Added collapsible KPI card
  - Maintains solution modals for backward compatibility

### 2. Solution Release Column (A2)

#### Implementation:
- Added `solution_release` column to `EmbedItemTable`
- Column displays release version from related `Release` model
- Shows "—" (em dash) when no release is assigned
- **Removed**: `assigned_to` column from embed table (replaced by solution_release)

### 3. Security: Internal Items Filtering (A3)

#### Security Measures:
All views and querysets now exclude items where `intern=True`:

1. **embed_project_issues**: Base queryset filters `intern=False`
2. **embed_issue_detail**: Queryset filters `intern=False` (returns 404 for internal items)
3. **EmbedItemFilter**: `qs` property override ensures fail-safe filtering
4. **embed_project_releases**: Filters `intern=False` when getting release items
5. **KPI calculations**: Only count non-internal items

This is a **defense-in-depth** approach: even if filters are bypassed, the base queryset ensures security.

### 4. KPI Card (B)

#### Implementation:
- **Location**: Between page header and item list
- **UI**: Collapsible card, default expanded
- **4 KPIs displayed**:
  1. **Open Items**: Count of items not in CLOSED status
  2. **Closed (30d)**: Items closed within last 30 days (based on `updated_at`)
  3. **Inbox**: Items in INBOX status
  4. **Backlog**: Items in BACKLOG status

#### Tooltips:
Each KPI box has a Bootstrap tooltip explaining its meaning:
- "Total number of items that are not closed"
- "Items closed within the last 30 days"
- "Items in Inbox status - newly created items awaiting triage"
- "Items in Backlog status - items planned for future work"

#### Security:
All KPI counts exclude `intern=True` items.

### 5. Releases Page (C)

#### New Files:
- **templates/embed/releases.html**: New template for releases view
- **core/views_embed.py**: Added `embed_project_releases` view
- **core/urls.py**: Added URL pattern `embed-project-releases`

#### Features:
- **Grouped/Collapsible**: Bootstrap accordion showing releases
- **Release Metadata**: Name, Version (badge), Planned Date
- **Item Count**: Badge showing number of items per release
- **Items Table**: Expandable list of items in each release
  - Columns: ID, Title, Type, Status, Updated, Solution indicator
  - Links to item detail pages
- **Solution Modal**: Same as issue list, with Bleach sanitization via `render_markdown` filter
- **Navigation**: Added tabs in base template for Issues/Releases

#### Security:
- Release items filtered with `intern=False`
- Solution descriptions sanitized via existing `render_markdown` template filter (uses Bleach)

### 6. Navigation Enhancement

#### Files Modified:
- **templates/embed/base.html**: Added navigation tabs
  - "Issues" tab (links to issue list)
  - "Releases" tab (links to releases page)
  - Active state highlighting based on current URL

### 7. Tests (Tests Section)

#### New Test Suite:
- **core/test_embed_endpoints.py**: Added `EmbedInternalItemsSecurityTestCase`

#### Test Methods (7 tests):
1. `test_internal_item_not_in_issues_list`: Verifies internal items don't appear in list
2. `test_internal_item_not_accessible_via_detail_view`: Verifies 404 for internal item access
3. `test_public_item_accessible_via_detail_view`: Verifies public items are accessible
4. `test_internal_item_not_in_filtered_results`: Tests filtering doesn't leak internal items
5. `test_internal_item_not_in_search_results`: Tests search doesn't leak internal items
6. `test_kpis_exclude_internal_items`: Verifies KPI counts exclude internal items
7. `test_releases_page_excludes_internal_items`: Verifies releases page excludes internal items

## Technical Details

### Status Definitions
Based on `ItemStatus` enum in `core/models.py`:
- **Open**: Any status except CLOSED
- **Closed**: ItemStatus.CLOSED
- **Inbox**: ItemStatus.INBOX
- **Backlog**: ItemStatus.BACKLOG

### Date Field for "Closed < 30 days"
- Uses `updated_at` field (no `closed_at` field exists)
- Filters: `status=CLOSED AND updated_at >= now() - 30 days`

### Field Name
- The boolean field is `intern` (not `internal`)
- Security filter: `.filter(intern=False)`

### Bleach Sanitization
- Solution descriptions use existing `render_markdown` template filter
- This filter applies Bleach HTML sanitization
- Configured in template filters (agira_filters)

## Acceptance Criteria Status

✅ 1. Issue list uses django-tables2 + django-filter with sorting/pagination  
✅ 2. "Solution Release" column added, shows version or "—"  
✅ 3. KPI Card visible, collapsible (default open), 4 KPIs with tooltips  
✅ 4. Internal items (intern=True) hidden throughout embed portal  
✅ 5. Releases page accessible, grouped/collapsible, shows metadata + items  
✅ 6. Solution indicator + modal work on releases page, sanitized  
✅ 7. Tests added for intern=True filtering (7 test methods)  

## Files Changed

### Modified:
- core/filters.py (added EmbedItemFilter)
- core/tables.py (added EmbedItemTable)
- core/views_embed.py (updated embed_project_issues, embed_issue_detail, added embed_project_releases)
- core/urls.py (added releases URL pattern)
- core/test_embed_endpoints.py (added security test suite)
- templates/embed/base.html (added navigation tabs)
- templates/embed/issue_list.html (complete rewrite for tables2/KPIs)

### Created:
- templates/embed/releases.html (new releases page)
- templates/embed/issue_list_old.html (backup of original template)

## Security Highlights

This implementation follows a **defense-in-depth** security approach for hiding internal items:

1. **Base Queryset Filtering**: All embed views filter `intern=False` at queryset level
2. **FilterSet Override**: `EmbedItemFilter.qs` property ensures filtering even if bypassed
3. **Detail View**: Returns 404 instead of showing internal items
4. **KPI Calculations**: Separate queryset with `intern=False` filter
5. **Releases Page**: Filters internal items when building release lists

**Critical**: No matter what query parameters or filters are applied, internal items can never be shown in the customer portal.

## Notes

### Clarified Requirements
During implementation, the following unclear points were addressed:

1. **Column to remove**: Removed "Assigned To" column (replaced with "Solution Release")
2. **Status definitions**: Derived from ItemStatus enum
3. **Closed date field**: Used `updated_at` (no `closed_at` exists)
4. **Field name**: Confirmed as `intern` not `internal`
5. **Releases URL**: Implemented as `/embed/projects/<id>/releases/?token=...`

### Bootstrap 5.3
All UI components use Bootstrap 5.3 features:
- Accordion for releases
- Tooltips for KPIs
- Collapsible card for KPIs
- Tabs for navigation
- Dark theme (data-bs-theme="dark")

### Database Requirements
- PostgreSQL database required for tests
- Tests cannot run in current environment (no DB)
- All code has valid Python syntax (verified)
- Templates have valid Django syntax (verified manually)

## Testing Instructions

To run tests when database is available:

```bash
python manage.py test core.test_embed_endpoints.EmbedInternalItemsSecurityTestCase
```

To verify all embed endpoint tests:

```bash
python manage.py test core.test_embed_endpoints
```

## Migration Notes

No database migrations required:
- Uses existing `intern` field on Item model
- Uses existing `solution_release` field on Item model
- Uses existing Release model
- No schema changes needed
