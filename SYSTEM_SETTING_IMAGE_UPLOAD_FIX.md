# SystemSetting Image Upload Fix

## Problem
When trying to save the SystemSetting form with a company logo file selected, the request failed with a 400 Bad Request error.

**Error Message:**
```
htmx.org@2.0.4:1 
POST https://agira.angermeier.net/system-setting/update/ 400 (Bad Request)
```

## Root Cause
HTMX 2.x has known issues with the `hx-encoding="multipart/form-data"` attribute when handling file uploads. While HTMX works well for most AJAX interactions, file uploads with multipart/form-data encoding are not reliably supported in HTMX 2.x.

The form was using:
```html
<form hx-post="{% url 'system-setting-update' %}" 
      hx-swap="none"
      hx-encoding="multipart/form-data"
      enctype="multipart/form-data"
      hx-on::after-request="...">
```

This combination caused the FormData to be incorrectly encoded or the CSRF token to not be properly included, resulting in a 400 error from the Django backend.

## Solution
Replaced HTMX-based form submission with vanilla JavaScript using the Fetch API, following the same pattern already used in `blueprint_import.html`.

### Changes Made

#### 1. Updated Form Tag (system_setting_detail.html)
**Before:**
```html
<form hx-post="{% url 'system-setting-update' %}" 
      hx-swap="none"
      hx-encoding="multipart/form-data"
      enctype="multipart/form-data"
      hx-on::after-request="if(event.detail.successful) { showToast('Settings updated successfully', 'success'); location.reload(); }">
```

**After:**
```html
<form id="settingsForm" enctype="multipart/form-data">
```

#### 2. Added Submit Button ID
**Before:**
```html
<button type="submit" class="btn btn-primary">
```

**After:**
```html
<button type="submit" class="btn btn-primary" id="save-btn">
```

#### 3. Added JavaScript Form Handler
Added a DOMContentLoaded event listener that:
- Intercepts form submission
- Creates FormData from the form
- Uses Fetch API to POST the data
- Includes CSRF token in headers
- Shows loading state on the button
- Handles success with toast notification and page reload
- Handles errors with toast notification and button reset

**Key Code:**
```javascript
fetch('{% url "system-setting-update" %}', {
    method: 'POST',
    body: formData,
    headers: {
        'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
    }
})
```

#### 4. Applied Same Fix to GlobalSettings
The same issue existed in `global_settings_detail.html`, so the identical fix was applied there as well.

## Benefits
- ✅ File uploads now work correctly
- ✅ CSRF protection maintained
- ✅ Better error handling
- ✅ Loading state feedback for users
- ✅ Consistent pattern across the application (matches blueprint_import.html)
- ✅ No changes to backend code required
- ✅ Toast notifications work as expected

## Testing
To test the fix:
1. Navigate to Configuration → System Settings
2. Select a company logo file (PNG, JPG, WEBP, or GIF)
3. Optionally modify other fields
4. Click "Save Settings"
5. Verify that:
   - Button shows "Saving..." with spinner
   - Success toast appears
   - Page reloads
   - New logo is displayed
   - No 400 errors in browser console

## Alternative Solutions Considered
1. **Using htmx-ext-multipart extension** - Would add an extra dependency
2. **Downgrading HTMX to 1.x** - Would lose other HTMX 2.x improvements
3. **Separate logo upload endpoint** - Would complicate the UX
4. **Using HTMX with JavaScript FormData manipulation** - Still unreliable

The chosen solution (vanilla Fetch API) is:
- Simple and reliable
- Doesn't add dependencies
- Already proven to work in blueprint_import.html
- Easy to understand and maintain

## Related Files
- `/templates/system_setting_detail.html` - Fixed
- `/templates/global_settings_detail.html` - Fixed
- `/templates/blueprint_import.html` - Reference implementation
- `/core/views.py` - No changes needed (backend already correct)

## References
- Issue: gdsanger/Agira#368
- Related PRs: gdsanger/Agira#478, gdsanger/Agira#479
- HTMX 2.x file upload limitations: Known issue in HTMX community

## Future Considerations
If other forms in the application need file upload functionality, they should follow this same pattern (Fetch API) rather than using HTMX's `hx-encoding` attribute.
