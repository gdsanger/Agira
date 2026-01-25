# Multi-File Drag & Drop Upload Implementation

This document describes the implementation of multi-file drag-and-drop upload functionality for Items and Projects in Agira.

## Overview

The implementation adds a modern, user-friendly upload experience with the following features:

- **Drag & Drop**: Users can drag files directly onto the upload zone
- **Multi-File Upload**: Multiple files can be selected and uploaded simultaneously
- **Progress Tracking**: Real-time progress bars for each file
- **Error Handling**: Individual file errors don't block other uploads
- **Reusable Component**: Same component works for both Items and Projects
- **No External Dependencies**: Pure vanilla JavaScript implementation

## Architecture

### Frontend Components

#### 1. JavaScript Module (`static/js/multi-file-upload.js`)

The `MultiFileUpload` class handles all client-side upload logic:

```javascript
new MultiFileUpload({
    dropZoneId: 'item-upload-drop-zone',
    fileInputId: 'item-file-input',
    uploadUrl: "/items/123/upload-attachment/",
    csrfToken: token,
    maxFileSize: 25 * 1024 * 1024, // 25 MB
    onSuccess: (response, file) => {},
    onError: (error, file) => {},
    onAllComplete: () => {}
});
```

**Key Features:**
- Queue management (max 3 concurrent uploads)
- Per-file validation (size, type)
- XMLHttpRequest with progress events
- Automatic retry on queue processing
- Visual feedback for all states

**Upload States:**
1. `queued` - File waiting to upload
2. `uploading` - Upload in progress
3. `complete` - Upload successful
4. `error` - Upload failed

#### 2. CSS Styling (`static/css/site.css`)

Added styles for:
- Upload drop zone with hover effects
- Drag-over visual feedback
- Progress bars and status indicators
- Dark mode compatibility

### Backend Components

#### 1. Item Attachments

**View:** `item_upload_attachment(request, item_id)`
- Handles single file upload per request
- Returns simple success for AJAX requests
- Returns full template for HTMX requests (backward compatibility)
- Logs activity for each upload

**Template:** `templates/partials/item_attachments_tab.html`
- Drag & drop zone
- Progress container
- Attachment list
- JavaScript initialization

#### 2. Project Attachments (New)

**Views:**
- `project_attachments_tab(request, id)` - Renders attachments tab
- `project_upload_attachment(request, id)` - Handles uploads
- `project_delete_attachment(request, attachment_id)` - Handles deletion

**Template:** `templates/partials/project_attachments_tab.html`
- Identical UX to item attachments
- Configured for project context

**URL Routes:**
```python
path('projects/<int:id>/attachments/tab/', views.project_attachments_tab, name='project-attachments-tab'),
path('projects/<int:id>/upload-attachment/', views.project_upload_attachment, name='project-upload-attachment'),
path('projects/attachments/<int:attachment_id>/delete/', views.project_delete_attachment, name='project-delete-attachment'),
```

## Usage

### For Items

The upload component is automatically initialized when the attachments tab is loaded. Users can:

1. Click the drop zone to select files
2. Drag files onto the drop zone
3. Select multiple files at once
4. Watch progress for each file
5. See automatic list refresh after upload

### For Projects

Same as items, but accessed from the new "Attachments" tab in project detail view.

## File Upload Flow

```
User Action (Drag/Click)
    ↓
File Validation (size, type)
    ↓
Add to Upload Queue
    ↓
Process Queue (max 3 concurrent)
    ↓
XMLHttpRequest with Progress Events
    ↓
Backend Processing (AttachmentStorageService)
    ↓
Success Response
    ↓
Update UI (progress bar → complete)
    ↓
Refresh List (after all complete)
```

## Configuration

### File Size Limit

Default: 25 MB per file

To change, update the `maxFileSize` parameter:

```javascript
maxFileSize: 50 * 1024 * 1024  // 50 MB
```

### File Type Restrictions

By default, all file types are allowed. To restrict:

```javascript
allowedTypes: ['.pdf', '.docx', 'image/*', 'application/pdf']
```

### Concurrent Uploads

Default: 3 concurrent uploads

To change, modify the `maxConcurrentUploads` property in the class.

## Error Handling

### Client-Side
- File size validation
- File type validation
- Network errors
- Upload cancellation

### Server-Side
- File validation
- Permission checks
- Storage errors
- Activity logging

Each error is displayed per-file and doesn't block other uploads.

## Testing

### Automated Tests

Updated test: `core.test_item_detail.ItemDetailViewTest.test_item_attachments_tab_loads`
- Verifies new UI text
- Ensures template renders correctly
- All 14 tests passing

### Security

- CodeQL analysis: 0 alerts
- CSRF token protection
- Input sanitization
- File validation
- No XSS vulnerabilities

## Browser Compatibility

The implementation uses standard web APIs:
- XMLHttpRequest (Level 2) with progress events
- Drag and Drop API
- File API
- FormData API

Compatible with all modern browsers:
- Chrome/Edge 90+
- Firefox 88+
- Safari 14+

## Performance Considerations

1. **Queue Management**: Maximum 3 concurrent uploads prevents server overload
2. **Progress Tracking**: Uses efficient XMLHttpRequest events
3. **DOM Updates**: Minimal reflows, efficient element creation
4. **Memory**: Files are processed individually, not held in memory

## Future Enhancements

Potential improvements for future versions:

1. **Chunked Uploads**: For very large files (>100MB)
2. **Resume Capability**: Resume interrupted uploads
3. **Image Preview**: Thumbnail generation for images
4. **Batch Actions**: Select multiple files for deletion
5. **Upload History**: Track upload sessions
6. **Compression**: Client-side image compression before upload

## Troubleshooting

### Upload Fails Immediately

- Check file size (must be ≤ 25MB)
- Verify CSRF token is present
- Check browser console for errors

### Progress Bar Stuck

- Network timeout (check server logs)
- Server processing delay
- Browser console for errors

### List Doesn't Refresh

- Check HTMX is loaded
- Verify URL routes are correct
- Check browser console for errors

## Implementation Details

### Why XMLHttpRequest over Fetch?

XMLHttpRequest provides better upload progress tracking through the `upload.progress` event, which is essential for the per-file progress bars. While Fetch API is more modern, it doesn't support upload progress natively.

### Queue Design

The queue ensures:
1. No server overload (max 3 concurrent)
2. Efficient network usage
3. Fair processing order
4. Resilient to individual failures

### AJAX vs HTMX Detection

The backend differentiates between:
- AJAX requests (from JavaScript component) → simple success response
- HTMX requests → full template response (backward compatibility)

This allows both the new upload component and potential future HTMX-based uploads to coexist.

## Credits

Implementation based on requirements from Issue #7:
- Drag & Drop support ✓
- Multi-file upload ✓
- Progress indicators ✓
- Reusable component ✓
- Project attachments ✓
- Error handling ✓

All acceptance criteria met.
