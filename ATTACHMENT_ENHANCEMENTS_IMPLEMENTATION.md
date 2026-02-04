# Attachment ListView Enhancement Implementation

## Overview
This document describes the implementation of enhancements to the Attachment ListView in both Item and Project detail views.

## Features Implemented

### 1. FileType Avatar (Column 1)
- **Location**: First column in attachment tables
- **Display**: Blue badge showing file type (e.g., PDF, DOCX, MD, HTML)
- **Implementation**: 
  - New `file_type` CharField in Attachment model (max 20 chars, indexed)
  - Auto-populated via `determine_file_type()` method on save
  - Supports 46+ common file extensions
  - Fallback to MIME type detection
  - Default: "FILE" for unknown types

### 2. AI Summary Action
- **Location**: Actions column, info icon button
- **Functionality**:
  - Fetches text content from Weaviate object
  - Calls `summarize-text-agent` to generate summary
  - Displays result in modal
  - Auto-disables when attachment not indexed in Weaviate
- **Implementation**:
  - New view: `attachment_ai_summary(request, attachment_id)`
  - URL: `/attachments/<id>/ai-summary/`
  - Modal templates: `attachment_summary_modal.html` + content template
  - Agent config: `agents/summarize-text-agent.yml`

### 3. Filename Search
- **Location**: Search input above attachment table
- **Functionality**:
  - Case-insensitive substring search in filenames
  - Real-time filtering with 300ms debounce
  - Works in combination with file type filter (AND logic)
  - HTMX-powered for seamless UX
- **Implementation**:
  - Query parameter: `?search=<query>`
  - Client-side filtering in view
  - Preserved across pagination in project view

### 4. FileType Filter
- **Location**: Dropdown next to search
- **Functionality**:
  - Shows distinct file types from current attachments
  - "Alle Dateitypen" option to clear filter
  - Works in combination with search (AND logic)
  - Preserved across pagination in project view
- **Implementation**:
  - Query parameter: `?file_type=<type>`
  - Distinct values calculated from attachment list
  - HTMX-powered for instant filtering

## Database Changes

### Migration: 0042_add_file_type_to_attachment
```python
operations = [
    migrations.AddField(
        model_name='attachment',
        name='file_type',
        field=models.CharField(
            blank=True, 
            db_index=True, 
            help_text='File type determined from extension (e.g., PDF, DOCX, MD)', 
            max_length=20
        ),
    ),
]
```

### Model Changes
```python
class Attachment(models.Model):
    # ... existing fields ...
    file_type = models.CharField(max_length=20, blank=True, db_index=True, 
                                  help_text="File type determined from extension")
    
    def determine_file_type(self) -> str:
        """Determine file type from filename or MIME type"""
        # See core/models.py for full implementation
    
    def save(self, *args, **kwargs):
        """Auto-populate file_type if not set"""
        if not self.file_type:
            self.file_type = self.determine_file_type()
        super().save(*args, **kwargs)
```

## Backfilling Existing Data

Use the management command to backfill file_type for existing attachments:

```bash
# Dry run to see what would be updated
python manage.py backfill_attachment_file_types --dry-run

# Actually update the records
python manage.py backfill_attachment_file_types
```

## AI Agent Configuration

### summarize-text-agent.yml
```yaml
name: summarize-text-agent
description: Erstellt eine prägnante Zusammenfassung eines Textes in deutscher Sprache.
provider: OpenAI
model: gpt-5.2
role: Du bist ein Experte für das Erstellen prägnanter und informativer Zusammenfassungen.
task: |
  Du erhältst einen Text und sollst daraus eine Zusammenfassung erstellen.
  
  Anforderungen:
  - Fasse die wichtigsten Punkte und Kernaussagen zusammen
  - Halte dich an eine Länge von ca. 200-500 Wörtern
  - Verwende eine klare und verständliche Sprache
  - Strukturiere die Zusammenfassung logisch
  - Antworte in deutscher Sprache
  - Gib nur die Zusammenfassung zurück
```

## View Changes

### item_attachments_tab
```python
def item_attachments_tab(request, item_id):
    # Get query parameters
    search_query = request.GET.get('search', '').strip()
    file_type_filter = request.GET.get('file_type', '').strip()
    
    # Fetch attachments
    # ... existing code ...
    
    # Apply filters
    if search_query:
        attachments = [a for a in attachments if search_query.lower() in a.original_name.lower()]
    
    if file_type_filter:
        attachments = [a for a in attachments if a.file_type == file_type_filter]
    
    # Get distinct file types for dropdown
    file_types = sorted(set(a.file_type for a in all_attachments if a.file_type))
    
    # Return with filter state
    context = {
        'item': item,
        'attachments': attachments,
        'file_types': file_types,
        'search_query': search_query,
        'file_type_filter': file_type_filter,
    }
```

