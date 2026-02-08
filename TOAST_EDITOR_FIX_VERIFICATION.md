# Toast UI Editor Bug Fix - Verification Guide

## Issue Summary
Fixed RangeError in Toast UI Editor when using Enter key and Paste inside markdown code blocks (marked with ```).

**Related Issue:** #339  
**GitHub Issues:** 
- https://github.com/nhn/tui.editor/issues/1349
- https://github.com/nhn/tui.editor/issues/2957

## Root Cause
Toast UI Editor has a known upstream bug where pasted HTML content causes internal state corruption in markdown mode, particularly within code blocks. This results in:
- Enter key not creating line breaks
- Paste operations failing
- `RangeError: Index X out of range` console errors

## Solution Implemented
Added a `change` event handler workaround that:
1. Monitors editor content changes
2. Detects and removes problematic HTML tags
3. Converts HTML formatting to proper markdown syntax
4. Prevents RangeError by maintaining consistent editor state

## Files Modified
1. `templates/item_form.html` - 3 editors (description, user_input, solution_description)
2. `templates/project_form.html` - 1 editor (description)
3. `templates/embed/issue_create.html` - 1 editor (description)

## Manual Testing Instructions

### Test Route 1: /items/new/
1. Navigate to `/items/new/`
2. Ensure editor is in **Markdown mode** (check the mode toggle)
3. Type or paste the following code block:
   ```
   ```
   test line 1
   ```
   ```
4. Place cursor at the end of "test line 1"
5. Press **Enter** → Expected: New line created within code block
6. Type "test line 2"
7. Press **Enter** again → Expected: Another new line
8. Copy multi-line text from any source
9. Paste with **Ctrl+V** → Expected: Text pasted successfully
10. Check browser console → Expected: No RangeError

### Test Route 2: /items/338/edit/ (or any existing item)
1. Navigate to `/items/338/edit/` (adjust ID as needed)
2. Locate any of the three editors (Description, User Input, Solution)
3. Switch to **Markdown mode**
4. Follow steps 3-10 from Test Route 1
5. Verify fix works for all three editors independently

### Test Route 3: /projects/1/edit/ (or any existing project)
1. Navigate to `/projects/1/edit/` (adjust ID as needed)
2. Locate the Description editor
3. Switch to **Markdown mode**
4. Follow steps 3-10 from Test Route 1

### Test Route 4: /projects/new
1. Navigate to `/projects/new`
2. Locate the Description editor
3. Switch to **Markdown mode**
4. Follow steps 3-10 from Test Route 1

### Test Route 5: Embed Form (if accessible)
1. Navigate to an embed project issue creation form
2. Locate the Description editor
3. Follow steps 3-10 from Test Route 1

## Expected Behavior (Acceptance Criteria)
- ✅ Enter key creates line breaks within ``` code blocks
- ✅ Paste works within ``` code blocks (single and multi-line text)
- ✅ No `RangeError` exceptions in browser console
- ✅ Behavior is consistent regardless of previous input
- ✅ HTML tags from pasted content are automatically cleaned

## Edge Cases to Test
1. **Mixed content paste**: Paste formatted text with bold, italics, links
   - Expected: HTML converted to markdown syntax
2. **Large code blocks**: Create a code block with 50+ lines
   - Expected: All lines accept Enter and Paste
3. **Multiple code blocks**: Create 3 code blocks in sequence
   - Expected: Each block works independently
4. **Rapid typing**: Type quickly within a code block
   - Expected: No lag or errors
5. **Mode switching**: Switch between Markdown and WYSIWYG modes
   - Expected: No data loss or errors

## Regression Testing
Test that normal editor functionality still works:
- ✅ WYSIWYG mode works as before
- ✅ Regular markdown editing (outside code blocks)
- ✅ Image uploads (in embed form)
- ✅ Form submission and data persistence
- ✅ Editor height constraints remain enforced

## Technical Details

### Workaround Implementation
```javascript
function setupEditorWorkaround(editor) {
    let isProcessing = false;
    
    editor.on('change', function() {
        if (isProcessing) return;
        
        try {
            isProcessing = true;
            const mdtext = editor.getMarkdown();
            
            // Clean up problematic HTML tags
            const cleanedMdText = mdtext
                .replace(/<\/?span[^>]*>/g, '')  // Remove span tags
                .replace(/<br[\s/]*>/g, '')      // Remove <br>
                .replace(/<\/?u>/g, '')          // Remove underline tags
                .replace(/<\/?strong>/g, '**')   // Convert strong to markdown
                .replace(/<\/?em>/g, '_');       // Convert em to markdown
            
            if (cleanedMdText !== mdtext) {
                editor.setMarkdown(cleanedMdText, false);
            }
        } catch (e) {
            console.warn('Editor cleanup warning:', e);
        } finally {
            isProcessing = false;
        }
    });
}
```

### Performance Considerations
- `isProcessing` flag prevents recursive calls
- Regex replacements only run when content changes
- `setMarkdown` only called when cleanup is needed
- Minimal performance impact on normal typing

## Known Limitations
- This is a workaround for an upstream bug in Toast UI Editor
- If Toast UI Editor releases a fix, this workaround can be removed
- The workaround focuses on the most common HTML tags that cause issues

## References
- Toast UI Editor GitHub: https://github.com/nhn/tui.editor
- Community workaround source: https://github.com/nhn/tui.editor/issues/1349
- Korean language code block issue: https://github.com/nhn/tui.editor/issues/2957

## Code Review & Security
- ✅ Code review completed - variable naming fixed to camelCase
- ✅ Security scan completed - no vulnerabilities detected
- ✅ Changes are minimal and focused
- ✅ No breaking changes to existing functionality
