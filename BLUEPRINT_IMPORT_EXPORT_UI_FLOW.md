# Blueprint Import/Export UI Flow

## 1. Blueprint List Page (/configuration/blueprints/)

```
┌────────────────────────────────────────────────────────────────┐
│ Issue Blueprints                                               │
│ Manage reusable issue templates                               │
│                                                                │
│  [📤 Import Blueprint]  [➕ New Blueprint]                     │
└────────────────────────────────────────────────────────────────┘
│                                                                │
│ Filter Bar: [Search] [Category] [Status] [Tag] [Creator]      │
│                                                                │
│ ┌──────────────────────────────────────────────────────────┐  │
│ │ Title          │ Category │ Version │ Status  │ Actions  │  │
│ ├──────────────────────────────────────────────────────────┤  │
│ │ User Auth      │ Features │ v1      │ Active  │ [View]   │  │
│ │ API Limiting   │ Security │ v2      │ Active  │ [View]   │  │
│ │ Data Backup    │ Infra    │ v1      │ Inactive│ [View]   │  │
│ └──────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

**New UI Element:**
- **Import Blueprint** button (green) - Opens import form

---

## 2. Blueprint Detail Page (/configuration/blueprints/<id>/)

```
┌────────────────────────────────────────────────────────────────┐
│ API Rate Limiting                      [Active]                │
│ Features  Version 1                                            │
│                                        [✏️ Edit]                │
└────────────────────────────────────────────────────────────────┘

┌─────────────────────────────┬──────────────────────────────────┐
│ Description                 │ ┌──────────────────────────────┐ │
│                             │ │ Information                  │ │
│ # API Rate Limiting         │ │ Status: Active               │ │
│                             │ │ Category: Security           │ │
│ Implement rate limiting     │ │ Version: 1                   │ │
│ for API endpoints.          │ │ Created By: admin            │ │
│                             │ │ Created: 2024-01-15          │ │
│ ## Acceptance Criteria      │ └──────────────────────────────┘ │
│ - Limit requests per minute │                                  │
│ - Return 429 on limit       │ ┌──────────────────────────────┐ │
│                             │ │ Actions                      │ │
│ Default Settings            │ │                              │ │
│ Tags: security, api         │ │ [➕ Create Issue]            │ │
│ Risk Level: High            │ │ [✏️ Edit Blueprint]          │ │
│ Security Relevant: Yes      │ │ [⬇️ Export Blueprint]        │ │
│                             │ │ [🗑️ Delete Blueprint]         │ │
│                             │ └──────────────────────────────┘ │
└─────────────────────────────┴──────────────────────────────────┘
```

**New UI Element:**
- **Export Blueprint** button (blue) - Downloads JSON file

---

## 3. Import Form Page (/configuration/blueprints/import/)

```
┌────────────────────────────────────────────────────────────────┐
│ Blueprints > Import                                            │
│                                                                │
│ Import Blueprint                                               │
│ Import a blueprint from JSON file or text                      │
└────────────────────────────────────────────────────────────────┘

┌─────────────────────────────┬──────────────────────────────────┐
│ Import Blueprint            │ Import Help                      │
│                             │                                  │
│ Import Method               │ What is Blueprint Import?        │
│ [📄 Upload File] [📝 Paste] │ Import allows you to load        │
│                             │ blueprints from another Agira    │
│ ┌─────────────────────────┐ │ instance or backup.              │
│ │ JSON File               │ │                                  │
│ │ [Choose File...]        │ │ Expected Format                  │
│ │                         │ │ • schema_version: "1.0"          │
│ │ blueprint_export.json   │ │ • blueprint: { ... }             │
│ └─────────────────────────┘ │                                  │
│                             │ Category Handling                │
│ Options                     │ Missing categories are created   │
│ ☑️ Update if exists         │ automatically.                   │
│                             │                                  │
│ [⬅️ Cancel] [⬆️ Import]     │ Example Export                   │
│                             │ {                                │
│                             │   "schema_version": "1.0",       │
│                             │   "blueprint": {                 │
│                             │     "title": "Example",          │
│                             │     ...                          │
│                             │   }                              │
│                             │ }                                │
└─────────────────────────────┴──────────────────────────────────┘
```

**Import Options:**
1. **Upload File** - Select .json file
2. **Paste JSON** - Paste JSON content directly
3. **Update if exists** - Checkbox to update existing blueprint

---

## 4. Export Result (Downloaded JSON)

**Filename:** `blueprint_API_Rate_Limiting_v1.json`

```json
{
  "schema_version": "1.0",
  "blueprint": {
    "category": {
      "name": "Security",
      "slug": "security"
    },
    "default_labels": [
      "backend",
      "api"
    ],
    "default_risk_level": "High",
    "default_security_relevant": true,
    "description_md": "# API Rate Limiting\n\nImplement rate limiting...",
    "is_active": true,
    "notes": "Critical security feature",
    "tags": [
      "security",
      "api"
    ],
    "title": "API Rate Limiting",
    "version": 1
  }
}
```

---

## 5. Import Success Flow

```
User clicks "Import Blueprint"
         ↓
Opens Import Form
         ↓
User uploads JSON file or pastes JSON
         ↓
User clicks "Import Blueprint" button
         ↓
System validates JSON:
  • Check schema_version
  • Validate required fields
  • Validate field types
         ↓
System creates/updates blueprint:
  • Create category if needed
  • Create/update blueprint
  • Log activity
         ↓
Success notification shown
         ↓
Redirect to blueprint detail page
```

## 6. Error Handling Examples

### Invalid JSON
```
┌──────────────────────────────────────────────┐
│ ⚠️ Error                                     │
│ Invalid JSON: Expecting ',' delimiter       │
│ at line 5 column 3                          │
└──────────────────────────────────────────────┘
```

### Unsupported Version
```
┌──────────────────────────────────────────────┐
│ ⚠️ Error                                     │
│ Unsupported schema version: 2.0.            │
│ Supported versions: 1.0                     │
└──────────────────────────────────────────────┘
```

### Missing Required Field
```
┌──────────────────────────────────────────────┐
│ ⚠️ Error                                     │
│ Missing required field: blueprint.title     │
└──────────────────────────────────────────────┘
```

---

## Key Features Demonstrated

✅ **Export from Detail Page** - Single click to download JSON
✅ **Import from List Page** - Dedicated import interface
✅ **File or Text Import** - Flexible input methods
✅ **Update Option** - Control over create vs. update behavior
✅ **Help Panel** - Inline documentation for users
✅ **Error Messages** - Clear, actionable feedback
✅ **Activity Logging** - Audit trail for all operations

---

## Technical Details

### Export Endpoint
- **URL:** `GET /configuration/blueprints/<uuid:id>/export/`
- **Response:** JSON file download
- **Filename:** `blueprint_<sanitized_title>_v<version>.json`
- **Content-Type:** `application/json`

### Import Endpoints
- **Form:** `GET /configuration/blueprints/import/`
- **Submit:** `POST /configuration/blueprints/import/submit/`
- **Request:** Multipart form (file) or JSON text
- **Response:** JSON with success/error and redirect URL

### Data Flow
```
Export: IssueBlueprint → export_blueprint() → JSON file
Import: JSON file → import_blueprint() → IssueBlueprint
```
