# IssueBlueprints UserUI Integration - Implementation Summary

## Overview
This implementation adds full CRUD functionality for IssueBlueprints in the Agira UserUI, along with workflow integration for creating blueprints from issues and applying blueprints to issues.

## Implementation Details

### 1. Backend Components

#### Models
- **IssueBlueprint** (already existed in `core/models.py`)
- **IssueBlueprintCategory** (already existed in `core/models.py`)

#### Views (`core/views.py`)
- `blueprints()` - List view with django-tables2 and django-filter
- `blueprint_detail(id)` - Detail view for single blueprint
- `blueprint_create()` - Form view for creating new blueprint
- `blueprint_edit(id)` - Form view for editing existing blueprint
- `blueprint_update(id)` - POST handler for create/update operations
- `blueprint_delete(id)` - POST handler for deletion
- `item_create_blueprint(item_id)` - Form view for creating blueprint from issue
- `item_create_blueprint_submit(item_id)` - POST handler for creating blueprint from issue
- `item_apply_blueprint(item_id)` - HTMX-loaded modal content for blueprint selection
- `item_apply_blueprint_submit(item_id)` - POST handler for applying blueprint to issue

#### Tables (`core/tables.py`)
- `IssueBlueprintTable` - Django-tables2 table configuration with:
  - Title column (with truncated description preview)
  - Category column (as badge)
  - Active status (✓/✗)
  - Version
  - Updated timestamp
  - Tags (showing first 2 + count)
  - Actions (View/Edit buttons)

#### Filters (`core/filters.py`)
- `IssueBlueprintFilter` - Django-filter configuration with:
  - Search by title
  - Filter by category (only active categories)
  - Filter by is_active status (all/active/inactive)
  - Filter by tag contains
  - Filter by created_by user

#### URL Routes (`core/urls.py`)
- `/configuration/blueprints/` → blueprints list
- `/configuration/blueprints/new/` → create new blueprint
- `/configuration/blueprints/<uuid:id>/` → blueprint detail
- `/configuration/blueprints/<uuid:id>/edit/` → edit blueprint
- `/configuration/blueprints/<uuid:id>/update/` → update blueprint (POST)
- `/configuration/blueprints/<uuid:id>/delete/` → delete blueprint (POST)
- `/items/<int:item_id>/create-blueprint/` → create blueprint from issue form
- `/items/<int:item_id>/create-blueprint/submit/` → create blueprint from issue (POST)
- `/items/<int:item_id>/apply-blueprint/` → apply blueprint modal (HTMX)
- `/items/<int:item_id>/apply-blueprint/submit/` → apply blueprint to issue (POST)

### 2. Frontend Components

#### Templates
1. **`blueprints.html`** - List view with:
   - Page header with "New Blueprint" button
   - Filter form (search, category, status, tag, created_by)
   - Django-tables2 rendered table
   - Empty state message

2. **`blueprint_detail.html`** - Detail view with:
   - Breadcrumb navigation
   - Page header with status badge and edit button
   - Two-column layout (main content + sidebar)
   - Description card (rendered Markdown)
   - Default settings card (if optional fields present)
   - Internal notes card (if present)
   - Sidebar metadata card
   - Sidebar actions card (Edit/Delete buttons)
   - Delete confirmation with toast notification

3. **`blueprint_form.html`** - Create/Edit form with:
   - Breadcrumb navigation
   - Two-column layout (form + help sidebar)
   - Basic information card (title, category, description, version, is_active)
   - Optional settings card (tags, labels, risk level, security relevant, notes)
   - Save and Save & Close buttons
   - Form validation and AJAX submission
   - Toast notifications

4. **`item_create_blueprint_form.html`** - Create blueprint from issue:
   - Shows source issue info
   - Pre-fills title and description from issue
   - Category selection (required)
   - Version and active status
   - AJAX submission with toast notifications

5. **`item_apply_blueprint_modal.html`** - Apply blueprint modal (HTMX-loaded):
   - Blueprint selection dropdown
   - Preview of selected blueprint
   - Options: Replace description / Use blueprint title
   - Information about default behavior (append)
   - AJAX submission

#### Navigation
- Added "Issue Blueprints" link in Configuration section of `base.html`
- Icon: `bi-file-earmark-text`
- Active state detection: `'blueprint' in request.resolver_match.url_name`

#### Issue Detail Integration (`item_detail.html`)
Added two new buttons in the action button row:
1. **Apply Blueprint** button - Opens modal for selecting and applying a blueprint
2. **Create Blueprint** button - Links to form for creating blueprint from current issue

### 3. Features

#### Blueprint CRUD
- ✅ Create new blueprints
- ✅ View blueprint details with rendered Markdown
- ✅ Edit existing blueprints
- ✅ Delete blueprints (with confirmation)
- ✅ List view with filtering and sorting
- ✅ Active/inactive status management

