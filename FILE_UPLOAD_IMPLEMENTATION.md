# File Upload and Toast UI Editor Implementation - Issue #227

## Overview
This implementation adds file upload and inline image support to the customer portal embed issue creation form, replacing the plain textarea with Toast UI Editor for rich markdown editing.

## Screenshot
![Issue Creation Form with File Upload](https://github.com/user-attachments/assets/c4e0dbc4-6e27-4d39-9799-3c29f5f91765)

## Features Implemented

### 1. Toast UI Editor Integration
- **Replaced** plain textarea with Toast UI Editor (v3.2.2)
- **Markdown** editing with live preview
- **Inline image paste** support via addImageBlobHook
- **Dark theme** compatible with existing embed portal styling

### 2. File Upload Support
- **Multiple file upload** (max 5 files)
- **Drag & drop** support for files
- **File size limit**: 10MB per file
- **Allowed file types**: 
  - Images: .jpg, .jpeg, .png, .gif, .bmp
  - Documents: .pdf, .docx, .md
  - ⚠️ **Security**: SVG and HTML files excluded to prevent XSS attacks

### 3. Client-Side Features
- **Real-time file validation**:
  - File type checking (with user-friendly error messages)
  - File size validation
  - Maximum file count enforcement
- **Visual file list** with:
  - File name display
  - File size formatting
  - Remove button for each file
- **Upload progress** indication during submission
- **Drag & drop** visual feedback

### 4. Backend Implementation

#### New Endpoints

##### `embed_attachment_pre_upload` (POST)
- **URL**: `/embed/projects/<project_id>/attachments/pre-upload/`
- **Purpose**: Pre-upload attachments before issue creation
- **Security**: Token-based authentication
- **Features**:
  - Server-side file type validation
  - Server-side file size validation (10MB limit)
  - Attachment storage using existing AttachmentStorageService
  - Returns attachment ID and URL for inline images

##### `embed_attachment_download` (GET)
- **URL**: `/embed/attachments/<attachment_id>/download/`
- **Purpose**: Serve attachments with token authentication
- **Security**: 
  - Token-based authentication
  - Project ownership verification
  - Filename sanitization (prevents header injection)
- **Features**:
  - Inline display for images
  - Forced download for documents
  - Content-Type handling

#### Updated Endpoint

##### `embed_issue_create` (POST)
- **Enhanced** to accept attachment IDs
- **Links** pre-uploaded attachments to the created item
- **Robust** error handling for invalid attachment IDs
- **Maintains** existing functionality

## Security Measures

### 1. File Type Restrictions
- ❌ **Blocked**: SVG and HTML files (XSS vulnerability)
- ✅ **Allowed**: Safe file types only (images, PDF, DOCX, Markdown)

### 2. Validation
- **Client-side**: For user experience (can be bypassed)
- **Server-side**: Enforced security validation (cannot be bypassed)
- **Both layers** validate file types and sizes

### 3. Header Injection Prevention
- Filenames sanitized using `urllib.parse.quote()` in Content-Disposition headers

### 4. Input Validation
- Attachment IDs validated before parsing (prevents ValueError exceptions)
- Only numeric IDs accepted

### 5. Version Pinning
- Toast UI Editor pinned to **v3.2.2** (prevents unexpected breaking changes)

## Technical Details

### Constants Defined
```python
MAX_ATTACHMENT_SIZE_MB = 10
MAX_ATTACHMENT_COUNT = 5
ALLOWED_ATTACHMENT_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.pdf', '.docx', '.md']
```

### File Storage Flow
1. User selects/pastes files
2. Files validated client-side (UX)
3. Files pre-uploaded via AJAX to `embed_attachment_pre_upload`
4. Server validates and stores files
5. Server returns attachment IDs
6. On form submit, attachment IDs sent with issue data
7. Backend links attachments to created item

### Inline Image Flow
1. User pastes image into Toast Editor
2. `addImageBlobHook` triggered
3. Image uploaded via AJAX with `is_inline=true`
4. Server returns download URL with token
5. URL inserted into markdown
6. Image displayed in preview
7. Attachment linked to item on submission

## Files Modified

### Frontend
- **templates/embed/issue_create.html**
  - Added Toast UI Editor CSS/JS (v3.2.2)
  - Replaced textarea with editor div
  - Added file upload area with drag & drop
  - Added file list display
  - Added comprehensive JavaScript for file handling
  - Added Toast Editor initialization with image upload hook

### Backend
- **core/views_embed.py**
  - Added constants for upload limits
  - Added `embed_attachment_pre_upload` view
  - Added `embed_attachment_download` view
  - Updated `embed_issue_create` to handle attachments
  - Added security measures and validation

### Configuration
- **core/urls.py**
  - Added route for `embed-attachment-pre-upload`
  - Added route for `embed-attachment-download`

## Code Quality

### Code Review Results
✅ All critical security issues addressed:
- SVG/HTML file types removed
- Filename sanitization added
- Attachment ID validation improved
- Toast UI version pinned
- File removal bug fixed
- Constants defined (no magic numbers)

### Security Scan Results
✅ **CodeQL**: No vulnerabilities found

## Testing Recommendations

### Manual Testing Checklist
1. **File Upload**
   - [ ] Upload single file
   - [ ] Upload multiple files (up to 5)
   - [ ] Upload files via drag & drop
   - [ ] Remove file from list
   - [ ] Verify file type validation
   - [ ] Verify file size validation
   - [ ] Verify max count validation

2. **Inline Images**
   - [ ] Paste image into editor
   - [ ] Verify image uploads automatically
   - [ ] Verify image displays in preview
   - [ ] Drag & drop image into editor
   - [ ] Verify multiple inline images work

3. **Toast Editor**
   - [ ] Type markdown syntax
   - [ ] Verify preview updates
   - [ ] Test toolbar buttons
   - [ ] Test dark theme rendering

4. **Form Submission**
   - [ ] Create issue with attachments
   - [ ] Verify attachments appear in issue detail
   - [ ] Verify inline images render correctly
   - [ ] Test without attachments (should still work)

5. **Error Handling**
   - [ ] Try uploading >10MB file
   - [ ] Try uploading >5 files
   - [ ] Try uploading invalid file type
   - [ ] Test network error during upload

### Automated Testing
While this implementation focuses on minimal changes, future enhancements could include:
- Integration tests for file upload endpoints
- Selenium/Playwright tests for UI interactions
- Unit tests for validation logic

## Migration Notes
- ✅ **No database migrations** required
- ✅ **No breaking changes** to existing functionality
- ✅ **Backward compatible** with existing embed portal features

## Usage Example

### For End Users
1. Navigate to issue creation form in embed portal
2. Fill in required fields (Title, Type, Requester)
3. Use Toast Editor to write description with markdown
4. **Optional**: Paste images directly into editor
5. **Optional**: Click or drag files into upload area
6. Remove unwanted files if needed
7. Click "Create Issue"
8. Attachments and inline images automatically linked to issue

### For Administrators
- No configuration changes needed
- File size limit: 10MB (configurable via `MAX_ATTACHMENT_SIZE_MB`)
- File count limit: 5 (configurable via `MAX_ATTACHMENT_COUNT`)
- Allowed extensions: Defined in `ALLOWED_ATTACHMENT_EXTENSIONS`

## Performance Considerations
- Files pre-uploaded individually (not all at once on submit)
- Progress indication prevents user confusion
- Chunked file writing for large files
- Existing storage service used (no new infrastructure)

## Known Limitations
1. **Browser compatibility**: Requires modern browser with File API support
2. **Network dependency**: Requires stable connection for file uploads
3. **No progress bar**: Individual file upload progress not shown (could be future enhancement)
4. **No resumable uploads**: Large files must upload completely (could be future enhancement)

## Future Enhancements
- Add upload progress bars
- Add file preview thumbnails
- Support resumable uploads
- Add file type icons
- Implement client-side image compression
- Add copy/paste from clipboard for text files

## Acceptance Criteria Status
✅ **All requirements met**:
1. ✅ File upload functionality (max 5 files, 10MB each)
2. ✅ Toast UI Editor instead of plain textarea
3. ✅ Inline image paste support
4. ✅ Allowed file types: Images, PDF, DOCX, Markdown
5. ✅ Pre-upload mechanism for attachments
6. ✅ Proper linking of attachments to created items
7. ✅ Client and server-side validation
8. ✅ Security measures implemented

## Security Summary
**No security vulnerabilities found** during CodeQL scan.

Security measures implemented:
- ✅ File type whitelist (no executable types)
- ✅ File size validation (prevents DoS)
- ✅ Filename sanitization (prevents header injection)
- ✅ Token-based authentication (prevents unauthorized access)
- ✅ Project ownership verification (prevents data leakage)
- ✅ Input validation (prevents injection attacks)

## Conclusion
This implementation successfully adds file upload and rich text editing capabilities to the customer portal embed, meeting all requirements from issue #227 while maintaining security and code quality standards.
