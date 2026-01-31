# Item ListView Migration to django-tables2 + django-filter

## Summary

Successfully migrated all status-based Item ListView implementations from manual HTML table rendering to use `django-tables2` and `django-filter` libraries. This provides consistent filtering, sorting, and pagination across all item list views.

## What Was Changed

### 1. Dependencies Added

**File: `requirements.txt`**
- Added `django-tables2>=2.7,<3.0` for table rendering and sorting
- Added `django-filter>=24.0,<25.0` for GET-based filtering

**File: `agira/settings.py`**
- Added `django_filters` and `django_tables2` to `INSTALLED_APPS`
- Added `DJANGO_TABLES2_TEMPLATE = "django_tables2/bootstrap5.html"`
- Added `ITEMS_PER_PAGE = 25` for pagination

### 2. New Infrastructure

#### ItemFilter (core/filters.py)
- FilterSet for Item model with the following filters:
  - `q`: Search filter (title or description)
  - `project`: Filter by project
  - `type`: Filter by item type
  - `organisation`: Filter by organisation
  - `requester`: Filter by requester
  - `assigned_to`: Filter by assigned user
- All filters use Bootstrap 5 form styling
- Search uses custom method for case-insensitive search

#### ItemTable (core/tables.py)
- Table class with sortable columns:
  - `updated_at`: Date/time formatted column
  - `title`: With link to item detail and truncated description
  - `type`: Displayed as badge
  - `project`: Project name
  - `organisation`: With em-dash for empty values
  - `requester`: With em-dash for empty values
  - `assigned_to`: With em-dash for empty values
- Custom rendering for better UX (badges, links, empty value handling)
- Uses Bootstrap 5 template
- Default ordering by `-updated_at`

#### StatusItemListView Base Class (core/views_items.py)
- Combines `LoginRequiredMixin`, `SingleTableMixin`, and `FilterView`
- Enforces status scope that cannot be removed via UI filters
- Pipeline order: **Status-Scope → Filter → Table**
- Provides distinct values for header-based filters
- Pagination with configurable page size
- Performance guardrails: Limits distinct values to 100 per field

#### Status-Specific View Classes
- `ItemsInboxView`: Items in inbox status
- `ItemsBacklogView`: Items in backlog status
- `ItemsWorkingView`: Items in working status
- `ItemsTestingView`: Items in testing status
- `ItemsReadyView`: Items ready for release
- `ItemsPlanningView`: Items in planning phase
- `ItemsSpecificationView`: Items in specification phase

Each view:
- Sets specific `item_status`
- Defines custom `page_title` and `page_description`
- Inherits all filtering, sorting, and pagination from base class

### 3. Unified Template (templates/items_list.html)

Features:
- Collapsible filter card with clear UI
- Active filters display with individual removal links
- Results count display
- Table rendering via `{% render_table table %}`
- Empty state with helpful message
- Pagination handled by django-tables2
- Bootstrap 5 styling throughout

### 4. URL Updates (core/urls.py)

Changed from function-based views to class-based views:
```python
# Before:
path('items/backlog/', views.items_backlog, name='items-backlog')

# After:
path('items/backlog/', views_items.ItemsBacklogView.as_view(), name='items-backlog')
```

### 5. Comprehensive Tests (core/test_item_listviews.py)

Added 16 tests covering:
- Status scope enforcement for all views
- Search filter functionality
- Project filter functionality
- Type filter functionality
- Multiple filters working together
- Status scope not removable via filters
- Pagination context
- Distinct values in context
- Login requirement
- Sorting via querystring

**All tests passing ✓**

## Technical Requirements Met

### ✅ Functional Requirements

- [x] **Status-Lists: Fixed Scope Pipeline**
  - Status scope is enforced in `get_queryset()` and cannot be removed
  - Order: Status-Scope → Filter → Table

- [x] **django-filter Integration**
  - ItemFilter created with all existing filters
  - Filters run via GET parameters
  - Filter parameters persist across sorting and pagination

