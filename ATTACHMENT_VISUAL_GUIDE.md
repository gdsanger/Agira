# Attachment ListView Enhancements - Visual Guide

## Overview
This implementation adds 4 key features to the Attachment ListView in both Item and Project detail views.

## Feature 1: FileType Avatar (First Column)

### Before
```
| Filename           | Size  | Uploaded  | ...
|-------------------:|------:|----------:|----
| document.pdf       | 2.5MB | 2024-01-15| ...
| report.docx        | 1.2MB | 2024-01-14| ...
| README.md          | 15KB  | 2024-01-13| ...
```

### After
```
| Typ  | Filename           | Size  | Uploaded  | ...
|-----:|-------------------:|------:|----------:|----
| PDF  | document.pdf       | 2.5MB | 2024-01-15| ...
| DOCX | report.docx        | 1.2MB | 2024-01-14| ...
| MD   | README.md          | 15KB  | 2024-01-13| ...
```

**Visual:** Blue badge with file type in uppercase

**Supported Types:**
- Documents: PDF, DOC, DOCX, TXT, MD, HTML, XML, JSON, CSV
- Spreadsheets: XLS, XLSX  
- Presentations: PPT, PPTX
- Archives: ZIP, RAR, 7Z, TAR, GZ
- Images: JPG, PNG, GIF, BMP, SVG
- Media: MP3, MP4, AVI, MOV, WAV
- Code: PY, JS, JAVA, C, CPP, CS, GO, RB, PHP, SQL, SH, BAT, PS1
- Unknown: Shows uppercase extension (max 10 chars) or "FILE"

## Feature 2: AI Summary Action Button

### Location
Actions column, next to delete button

### Visual
```
[★] [🗑️]
 │    └── Delete button (existing)
 └── AI Summary button (NEW)
```

**Icon:** Star/sparkle icon (bi-stars from Bootstrap Icons)
**Color:** Outline info (blue)
**Tooltip:** "AI-Zusammenfassung anzeigen"

### Button States

**Enabled (Indexed):**
- Blue outline button
- Clickable
- Opens modal on click

**Disabled (Not Indexed):**
- Grayed out
- Not clickable  
- Tooltip: "Attachment not indexed in Weaviate"

### Modal Flow

1. **Click Button** → Modal opens with loading spinner
   ```
   ┌─────────────────────────────────────┐
   │ AI-Zusammenfassung            [×]   │
   ├─────────────────────────────────────┤
   │                                     │
   │      🔄 Zusammenfassung wird        │
   │         generiert...                │
   │                                     │
   ├─────────────────────────────────────┤
   │                      [Schließen]    │
   └─────────────────────────────────────┘
   ```

2. **Summary Generated** → Shows content
   ```
   ┌─────────────────────────────────────┐
   │ AI-Zusammenfassung            [×]   │
   ├─────────────────────────────────────┤
   │ 📄 document.pdf                     │
   │                                     │
   │ ┌─────────────────────────────────┐ │
   │ │ ★ AI-Zusammenfassung            │ │
   │ │                                 │ │
   │ │ [Generated summary text in     │ │
   │ │  German, 200-500 words about   │ │
   │ │  the document content...]      │ │
   │ │                                 │ │
   │ └─────────────────────────────────┘ │
   │                                     │
   │ ℹ️ Diese Zusammenfassung wurde      │
   │    automatisch durch KI generiert   │
   ├─────────────────────────────────────┤
   │                      [Schließen]    │
   └─────────────────────────────────────┘
   ```

3. **Error State** → Shows error message
   ```
   ┌─────────────────────────────────────┐
   │ AI-Zusammenfassung            [×]   │
   ├─────────────────────────────────────┤
   │ ⚠️ Not Indexed                      │
   │                                     │
   │ This attachment has not been        │
   │ indexed in Weaviate yet.            │
   │                                     │
   │ The attachment needs to be indexed  │
   │ before a summary can be generated.  │
   ├─────────────────────────────────────┤
   │                      [Schließen]    │
   └─────────────────────────────────────┘
   ```

## Feature 3: Filename Search

### Location
Above the attachment table, left side

### Visual
```
┌────────────────────────────────────────────────────┐
│ 🔍 | Dateiname suchen...                          │
└────────────────────────────────────────────────────┘
```

### Behavior
- **Real-time:** Updates list as you type
- **Debounce:** 300ms delay to prevent excessive requests
- **Case-insensitive:** "PDF" matches "document.pdf"
- **Substring:** "doc" matches "mydocument.pdf"
- **Combined:** Works with FileType filter (AND logic)

### Example
Search: "report"

**Before Filter:**
```
| Typ  | Filename           |
|-----:|-------------------:|
| PDF  | document.pdf       |
| DOCX | report.docx        |
| MD   | README.md          |
| PDF  | annual_report.pdf  |
```

**After Filter:**
```
| Typ  | Filename           |
|-----:|-------------------:|
| DOCX | report.docx        |
| PDF  | annual_report.pdf  |
```

## Feature 4: FileType Filter

### Location
Above the attachment table, right side

### Visual
```
┌────────────────────────────────────┐
│ Alle Dateitypen          ▼        │
├────────────────────────────────────┤
│ Alle Dateitypen                   │
│ DOCX                              │
│ MD                                │
│ PDF                               │
└────────────────────────────────────┘
```

