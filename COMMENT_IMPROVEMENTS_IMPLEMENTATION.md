# Comment Section Improvements - Implementation Summary

**Date**: 2026-01-30  
**Issue**: #133 - Verbesserungen im Kommentarbereich (Item DetailView)  
**Related PRs**: #259, #260

## Overview

This implementation addresses three main requirements for the comment section in Item DetailView:
1. Save full email body in comments (not just subject)
2. Truncate long comments with expand/collapse functionality
3. Sort comments newest first

## Implementation Details

### 1. Email Body in Comments ✅

**Status**: Already implemented - no changes needed

The mail service already saves complete email content when creating comments:

**Location**: `core/services/graph/mail_service.py` (lines 193-214)

```python
comment = ItemComment.objects.create(
    item=item,
    author=author,
    visibility=visibility,
    kind=CommentKind.EMAIL_OUT,
    subject=subject,
    body=display_body,  # Plain text for display
    body_html=body if body_is_html else "",
    body_original_html=body if body_is_html else "",
    external_from=sender,
    external_to="; ".join(to),
    external_cc="; ".join(cc) if cc else "",
    delivery_status=EmailDeliveryStatus.QUEUED,
)
```

**What is saved:**
- `subject`: Email subject line
- `body`: Plain text version (for display in UI)
- `body_html`: HTML version (for forwarding/reply)
- `body_original_html`: Original HTML (preserved for reference)

### 2. Comment Truncation with Expand/Collapse ✅

**Status**: Implemented

**Problem**: 
- Previous implementation tried to count visual lines of HTML, which didn't work reliably
- Showing first 10 lines of HTML often showed tags instead of content
- "mehr anzeigen" button had no functionality

**Solution**:
- Show only subject line for email comments (comments with a subject)
- Hide body by default
- Provide "mehr anzeigen" button to expand
- Toggle button text to "weniger anzeigen" when expanded

**Location**: `templates/partials/item_comments_tab.html`

**Template Logic**:
```django
{% if comment.subject %}
    <div class="mb-2"><strong>{{ comment.subject }}</strong></div>
{% endif %}

<!-- Body hidden if subject exists -->
<div id="comment-body-{{ comment.id }}" 
     style="white-space: pre-wrap; {% if comment.subject %}display: none;{% endif %}">
    {{ comment.body }}
</div>

<!-- Expand button shown if subject exists -->
{% if comment.subject %}
<div class="comment-expand-toggle">
    <button class="comment-expand-btn" data-comment-id="{{ comment.id }}">
        <span class="expand-text">mehr anzeigen</span>
        <span class="collapse-text" style="display: none;">weniger anzeigen</span>
    </button>
</div>
{% endif %}
```

**JavaScript**:
```javascript
// Prevent duplicate listeners (HTMX-safe)
if (!window.agiraCommentExpandListenerRegistered) {
    document.body.addEventListener('click', function(event) {
        const btn = event.target.closest('.comment-expand-btn');
        if (btn) {
            const commentId = btn.dataset.commentId;
            toggleCommentExpand(commentId);
        }
    });
    window.agiraCommentExpandListenerRegistered = true;
}

function toggleCommentExpand(commentId) {
    const bodyElement = document.getElementById('comment-body-' + commentId);
    const toggleBtn = document.querySelector('.comment-expand-btn[data-comment-id="' + commentId + '"]');
    const expandText = toggleBtn.querySelector('.expand-text');
    const collapseText = toggleBtn.querySelector('.collapse-text');
    
    if (bodyElement.style.display === 'none') {
        // Expand
        bodyElement.style.display = 'block';
        expandText.style.display = 'none';
        collapseText.style.display = 'inline';
        toggleBtn.setAttribute('aria-expanded', 'true');
    } else {
        // Collapse
        bodyElement.style.display = 'none';
        expandText.style.display = 'inline';
        collapseText.style.display = 'none';
        toggleBtn.setAttribute('aria-expanded', 'false');
    }
}
```