### attachment_ai_summary (new)
```python
@login_required
def attachment_ai_summary(request, attachment_id):
    """Generate AI summary for an attachment using text from Weaviate."""
    # Check Weaviate availability
    # Fetch Weaviate object
    # Extract text content
    # Execute AI agent
    # Return modal content
```

## Template Changes

### item_attachments_tab.html
Key additions:
- Search input with HTMX trigger
- FileType dropdown with HTMX trigger
- FileType badge column
- AI summary button with modal trigger
- JavaScript to auto-disable summary button based on Weaviate status
- Empty state handling for filtered results

### project_attachments_tab.html
Same as item template, plus:
- Pagination link preservation of filter parameters
- Proper handling of filter state across pages

## URL Routes

New route:
```python
path('attachments/<int:attachment_id>/ai-summary/', 
     views.attachment_ai_summary, 
     name='attachment-ai-summary'),
```

## Supported File Types

The system recognizes 46+ file types:

**Documents**: PDF, DOC, DOCX, TXT, MD, HTML, XML, JSON, CSV
**Spreadsheets**: XLS, XLSX
**Presentations**: PPT, PPTX
**Archives**: ZIP, RAR, 7Z, TAR, GZ
**Images**: JPG, PNG, GIF, BMP, SVG
**Media**: MP3, MP4, AVI, MOV, WAV
**Code**: PY, JS, JAVA, C, CPP, CS, GO, RB, PHP, SQL, SH, BAT, PS1

Unknown extensions are converted to uppercase (max 10 chars).

## User Experience

### Search Flow
1. User types in search box
2. 300ms debounce delay
3. HTMX sends request with search parameter
4. Server filters attachments
5. Attachment list updates without page refresh

### Filter Flow
1. User selects file type from dropdown
2. HTMX sends request immediately
3. Server filters attachments
4. Attachment list updates without page refresh

### AI Summary Flow
1. User clicks summary icon button
2. Modal opens with loading spinner
3. HTMX requests summary from server
4. Server checks Weaviate object exists
5. Server fetches text content
6. AI agent generates summary
7. Modal content updates with summary or error

### Button Auto-Disable
1. On page load, Weaviate status buttons are loaded via HTMX
2. JavaScript listens for HTMX afterSettle event
3. For each summary button, checks corresponding Weaviate status
4. If status shows object doesn't exist (btn-danger), disables summary button
5. Updates tooltip to indicate attachment not indexed

## Error Handling

### AI Summary Errors
- Weaviate not available: Shows warning message
- Attachment not indexed: Shows info message
- No text content: Shows error message
- AI agent failure: Shows error with details
- Loading state shown during processing

### Search/Filter
- Empty results: Shows "Keine Attachments gefunden" with suggestion
- No attachments: Shows "No attachments yet" with upload prompt

## Performance Considerations

- Client-side filtering (acceptable for typical list sizes)
- Database index on file_type for efficient queries
- HTMX for partial page updates (reduces bandwidth)
- 300ms debounce on search prevents excessive requests

## Testing

### File Type Determination
All 16 test cases passed:
- Extension-based detection (PDF, DOCX, MD, etc.)
- MIME type fallback
- Unknown extension handling
- No extension handling

### Manual Testing Required
1. Upload various file types, verify badges
2. Test search with various queries
3. Test file type filter
4. Test combined search + filter
5. Test AI summary with indexed attachment
6. Test AI summary with non-indexed attachment
7. Test pagination with filters (project view)

## Future Enhancements

Potential improvements:
1. Server-side filtering for large lists (1000+ attachments)
2. More file type icons/colors
3. Batch summary generation
4. Summary caching
5. Advanced search (tags, date range, size)
6. Multiple file type selection

## Migration Path

1. Apply migration: `python manage.py migrate`
2. Backfill existing attachments: `python manage.py backfill_attachment_file_types`
3. New uploads will auto-populate file_type
4. Users can immediately use search/filter features
5. AI summary requires Weaviate indexing to be active

## Security Considerations

- AI summary view requires login
- Respects existing attachment access controls
- No new permissions required
- Agent uses existing AI service infrastructure
- Content sanitization via Django templates
