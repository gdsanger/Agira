# Blueprint Import/Export Feature - Implementation Summary

## Overview

This implementation provides a robust Import/Export feature for IssueBlueprints, enabling blueprints to be shared between different Agira instances or used as backups.

## Features

### 1. Export Functionality

**Location:** `/configuration/blueprints/<id>/export/`

**Access:**
- From blueprint detail page: Click "Export Blueprint" button in the Actions sidebar
- Direct URL access with blueprint UUID

**Output:**
- JSON file download with automatic filename: `blueprint_<title>_v<version>.json`
- Versioned schema (currently v1.0)
- Deterministic output (same blueprint always produces identical JSON)
- Includes all blueprint data needed for reproduction

**Example Export JSON:**
```json
{
  "schema_version": "1.0",
  "blueprint": {
    "category": {
      "name": "Features",
      "slug": "features"
    },
    "default_labels": ["backend", "security"],
    "default_risk_level": "High",
    "default_security_relevant": true,
    "description_md": "# API Rate Limiting\n\nImplement rate limiting for API endpoints.",
    "is_active": true,
    "notes": "Critical security feature",
    "tags": ["security", "api"],
    "title": "API Rate Limiting",
    "version": 1
  }
}
```

### 2. Import Functionality

**Location:** `/configuration/blueprints/import/`

**Access:**
- From blueprints list page: Click "Import Blueprint" button
- Direct URL access

**Import Methods:**
1. **File Upload** - Upload a `.json` file
2. **Text Paste** - Paste JSON content directly

**Options:**
- **Update if exists**: When enabled, updates an existing blueprint with the same title and category instead of creating a new one

**Behavior:**
- Validates JSON structure and schema version
- Automatically creates missing categories (using slug as identifier)
- Handles unknown fields gracefully (ignores them)
- Sets default values for missing optional fields
- Logs activity for audit trail

### 3. JSON Schema (v1.0)

**Required Fields:**
- `schema_version` (string): "1.0"
- `blueprint.title` (string): Blueprint title
- `blueprint.description_md` (string): Markdown description
- `blueprint.category.name` (string): Category name
- `blueprint.category.slug` (string): Category slug (used as identifier)

**Optional Fields:**
- `blueprint.is_active` (boolean, default: true)
- `blueprint.version` (integer, default: 1)
- `blueprint.tags` (array of strings, default: null)
- `blueprint.default_labels` (array of strings, default: null)
- `blueprint.default_risk_level` (string, default: null)
  - Valid values: "Low", "Normal", "High", "VeryHigh"
- `blueprint.default_security_relevant` (boolean, default: null)
- `blueprint.notes` (string, default: "")

## Implementation Details

### Core Components

1. **`core/utils/blueprint_serializer.py`**
   - `export_blueprint()` - Converts IssueBlueprint to dict
   - `export_blueprint_json()` - Converts IssueBlueprint to JSON string
   - `import_blueprint()` - Creates IssueBlueprint from dict
   - `import_blueprint_json()` - Creates IssueBlueprint from JSON string
   - Custom exceptions: `BlueprintSerializationError`, `BlueprintDeserializationError`

2. **Views (in `core/views.py`)**
   - `blueprint_export()` - Handles export requests
   - `blueprint_import_form()` - Shows import form
   - `blueprint_import()` - Handles import POST requests

3. **URLs (in `core/urls.py`)**
   - `/configuration/blueprints/import/` - Import form
   - `/configuration/blueprints/import/submit/` - Import submission
   - `/configuration/blueprints/<id>/export/` - Export endpoint

4. **Templates**
   - `templates/blueprint_import.html` - Import UI
   - `templates/blueprint_detail.html` - Updated with export button
   - `templates/blueprints.html` - Updated with import button

### Error Handling

The implementation provides clear error messages for various scenarios:

| Scenario | Error Message |
|----------|--------------|
| Missing schema_version | "Missing required field: schema_version" |
| Unsupported version | "Unsupported schema version: X. Supported versions: 1.0" |
| Invalid JSON | "Invalid JSON: <details>" |
| Missing required field | "Missing required field: blueprint.<field>" |
| Invalid risk level | "Invalid default_risk_level: X. Valid values: Low, Normal, High, VeryHigh" |

### Category Handling

**On Export:**
- Includes both `name` and `slug` of the category
- Category information is embedded in the blueprint object

**On Import:**
- Uses `slug` as the canonical identifier
- If category with matching slug exists: Uses existing category (even if name differs)
- If category doesn't exist: Creates new category with provided name and slug
- New categories are created as active (`is_active=True`)

### Security

**Authentication:**
- All endpoints require login (`@login_required`)
- Import/export actions are logged for audit trail