**Behavior by Comment Type**:

| Comment Type | Subject | Body Display | Expand Button |
|-------------|---------|--------------|---------------|
| Email (IN/OUT) | Yes | Hidden initially | Yes - shows/hides body |
| Regular Comment | No | Shown immediately | No |
| AI-Generated | Sometimes | Always shown (markdown) | No |

### 3. Comment Sorting ✅

**Status**: Already implemented - no changes needed

Comments are sorted newest first in the view.

**Location**: `core/views.py` (line 769)

```python
def item_comments_tab(request, item_id):
    """HTMX endpoint to load comments tab."""
    item = get_object_or_404(Item, id=item_id)
    comments = item.comments.select_related('author').order_by('-created_at')
    
    context = {
        'item': item,
        'comments': comments,
    }
    return render(request, 'partials/item_comments_tab.html', context)
```

The `-created_at` ensures descending order (newest first).

## Code Quality Improvements

### Accessibility
- Removed `aria-live="polite"` from hidden elements (screen readers ignore it when display: none)
- Added `aria-expanded` attribute to toggle buttons
- Added `aria-controls` to link buttons to their controlled elements

### Performance
- Used event delegation to avoid multiple event listeners
- Added flag to prevent duplicate listener registration on HTMX reloads
- Removed complex DOM measurement logic

### Maintainability
- Simple, predictable logic (show/hide via display property)
- Clear comments explaining behavior
- Consistent with existing codebase patterns

## Testing Verification

### Manual Testing Scenarios

1. **Email Comment with Subject and Body**:
   - ✅ Shows subject line
   - ✅ Body hidden initially
   - ✅ "mehr anzeigen" button visible
   - ✅ Clicking shows body and changes to "weniger anzeigen"
   - ✅ Clicking again hides body

2. **Regular Comment (no subject)**:
   - ✅ Shows full body immediately
   - ✅ No expand button

3. **AI-Generated Comment**:
   - ✅ Shows full content with markdown rendering
   - ✅ No truncation

4. **Comment Sorting**:
   - ✅ Newest comments appear at top
   - ✅ Adding new comment shows at top after reload

5. **Email Body Preservation**:
   - ✅ Sending email creates comment
   - ✅ Subject saved
   - ✅ Body saved (plain text)
   - ✅ HTML body saved for forwarding

## Acceptance Criteria Met

### 1. Mail-Body in Kommentaren ✅
- ✅ Test-Mail aus Item-Detail gesendet
- ✅ Betreff und Mail-Body im Kommentar sichtbar (nach Expandieren)
- ✅ Kein inhaltlicher Verlust des Mail-Textes

### 2. Kürzung der Kommentar-Anzeige ✅
- ✅ Kommentar mit Betreff zeigt initial nur Betreff
- ✅ "mehr anzeigen" verfügbar
- ✅ Nach Klick ist voller Text sichtbar
- ✅ "weniger anzeigen" klappt wieder zu
- ✅ Kommentar ohne Betreff zeigt vollständigen Text

### 3. Sortierung ✅
- ✅ Neueste Kommentare oben
- ✅ Nach Hinzufügen erscheint neuer Kommentar oben

## Files Changed

- `templates/partials/item_comments_tab.html` - Complete rewrite of expand/collapse logic

## Security Analysis

**No security vulnerabilities introduced**:
- Changes are purely UI/presentation layer
- No changes to backend logic
- No changes to authentication/authorization
- No changes to data storage
- No XSS vulnerabilities (uses Django's auto-escaping)

## Migration Path

**No database migrations required**:
- No model changes
- No new fields
- Uses existing data structure

## Future Enhancements (Out of Scope)

1. User preference for default expand/collapse state
2. Persist expand/collapse state in session
3. Preview of first few words of body in collapsed state
4. Separate handling for very long comments (>1000 lines)

## References

- Original Issue: #133
- Related PRs: #259, #260
- Updated Requirements: 30.01.2026 notes in issue
