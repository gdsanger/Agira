# Global Settings Logo Upload Fix - Summary

## Problem Description

The Global Settings page had a critical bug where:
1. Uploading a logo resulted in a **400 Bad Request** error
2. The file was **not saved** on the server
3. No reference was **stored in the database**
4. This prevented users from configuring company logos for use in emails, PDFs, and the customer portal

## Root Cause Analysis

### Primary Issue: Empty Field Handling
The `global_settings_update` view used this pattern:
```python
settings.company_name = request.POST.get('company_name', settings.company_name)
```

**Problem**: `dict.get(key, default)` only returns the default value if the key is **missing**, not if the value is an **empty string**.

When the HTMX form was submitted with a logo upload:
- Fields that weren't being changed were submitted as empty strings
- These empty strings overwrote the existing values
- The `full_clean()` validation failed because required fields were now empty
- Result: **400 Bad Request**

### Secondary Issue: Media Files Not Served
Media files were not configured to be served in Django's development server, so even if the logo was uploaded, the `{{ settings.logo.url }}` in the template would not work.

## Solution Implemented

### 1. Fixed Field Handling (core/views.py)
Changed the view to only update fields that have **non-empty values** after stripping whitespace:

```python
# Update fields only if they have a value (not empty string)
company_name = request.POST.get('company_name', '').strip()
if company_name:
    settings.company_name = company_name
```

**Benefits**:
- Allows uploading a logo without changing other fields
- Enables partial updates to settings
- Prevents validation errors from empty strings
- Maintains backward compatibility

### 2. Added Media File Serving (agira/urls.py)
Configured Django to serve media files in development mode:

```python
from django.conf.urls.static import static

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

This ensures uploaded logos are accessible via their URLs in development.

### 3. Comprehensive Test Coverage (core/test_global_settings.py)
Added three new test cases:

1. **`test_global_settings_logo_upload_only`**: Tests uploading a logo with empty field values
2. **`test_global_settings_update_without_logo`**: Tests updating settings without changing the logo
3. **`test_complete_logo_upload_workflow`**: Integration test covering the full workflow

## Verification

### Automated Tests
All 18 tests in `core.test_global_settings` pass:
```bash
python manage.py test core.test_global_settings --settings=agira.test_settings
```

**Result**: ✅ 18/18 tests passing

### Security Check
CodeQL security scan completed:
```
Analysis Result for 'python'. Found 0 alerts
```

**Result**: ✅ No security vulnerabilities

### Code Review
Automated code review completed:
```
Code review completed. No review comments found.
```

**Result**: ✅ No issues found

## Manual Testing Steps

To manually verify the fix:

1. **Navigate to Global Settings**
   ```
   Login → Configuration → Global Settings
   ```

2. **Test Logo Upload Only**
   - Upload a logo image (PNG, JPG, GIF, WEBP)
   - Click "Save Settings"
   - **Expected**: Success message, logo appears on page
   - **Expected**: No 400 error in browser console

3. **Verify Logo Storage**
   - Check that file exists in `media/global_settings/` directory
   - Check database: `select logo from core_globalsettings;`
   - **Expected**: Relative path stored (e.g., `global_settings/logo.png`)

4. **Test Public Logo Access**
   - Open `/public/logo.png` in a new browser tab (no login required)
   - **Expected**: Logo image displays

5. **Test Update Without Logo Change**
   - Change company name or email
   - Click "Save Settings" without selecting a new logo
   - **Expected**: Fields update, logo remains unchanged

6. **Test Logo Replacement**
   - Upload a different logo
   - Click "Save Settings"
   - **Expected**: Old logo is deleted, new logo appears

## Files Changed

### Modified Files
1. **core/views.py** (lines 7356-7387)
   - Fixed `global_settings_update` function

2. **agira/urls.py**
   - Added media file serving configuration

3. **core/test_global_settings.py**
   - Added 3 new comprehensive test cases

### New Files
4. **core/migrations/0041_merge_20260204_1208.py**
   - Merge migration (cleanup)

## Acceptance Criteria Status

✅ **Upload + Speichern** führt zu persistierter Datei im konfigurierten Server-Storage
✅ **Global-Settings-Datensatz** enthält einen persistierten Verweis auf das Image
✅ **`/global-settings/update/`** liefert bei validem Submit kein 400, sondern Success-Status
✅ **Wiederholtes Speichern** ohne Dateiänderung behält das bestehende Logo
✅ **Backend-Test** deckt Upload+Update ab

## Technical Notes

### Logo Storage
- Logos are stored in `MEDIA_ROOT/global_settings/`
- The `ImageField` automatically handles:
  - File naming (prevents conflicts)
  - Storage in the configured location
  - URL generation via `.url` property

### Database Field
The `GlobalSettings.logo` field is defined as:
```python
logo = models.ImageField(
    upload_to='global_settings/',
    blank=True,
    null=True,
    help_text="Company logo (PNG, JPG, WEBP, GIF - max 5 MB)"
)
```

### Public Access
The logo is publicly accessible (no authentication required) at:
- **URL**: `/public/logo.png`
- **View**: `public_logo` in `core/views.py`
- This enables use in:
  - Email templates
  - PDF reports
  - External integrations
  - Customer portals

## Future Considerations

1. **File Size Validation**: Consider adding explicit file size validation (currently only mentioned in help text)
2. **Image Format Validation**: Consider restricting to specific formats in the model
3. **Image Processing**: Consider adding image optimization/resizing on upload
4. **CDN Support**: For production, consider serving media files via CDN

## Rollback Plan

If issues arise, the changes can be rolled back by:
1. Reverting the commits in this PR
2. Running migrations: `python manage.py migrate core 0040`
3. No data loss - existing logos will remain in place

## Support

For questions or issues, contact the development team or create a new issue referencing this fix.