### Options
- **"Alle Dateitypen"** - Shows all (default)
- **Distinct values** - Only types present in current attachments
- **Alphabetically sorted**

### Behavior
- **Instant:** Updates list immediately on selection
- **Combined:** Works with search (AND logic)
- **Persistent:** Preserved across pagination

### Example
Filter: "PDF"

**Before Filter:**
```
| Typ  | Filename           |
|-----:|-------------------:|
| PDF  | document.pdf       |
| DOCX | report.docx        |
| MD   | README.md          |
| PDF  | annual_report.pdf  |
```

**After Filter:**
```
| Typ  | Filename           |
|-----:|-------------------:|
| PDF  | document.pdf       |
| PDF  | annual_report.pdf  |
```

## Feature Combination: Search + Filter

### Example
Search: "report" + Filter: "PDF"

**Original List:**
```
| Typ  | Filename              |
|-----:|----------------------:|
| PDF  | document.pdf          |
| DOCX | report.docx           |
| MD   | README.md             |
| PDF  | annual_report.pdf     |
| PDF  | monthly_summary.pdf   |
```

**Filtered Result (AND logic):**
```
| Typ  | Filename           |
|-----:|-------------------:|
| PDF  | annual_report.pdf  |
```

Only items matching BOTH:
- Filename contains "report" (case-insensitive)
- File type is "PDF"

## Empty States

### No Attachments
```
        📎
  No attachments yet
Upload a file to get started!
```

### No Results (After Filter)
```
        📎
  Keine Attachments gefunden
Versuchen Sie eine andere Suche oder Filter
```

## Complete Table Layout

### Item Detail View
```
┌──────────────────────────────────────────────────────────────────────┐
│ Attachments                                                          │
├──────────────────────────────────────────────────────────────────────┤
│ [Drag & Drop Upload Zone]                                           │
├──────────────────────────────────────────────────────────────────────┤
│ 🔍 Search...          │ Filter: [All Types ▼]                       │
├──────┬─────────────────┬───────┬───────────┬──────────┬─────┬───────┤
│ Typ  │ Filename        │ Size  │ Uploaded  │ By       │ W.  │ Acts  │
├──────┼─────────────────┼───────┼───────────┼──────────┼─────┼───────┤
│ PDF  │ document.pdf    │ 2.5MB │ 01-15     │ John Doe │ ✓   │ [★][🗑]│
│ DOCX │ report.docx     │ 1.2MB │ 01-14     │ Jane S.  │ ✓   │ [★][🗑]│
│ MD   │ README.md       │ 15KB  │ 01-13     │ John Doe │ ×   │ [⊘][🗑]│
└──────┴─────────────────┴───────┴───────────┴──────────┴─────┴───────┘
```

### Project Detail View
Same as Item view, plus:
```
Page 1 of 3
[First] [Previous] [Next] [Last]
Showing 1 to 10 of 27 attachments
```

## Technical Details

### HTMX Integration
All filters use HTMX for seamless updates:
- No page refresh required
- Partial content replacement
- Loading states handled automatically
- Browser back/forward compatible

### JavaScript Auto-Disable
```javascript
// Runs after Weaviate status buttons load
document.addEventListener('htmx:afterSettle', function() {
    // For each summary button
    summaryButtons.forEach(btn => {
        // Check corresponding Weaviate status
        if (weaviateStatus === 'not-indexed') {
            // Disable button
            btn.disabled = true;
            btn.title = 'Attachment not indexed in Weaviate';
        }
    });
});
```

### Database Queries
```python
# Get attachments with filters
attachments = Attachment.objects.filter(...)

# Apply search (client-side)
if search_query:
    attachments = [a for a in attachments 
                   if search_query.lower() in a.original_name.lower()]

# Apply file type filter (client-side)
if file_type_filter:
    attachments = [a for a in attachments 
                   if a.file_type == file_type_filter]

# Get distinct file types for dropdown
file_types = sorted(set(a.file_type for a in attachments if a.file_type))
```

## Accessibility

- **Keyboard Navigation:** All interactive elements are keyboard accessible
- **Screen Readers:** Proper ARIA labels and semantic HTML
- **Focus Management:** Modal focus trap
- **Color Contrast:** Meets WCAG AA standards
- **Alternative Text:** Icons have descriptive titles

## Browser Compatibility

- **Modern Browsers:** Chrome, Firefox, Edge, Safari (latest 2 versions)
- **HTMX Support:** Progressive enhancement (works without JS, better with JS)
- **Responsive:** Mobile-friendly table layout

## Performance

- **Initial Load:** < 1s for typical lists (< 100 attachments)
- **Search:** Real-time with 300ms debounce
- **Filter:** Instant (client-side)
- **AI Summary:** 2-5s (depends on Weaviate + AI service)
- **Pagination:** 10 items/page (project view)

## Error Scenarios

1. **Weaviate Unavailable:** Warning shown in summary modal
2. **Attachment Not Indexed:** Info message + disabled button
3. **No Text Content:** Error in summary modal
4. **AI Service Error:** Error message with details
5. **Network Error:** HTMX retry logic + error state

## Future Enhancements

Potential next steps:
- Multi-select file type filter
- Date range filter
- File size filter
- Sort by columns (name, size, date)
- Batch AI summary generation
- Summary caching
- Export filtered list
- Tag-based filtering
