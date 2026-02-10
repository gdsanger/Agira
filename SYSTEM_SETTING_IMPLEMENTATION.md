# SystemSetting Implementation Documentation

## Overview
This document describes the implementation of the `SystemSetting` model, a singleton configuration model for system-wide settings in the Agira application.

## Requirements Met
✓ New model `SystemSetting` with singleton pattern  
✓ CRUD operations (Create/Update/Edit - no Delete)  
✓ File upload for company logo  
✓ Default record creation with specified values  
✓ UserUI integration under Configuration navigation  
✓ Logo stored as relative path (accessible to HTML/Weasyprint)  

## Model Structure

### Fields
| Field Name | Type | Default Value | Description |
|------------|------|---------------|-------------|
| id | BigAutoField | Auto increment | Primary key |
| system_name | CharField(255) | "Agira Issue Tracking v1.0" | System name |
| company | CharField(255) | "Agira Software Enterprises" | Company name |
| company_logo | ImageField | None (optional) | Company logo file |
| email | EmailField | "agira@angermeier.net" | Contact email |
| created_at | DateTimeField | Auto | Creation timestamp |
| updated_at | DateTimeField | Auto | Last update timestamp |

### Key Features
- **Singleton Pattern**: Only one record allowed (enforced at model level)
- **Delete Prevention**: Override `delete()` method to prevent deletion
- **Default Record**: Migration automatically creates default record with specified values
- **Get Instance**: `SystemSetting.get_instance()` class method for easy access

## File Storage

### Company Logo Upload
- **Upload Directory**: `media/system_settings/`
- **Accepted Formats**: PNG, JPG, WEBP, GIF
- **Max Size**: 5 MB (documented, validation at form level)
- **Storage**: Relative path stored in database (e.g., `system_settings/logo.png`)
- **Access**: Accessible via `{{ setting.company_logo.url }}` in templates

### Why Relative Path?
The relative path is stored to ensure compatibility with:
- HTML templates
- PDF generation (Weasyprint)
- Email templates
- Different deployment environments (MEDIA_URL can vary)

## User Interface

### Navigation
Located under: **Configuration → System Settings**

### Detail/Edit Page
- **URL**: `/system-setting/`
- **Template**: `templates/system_setting_detail.html`
- **Features**:
  - Single-page view and edit interface
  - HTMX-based updates (no page reload)
  - File upload for company logo
  - Shows current logo with preview
  - Displays relative path for logo
  - Toast notifications for success/error
  - Metadata section (created/updated timestamps)

### Form Fields
All fields except company_logo are required:
1. **System Name**: Text input
2. **Company**: Text input
3. **Email**: Email input with validation
4. **Company Logo**: File upload (optional)

## Admin Interface

### Registration
Registered as: `SystemSettingAdmin(ConfigurationAdmin)`

### Features
- **Add Permission**: Only if no instance exists (singleton)
- **Delete Permission**: Disabled (cannot delete)
- **Fieldsets**:
  - Main: system_name, company, email
  - Logo: company_logo
  - Metadata: created_at, updated_at (collapsed, read-only)

## API Endpoints

### Detail View
- **URL**: `/system-setting/`
- **Method**: GET
- **Auth**: Login required
- **Response**: HTML page with form

### Update View
- **URL**: `/system-setting/update/`
- **Method**: POST
- **Auth**: Login required
- **Content-Type**: `multipart/form-data` (for file upload)
- **Fields**:
  - `system_name`: string
  - `company`: string
  - `email`: email
  - `company_logo`: file (optional)
- **Response**: 
  - Success: 200 with HX-Trigger header
  - Error: 400 with error message

### Update Behavior
- Only updates fields with non-empty values
- Old logo is deleted when new one is uploaded
- Validates all fields before saving
- Returns HTMX trigger for toast notification

## Database Migration

### Migration File
`core/migrations/0048_add_system_setting_model.py`

### Operations
1. Create `SystemSetting` table
2. Create default record with:
   - id = 1
   - system_name = "Agira Issue Tracking v1.0"
   - company = "Agira Software Enterprises"
   - email = "agira@angermeier.net"
   - company_logo = None

### Reversal
- Removes table
- Deletes default record

## Testing

### Test File
`core/test_system_setting.py`

### Test Coverage (10 tests, all passing)
1. **Singleton Pattern**: Ensures only one instance can exist
2. **Get Instance**: Verifies `get_instance()` creates and retrieves singleton
3. **Default Values**: Checks default values are set correctly
4. **Delete Prevention**: Confirms deletion is prevented
5. **String Method**: Tests `__str__()` representation
6. **Detail View Access**: Verifies view is accessible when logged in
7. **Default Values Display**: Checks default values appear in template
8. **Update Success**: Tests successful update via POST
9. **Auth Required**: Ensures authentication is required
10. **Email Validation**: Tests invalid email is rejected

## Usage Examples

### In Python Code
```python
from core.models import SystemSetting

# Get the singleton instance
setting = SystemSetting.get_instance()

# Access values
system_name = setting.system_name
company = setting.company
email = setting.email

# Check if logo exists
if setting.company_logo:
    logo_path = setting.company_logo.url
    # Use in templates, emails, PDFs, etc.
```

### In Templates
```django
{% load static %}

<!-- Get system settings -->
{% with setting=system_setting %}
  <h1>{{ setting.system_name }}</h1>
  <p>{{ setting.company }}</p>
  <p>Email: {{ setting.email }}</p>
  
  {% if setting.company_logo %}
    <img src="{{ setting.company_logo.url }}" alt="Company Logo">
  {% endif %}
{% endwith %}
```

### In PDF Reports (Weasyprint)
```python
from core.models import SystemSetting

setting = SystemSetting.get_instance()
context = {
    'system_name': setting.system_name,
    'company': setting.company,
    'logo_path': setting.company_logo.path if setting.company_logo else None,
}
# Use in PDF template
```

## Security Considerations

### Input Validation
- Email field validated by Django's EmailField
- File uploads validated by Django's ImageField
- CSRF protection via Django middleware
- Login required for all operations

### File Upload Security
- Only image files accepted (PNG, JPG, WEBP, GIF)
- Django's ImageField validates file format
- Old files are deleted when replaced
- Files stored in media directory with restricted access

### Singleton Enforcement
- Model-level validation prevents multiple instances
- Admin interface prevents creating new instances
- Delete method overridden to prevent deletion

## CodeQL Security Scan
✓ No security vulnerabilities detected

## Future Enhancements
Potential improvements for future iterations:
1. Add file size validation at model level (currently only documented)
2. Add image dimension validation
3. Add logo preview in admin interface
4. Add public endpoint for logo (if needed)
5. Add more system-wide settings as needed

## Compatibility
- Django 5.2.11+
- Python 3.12+
- PostgreSQL or SQLite
- Compatible with Weasyprint for PDF generation
- HTMX for interactive UI updates

## Related Files
- Model: `core/models.py` (lines 1559-1623)
- Admin: `core/admin.py` (lines 637-654)
- Views: `core/views.py` (lines 7860-7918)
- URLs: `core/urls.py` (lines 201-203)
- Template: `templates/system_setting_detail.html`
- Navigation: `templates/base.html` (lines 201-205)
- Migration: `core/migrations/0048_add_system_setting_model.py`
- Tests: `core/test_system_setting.py`