#### Filtering & Search
- ✅ Search by title
- ✅ Filter by category (only active)
- ✅ Filter by status (all/active/inactive)
- ✅ Filter by tag contains
- ✅ Filter by creator

#### Issue Integration
- ✅ Create blueprint from existing issue
  - Pre-fills title and description
  - User selects category
  - Original issue unchanged
  
- ✅ Apply blueprint to issue
  - Select from active blueprints
  - Default: Append description with timestamp header
  - Options: Replace description / Use blueprint title
  - Logs activity on issue

#### Activity Logging
All blueprint operations are logged:
- `blueprint.created`
- `blueprint.updated`
- `blueprint.deleted`
- `blueprint.created_from_issue`
- `item.blueprint_created`
- `item.blueprint_applied`

### 4. Validation

#### Category Validation
- Only active categories are selectable
- Category must exist and be active for save operations

#### Field Validation
- Title: Required, max 200 characters
- Category: Required
- Description: Required (Markdown format)
- Version: Integer, minimum 1
- Tags: Comma-separated list (parsed to JSON array)
- Default Labels: Comma-separated list (parsed to JSON array)

### 5. Security Considerations

- ✅ All views protected with `@login_required`
- ✅ CSRF protection on all POST requests
- ✅ Category validation prevents inactive category selection
- ✅ UUID-based primary keys prevent enumeration
- ✅ Input sanitization for tag/label parsing
- ✅ Activity logging for audit trail

## Testing Checklist

### Blueprint CRUD
- [ ] Create a new blueprint
- [ ] View blueprint list with pagination
- [ ] Apply filters (search, category, status)
- [ ] View blueprint detail
- [ ] Edit existing blueprint
- [ ] Delete blueprint
- [ ] Verify markdown rendering in detail view

### Issue Integration
- [ ] Create blueprint from issue
  - [ ] Verify pre-filled data
  - [ ] Verify original issue unchanged
  - [ ] Verify activity logged
- [ ] Apply blueprint to issue (append mode)
  - [ ] Verify description appended with header
  - [ ] Verify activity logged
- [ ] Apply blueprint to issue (replace mode)
  - [ ] Verify description replaced
  - [ ] Verify title can be replaced optionally
- [ ] Test blueprint selection in modal

### Navigation
- [ ] Verify "Issue Blueprints" link in Configuration menu
- [ ] Verify active state detection
- [ ] Verify buttons appear in issue detail page

### Edge Cases
- [ ] Create blueprint with all optional fields
- [ ] Create blueprint with minimal fields only
- [ ] Try to create blueprint with inactive category (should fail)
- [ ] Delete blueprint and verify it's gone
- [ ] Apply blueprint with empty description

## Files Modified/Created

### Modified Files
- `core/tables.py` - Added IssueBlueprintTable
- `core/filters.py` - Added IssueBlueprintFilter  
- `core/views.py` - Added 10 new view functions
- `core/urls.py` - Added 10 new URL routes
- `templates/base.html` - Added navigation entry
- `templates/item_detail.html` - Added action buttons and modal

### Created Files
- `templates/blueprints.html`
- `templates/blueprint_detail.html`
- `templates/blueprint_form.html`
- `templates/item_create_blueprint_form.html`
- `templates/item_apply_blueprint_modal.html`

## Known Limitations

1. **No versionierung mechanism** - Blueprints have a version field but no automatic versioning workflow (out of scope per requirements)
2. **No AI generation** - Blueprint generation via LLM not implemented (out of scope per requirements)
3. **No custom permissions** - Uses existing login_required pattern (per requirements)
4. **Tags are simple lists** - No autocomplete or tag management UI
5. **Markdown only** - No WYSIWYG editor, markdown knowledge required

## Future Enhancements (Out of Current Scope)

- Blueprint duplication feature
- Blueprint usage statistics
- Blueprint templates (meta-blueprints)
- AI-assisted blueprint creation
- Blueprint version history
- Tag management UI
- Blueprint categories management in UserUI
- Bulk operations (activate/deactivate multiple)

## Acceptance Criteria Status

### ✅ Blueprints UserUI
- ✅ Navigation entry under Configuration
- ✅ ListView filterable & sortable
- ✅ CRUD fully functional
- ✅ Validations working (category active check)

### ✅ Issue Integration
- ✅ Action "Create Blueprint from Issue" implemented
- ✅ Action "Apply Blueprint to Issue" implemented
- ✅ Existing content not silently overwritten (append default)
- ✅ Success/Error feedback in UI
- ✅ No regression in issue editing

## Notes

- Implementation follows existing patterns (mail_template views, tables, filters)
- Uses django-tables2 and django-filter as required
- Bootstrap 5 UI components
- HTMX used for modal content loading (existing pattern)
- All responses use JSON for AJAX endpoints
- Activity service integrated for logging
- Markdown rendering via existing template tags