**Validation:**
- JSON structure validation
- Schema version validation
- Field type validation
- Risk level enum validation
- Protection against malformed JSON

**Security Scan Results:**
- CodeQL analysis: ✅ 0 alerts found
- No SQL injection vulnerabilities
- No XSS vulnerabilities
- No file upload vulnerabilities

## Testing

### Test Coverage

Created `core/test_blueprint_import_export.py` with 22 comprehensive test cases:

**Export Tests (5 tests):**
- Export structure validation
- JSON format validation
- Minimal blueprint export
- Deterministic output verification

**Import Tests (10 tests):**
- Basic import
- Import with all fields
- Category creation on import
- Unknown fields handling
- Missing required fields
- Missing schema version
- Unsupported schema version
- Invalid JSON
- Update existing blueprint
- Invalid risk level

**Roundtrip Tests (2 tests):**
- Full blueprint export→import
- Minimal blueprint export→import

**View Tests (5 tests):**
- Export view returns JSON
- Export requires authentication
- Import form renders
- Import via text input
- Import requires authentication

### Running Tests

```bash
python manage.py test core.test_blueprint_import_export
```

**Note:** Tests require a configured PostgreSQL database.

## Usage Examples

### Example 1: Export a Blueprint

```python
from core.models import IssueBlueprint
from core.utils.blueprint_serializer import export_blueprint_json

blueprint = IssueBlueprint.objects.get(title="My Blueprint")
json_str = export_blueprint_json(blueprint, indent=2)

# Save to file
with open('blueprint_export.json', 'w') as f:
    f.write(json_str)
```

### Example 2: Import a Blueprint Programmatically

```python
from core.utils.blueprint_serializer import import_blueprint_json
from core.models import User

user = User.objects.get(username="admin")

with open('blueprint_export.json', 'r') as f:
    json_str = f.read()

blueprint, created = import_blueprint_json(
    json_str, 
    created_by=user,
    update_if_exists=False
)

print(f"Blueprint {'created' if created else 'updated'}: {blueprint.title}")
```

### Example 3: Roundtrip Test

```python
from core.models import IssueBlueprint
from core.utils.blueprint_serializer import export_blueprint_json, import_blueprint_json

# Export
original = IssueBlueprint.objects.get(id="...")
json_str = export_blueprint_json(original)

# Import
imported, created = import_blueprint_json(json_str)

# Verify
assert imported.title == original.title
assert imported.description_md == original.description_md
assert imported.category.slug == original.category.slug
```

## Acceptance Criteria Status

- ✅ Export action available in `/configuration/blueprints/`
- ✅ Export produces versioned, stable JSON (schema v1.0)
- ✅ Import action available in `/configuration/blueprints/`
- ✅ Import accepts JSON from other systems and creates blueprint correctly
- ✅ Validation and error cases handled cleanly (no 500 errors)
- ✅ Automated tests cover core scenarios including roundtrip

## Future Enhancements

Potential improvements for future versions:

1. **Bulk Export/Import** - Export/import multiple blueprints at once
2. **Import Preview** - Show what will be imported before confirmation
3. **Version Migration** - Automatic migration between schema versions
4. **Import Conflict Resolution UI** - Interactive resolution when blueprint exists
5. **Export Filters** - Export multiple blueprints with filtering
6. **API Endpoints** - REST API for import/export operations
7. **Import History** - Track import operations with rollback capability

## Activity Logging

All import/export operations are logged for audit purposes:

| Action | Verb | Summary |
|--------|------|---------|
| Export | `blueprint.exported` | "Exported blueprint '<title>'" |
| Import (new) | `blueprint.imported` | "Imported blueprint '<title>'" |
| Import (update) | `blueprint.updated_from_import` | "Updated from import blueprint '<title>'" |

## Files Modified/Created

### Created Files:
- `core/utils/blueprint_serializer.py` - Core serialization logic
- `templates/blueprint_import.html` - Import UI
- `core/test_blueprint_import_export.py` - Comprehensive tests

### Modified Files:
- `core/views.py` - Added export and import views
- `core/urls.py` - Added import/export URL routes
- `templates/blueprint_detail.html` - Added export button
- `templates/blueprints.html` - Added import button

## Conclusion

This implementation provides a production-ready Import/Export feature that meets all requirements:
- ✅ Versioned, stable JSON schema
- ✅ Deterministic export format
- ✅ Robust error handling and validation
- ✅ Category auto-creation
- ✅ Unknown field tolerance
- ✅ Comprehensive test coverage
- ✅ Security validated (CodeQL scan)
- ✅ User-friendly UI integration

The feature enables blueprint sharing between Agira instances while maintaining data integrity and providing clear error messages for any issues.
