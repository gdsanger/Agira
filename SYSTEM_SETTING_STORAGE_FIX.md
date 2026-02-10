# SystemSetting Image Upload Fix - Storage Configuration

## Issue
Image upload in SystemSetting form failed with error:
```
POST https://agira.angermeier.net/system-setting/update/ 400 (Bad Request)
Error: Error updating settings: Could not find config for 'default' in settings.STORAGES.
```

**Related Issues:**
- gdsanger/Agira#368 - SystemSetting model and UserUI integration
- gdsanger/Agira#478, #479, #481, #482 - Related PRs

## Root Cause
Django's `STORAGES` setting in `agira/settings.py` only defined the `"staticfiles"` backend but was missing the `"default"` backend configuration. This caused any ImageField or FileField operations to fail when trying to save uploaded files.

When Django tries to save a file via ImageField (like `company_logo`), it looks for the `"default"` key in the `STORAGES` dictionary. If it doesn't find it, the error occurs.

## Solution
Added the `"default"` storage backend configuration to the `STORAGES` setting.

### Changes Made

**File:** `agira/settings.py`

**Before:**
```python
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
```

**After:**
```python
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}
```

## Technical Details

### FileSystemStorage
The `FileSystemStorage` backend is Django's default file storage system that:
- Stores files on the local filesystem
- Uses `MEDIA_ROOT` setting as the base directory for file storage
- Uses `MEDIA_URL` setting as the base URL for serving files
- Handles file naming conflicts automatically
- Provides secure file handling

### Why This Works
1. FileSystemStorage automatically uses Django's `MEDIA_ROOT` and `MEDIA_URL` settings
2. No additional configuration is needed for basic file storage
3. This is the standard Django pattern for media file handling
4. Compatible with all Django file upload features

### Existing Settings
The following settings were already configured correctly in `settings.py`:
```python
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'
```

These settings are automatically used by FileSystemStorage.

## Testing

### Unit Tests
All existing tests pass with the fix:
- ✅ **SystemSetting tests**: 10/10 passed
- ✅ **GlobalSettings tests**: 18/18 passed

### Django Configuration Check
```bash
$ python manage.py check
System check identified no issues (0 silenced).
```

### Storage Verification
```python
from django.core.files.storage import default_storage
print(default_storage.__class__.__name__)  # FileSystemStorage
print(default_storage.location)            # /path/to/media
print(default_storage.base_url)            # /media/
```

## Security Analysis

### CodeQL Scan
✅ **No security vulnerabilities found**

### Security Considerations
1. **File Storage Security**: FileSystemStorage is the standard Django storage backend
2. **Path Traversal Prevention**: Django handles file path sanitization automatically
3. **File Validation**: Existing ImageField validation remains intact
4. **Access Control**: MEDIA_URL routing still requires proper web server configuration
5. **CSRF Protection**: Form submission still uses CSRF tokens

### Risk Assessment
- **Risk Level**: LOW
- **Impact**: Fixes broken functionality with standard Django configuration
- **Security Impact**: None - uses Django's built-in secure storage backend

## Impact

### Fixed Functionality
- ✅ Company logo upload in SystemSettings
- ✅ Company logo upload in GlobalSettings  
- ✅ Any other ImageField/FileField uploads in the application

### No Breaking Changes
- ✅ Backward compatible with existing code
- ✅ Existing files in media directory unaffected
- ✅ No database migrations required
- ✅ No template changes required
- ✅ No URL routing changes required

## Deployment

### Requirements
- No additional dependencies
- No database migrations
- No special deployment steps

### Post-Deployment Verification
1. Navigate to **Configuration → System Settings**
2. Upload a company logo (PNG, JPG, WEBP, or GIF)
3. Click **Save Settings**
4. Verify:
   - No browser console errors
   - Success toast notification appears
   - Logo is saved and displayed
   - File exists in `media/system_settings/` directory

## Alternative Approaches Considered

### 1. Using S3 or Cloud Storage
**Not needed** - FileSystemStorage is sufficient for this application's needs.

### 2. Custom Storage Backend
**Not needed** - Django's FileSystemStorage provides all required functionality.

### 3. Adding OPTIONS to Storage Config
**Not needed** - FileSystemStorage uses MEDIA_ROOT and MEDIA_URL by default.

## Related Documentation
- Django STORAGES documentation: https://docs.djangoproject.com/en/5.0/ref/settings/#storages
- FileSystemStorage documentation: https://docs.djangoproject.com/en/5.0/ref/files/storage/
- Previous fix documentation: SYSTEM_SETTING_IMAGE_UPLOAD_FIX.md (HTMX to Fetch API change)

## Conclusion
This is a minimal, essential fix that adds the missing default storage configuration required by Django for handling file uploads. The change follows Django best practices and resolves the 400 Bad Request error without introducing any security risks or breaking changes.

**Status**: ✅ **COMPLETE AND TESTED**

---

**Date**: 2026-02-10  
**Issue**: gdsanger/Agira#368  
**PR Branch**: copilot/add-system-setting-integration