- [x] **django-tables2 Integration**
  - ItemTable created with all columns
  - Sortable headers
  - All views use `{% render_table table %}`

- [x] **Pagination**
  - Enabled with 25 items per page
  - Paging links preserve filter and sort parameters

- [x] **Sorting**
  - Sortable via django-tables2
  - Sort parameters preserve filter and pagination parameters

- [x] **Header-Distinct-Filter Infrastructure**
  - `get_distinct_values()` method provides distinct values
  - Distinct values from status-scoped + filtered queryset
  - Performance guardrails: Limited to 100 distinct values per field
  - Ready for UI implementation (data provided in context)

### ✅ Technical Requirements

- [x] **Common Patterns Used**
  - `SingleTableMixin` for table integration
  - `FilterView` for filter integration
  - `LoginRequiredMixin` for authentication

- [x] **Common Base Class**
  - `StatusItemListView` reduces duplication
  - All status views inherit from it

- [x] **Common Templates**
  - Single `items_list.html` template for all views
  - Reusable across all status-based lists

- [x] **No Model Changes**
  - Only views, templates, and new supporting files

## What's Not Changed

- `items_github_open` view remains as-is (special case, not status-based)
- Item detail view (out of scope)
- Item creation (out of scope)
- Data models (as required)

## Migration Path for Existing Code

The old function-based views in `core/views.py` can be safely removed:
- `items_inbox()`
- `items_backlog()`
- `items_working()`
- `items_testing()`
- `items_ready()`
- `items_planning()`
- `items_specification()`

The old templates can also be removed:
- `templates/items_inbox.html`
- `templates/items_backlog.html`
- `templates/items_working.html`
- `templates/items_testing.html`
- `templates/items_ready.html`
- `templates/items_planning.html`
- `templates/items_specification.html`

**Note**: This should only be done after thorough manual testing confirms the new implementation works correctly.

## Acceptance Criteria Status

- [x] Each item ListView renders django-tables2 table (no manual HTML tables)
- [x] Table headers are sortable and sorting works
- [x] Filters via django-filter are active and work correctly (GET-based)
- [x] Pagination is active and preserves filter + sorting
- [x] Status lists show only items of respective status (scope enforced)
- [x] Header-distinct-filter infrastructure implemented (data in context)
- [x] No server errors / no missing template context keys
- [x] All tests passing (16/16)
- [x] Code review completed (1 comment addressed)
- [x] Security review completed (0 alerts from codeql_checker)

## Files Changed

1. `requirements.txt` - Added dependencies
2. `agira/settings.py` - Added apps and configuration
3. `core/filters.py` - New file with ItemFilter
4. `core/tables.py` - New file with ItemTable
5. `core/views_items.py` - New file with view classes
6. `core/urls.py` - Updated URL patterns
7. `templates/items_list.html` - New unified template
8. `core/test_item_listviews.py` - New comprehensive tests

## Performance Considerations

1. **Distinct Value Queries**: Limited to 100 results per field to prevent unbounded queries
2. **Select Related**: Base queryset uses `select_related()` for efficient database queries
3. **Pagination**: Limits results per page to 25 items
4. **Caching**: django-tables2 handles caching internally

## Next Steps for Manual Testing

1. Start development server
2. Create test data with various statuses
3. Verify each status view shows only correct items
4. Test filtering (search, project, type, etc.)
5. Test sorting by clicking column headers
6. Test pagination navigation
7. Verify filter + sort + page parameters persist
8. Test filter removal via badge links
9. Test clear all filters button
10. Verify UI matches existing design

## Security Summary

- **CodeQL Analysis**: 0 alerts
- All user input is sanitized through Django's ORM
- No raw SQL queries
- CSRF protection via Django forms
- Login required on all views
- No new security vulnerabilities introduced

## Conclusion

The migration is complete and ready for manual testing. All automated tests pass, code review is clean, and security analysis shows no issues. The implementation follows Django best practices and project conventions.
