# Global Settings Logo Upload Fix - Visual Guide

## Before the Fix ❌

### User Experience
```
1. User navigates to: Configuration → Global Settings
2. User selects a logo file
3. User clicks "Save Settings"
4. Result: ❌ 400 Bad Request Error
   - Console Error: "Response Status Error Code 400 from /global-settings/update/"
   - File not saved
   - No logo appears on page
```

### What Was Happening
```python
# OLD CODE - BROKEN
def global_settings_update(request):
    settings = GlobalSettings.get_instance()
    
    # ❌ Problem: Empty strings overwrite existing values
    settings.company_name = request.POST.get('company_name', settings.company_name)
    settings.email = request.POST.get('email', settings.email)
    # When fields are empty strings, they replace valid data
    
    if 'logo' in request.FILES:
        settings.logo = request.FILES['logo']
    
    settings.full_clean()  # ❌ FAILS: required fields are now empty strings
    settings.save()
```

### The Problem
When uploading a logo without changing other fields:
1. HTMX submits the form with empty strings for unchanged fields
2. `request.POST.get('email', default)` returns `''` (empty string)
3. Empty strings overwrite the existing values
4. `full_clean()` validation fails (required fields are empty)
5. Returns **400 Bad Request**

---

## After the Fix ✅

### User Experience
```
1. User navigates to: Configuration → Global Settings
2. User selects a logo file
3. User clicks "Save Settings"
4. Result: ✅ Success!
   - Logo uploads successfully
   - File saved to media/global_settings/
   - Logo appears on page
   - Other fields remain unchanged
```

### What Happens Now
```python
# NEW CODE - FIXED
def global_settings_update(request):
    settings = GlobalSettings.get_instance()
    
    # ✅ Solution: Only update fields with actual values
    company_name = request.POST.get('company_name', '').strip()
    if company_name:  # Only update if not empty
        settings.company_name = company_name
    
    email = request.POST.get('email', '').strip()
    if email:  # Only update if not empty
        settings.email = email
    
    # Same for other fields...
    
    if 'logo' in request.FILES:
        if settings.logo:
            settings.logo.delete(save=False)  # Clean up old file
        settings.logo = request.FILES['logo']
    
    settings.full_clean()  # ✅ PASSES: existing values preserved
    settings.save()
```

### The Solution
1. Strip whitespace from field values
2. Only update fields that have non-empty values
3. Preserve existing values for empty fields
4. Logo uploads work independently of other fields
5. Returns **200 Success**

---

## Example Scenarios

### Scenario 1: Upload Logo Only ✅
```
Form Submission:
  company_name: ""
  email: ""
  address: ""
  base_url: ""
  logo: [file selected]

OLD: ❌ 400 Error (fields become empty)
NEW: ✅ Success! (fields unchanged, logo uploaded)
```

### Scenario 2: Update Fields Without Logo ✅
```
Form Submission:
  company_name: "New Company Name"
  email: "new@example.com"
  address: "New Address"
  base_url: "https://new.com"
  logo: [not selected]

OLD: ✅ Works (no empty strings)
NEW: ✅ Works (logo preserved)
```

### Scenario 3: Update Everything ✅
```
Form Submission:
  company_name: "Updated Company"
  email: "updated@example.com"
  address: "Updated Address"
  base_url: "https://updated.com"
  logo: [new file selected]

OLD: ✅ Works
NEW: ✅ Works (old logo deleted, new logo saved)
```

---

## Technical Details

### File Storage
```
Upload Location: {MEDIA_ROOT}/global_settings/
Database Field:  settings.logo = "global_settings/logo_abc123.png"
Public URL:      /public/logo.png (no auth required)
Display URL:     /media/global_settings/logo_abc123.png (in dev)
```

### Logo Access Points
1. **Detail View**: Shows logo with settings.logo.url
2. **Public Endpoint**: `/public/logo.png` (no authentication)
3. **Template Variables**: Available in email templates
4. **PDF Reports**: Can use public URL

### Validation
- Required: company_name, email, address, base_url
- Optional: logo
- Formats: PNG, JPG, WEBP, GIF
- Max Size: 5 MB (note in UI)

---

## Testing

### Automated Tests (18 total)
```
✅ test_global_settings_logo_upload
   → Upload with all fields filled

✅ test_global_settings_logo_upload_only
   → Upload with empty field values (main fix)

✅ test_global_settings_update_without_logo
   → Update fields, preserve logo

✅ test_complete_logo_upload_workflow
   → Full integration test

...and 14 more tests covering:
   - Model validation
   - Singleton pattern
   - Public access
   - Authentication
   - Error handling
```

### Manual Testing
```bash
# 1. Access the page
URL: /global-settings/

# 2. Upload a logo
- Click "Choose File"
- Select an image
- Click "Save Settings"
- Verify: Success toast appears
- Verify: Logo displays on page

# 3. Check public access
URL: /public/logo.png
- Should display without login

# 4. Verify file storage
Path: media/global_settings/logo_*.png
- File should exist

# 5. Check database
SELECT logo FROM core_globalsettings;
- Should show: "global_settings/logo_*.png"
```

---

## Deployment Notes

### Development
- Media files served automatically by Django
- URL pattern added to agira/urls.py

### Production
- Configure web server (nginx/Apache) to serve /media/
- Or use cloud storage (S3, GCS, Azure Blob)
- Public logo endpoint works regardless

### Migration
- No data migration needed
- Existing logos (if any) continue to work
- New uploads use corrected logic
