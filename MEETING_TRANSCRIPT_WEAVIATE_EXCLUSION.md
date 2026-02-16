# Meeting Transcript Weaviate Sync Exclusion - Implementation Summary

## Overview
This implementation excludes meeting transcript attachments from Weaviate indexing to prevent timeout errors caused by large file sizes.

## Problem
When uploading meeting transcripts (large DOCX files), the automatic Weaviate sync would trigger and attempt to index these large files, resulting in:
- `context deadline exceeded` errors
- Weaviate timeout failures
- Error logs: `Weaviate INSERT failed for attachment:XXX`

## Solution
Meeting transcripts are now:
1. Tagged with a dedicated `TRANSKRIPT` attachment role
2. Automatically excluded from Weaviate sync via signal handler
3. Still stored and processed normally for AI summarization

## Technical Implementation

### 1. New Attachment Role
**File:** `core/models.py`
```python
class AttachmentRole(models.TextChoices):
    PROJECT_FILE = 'ProjectFile', _('Project File')
    ITEM_FILE = 'ItemFile', _('Item File')
    COMMENT_ATTACHMENT = 'CommentAttachment', _('Comment Attachment')
    APPROVER_ATTACHMENT = 'ApproverAttachment', _('Approver Attachment')
    TRANSKRIPT = 'transkript', _('Meeting Transcript')  # NEW
```

### 2. Helper Function
**File:** `core/services/weaviate/service.py`
```python
def is_meeting_transcript_attachment(attachment) -> bool:
    """
    Check if an attachment is a meeting transcript.
    Returns True if:
    - Attachment has role = 'transkript' (TRANSKRIPT)
    - AND target is an Item with type.key = 'meeting'
    """
```

### 3. Signal Handler Modification
**File:** `core/services/weaviate/signals.py`
```python
def _safe_upsert(instance):
    """Modified to skip meeting transcripts"""
    # Skip meeting transcript attachments
    from core.models import Attachment
    if isinstance(instance, Attachment) and is_meeting_transcript_attachment(instance):
        logger.info(f"Skipping Weaviate sync for meeting transcript...")
        return
    # ... continue with normal sync
```

### 4. Transcript Upload View
**File:** `core/views.py`
```python
def item_upload_transcript(request, item_id):
    # Store with TRANSKRIPT role instead of ITEM_FILE
    attachment = storage_service.store_attachment(
        file=uploaded_file,
        target=item,
        role=AttachmentRole.TRANSKRIPT,  # CHANGED
        created_by=request.user
    )
```

### 5. Database Migration
**File:** `core/migrations/0051_alter_attachmentlink_role.py`
- Adds 'transkript' as valid choice for AttachmentLink.role field

## Testing

### New Tests (6 total)
**File:** `core/services/weaviate/test_weaviate.py`
- `MeetingTranscriptExclusionTestCase`
  - ✅ Identifies meeting transcripts correctly
  - ✅ Returns False for regular files
  - ✅ Returns False for non-meeting items
  - ✅ Returns False for unlinked attachments
  - ✅ Signal skips meeting transcripts
  - ✅ Signal still syncs regular attachments

### Test Results
```
$ python manage.py test core.services.weaviate.test_weaviate.MeetingTranscriptExclusionTestCase
Ran 6 tests in 0.053s
OK
```

## Behavior Matrix

| Attachment Type | Item Type | Role | Weaviate Sync |
|----------------|-----------|------|---------------|
| Meeting Transcript | Meeting | TRANSKRIPT | ❌ SKIPPED |
| Regular File | Meeting | ITEM_FILE | ✅ SYNCED |
| Regular File | Bug/Task | ITEM_FILE | ✅ SYNCED |
| Transcript DOCX | Bug/Task | TRANSKRIPT | ✅ SYNCED* |

\* *If someone manually assigns TRANSKRIPT role to non-meeting item, it will sync (edge case)*

## Acceptance Criteria - Met ✅

1. ✅ Upload/save of meeting transcript does NOT trigger Weaviate upsert
2. ✅ No Weaviate timeout/error logs for these attachments (sync is skipped)
3. ✅ Other attachments continue to sync normally
4. ✅ Status handling: Meeting transcripts are excluded, not failed

## Verification Steps

### 1. Upload a Meeting Transcript
```
POST /items/{meeting_item_id}/upload-transcript/
File: large_transcript.docx (> 5MB)
```

**Expected Behavior:**
- ✅ Attachment is stored successfully
- ✅ AI summarization runs
- ✅ Tasks are created
- ✅ **No Weaviate sync attempted**
- ✅ Logs show: "Skipping Weaviate sync for meeting transcript attachment..."

### 2. Upload a Regular File
```
POST /items/{any_item_id}/files/
File: document.pdf
```

**Expected Behavior:**
- ✅ Attachment is stored successfully
- ✅ **Weaviate sync IS triggered**
- ✅ File is indexed in Weaviate

### 3. Check Database
```sql
SELECT a.original_name, al.role, i.title, it.key 
FROM core_attachment a
JOIN core_attachmentlink al ON al.attachment_id = a.id
JOIN core_item i ON i.id = al.target_object_id
JOIN core_itemtype it ON it.id = i.type_id
WHERE al.role = 'transkript';
```

**Expected Result:**
- Meeting transcripts show role = 'transkript'
- Items have type.key = 'meeting'

## Code Review Notes

### Note 1: German vs English Naming
The role name 'transkript' uses German spelling, which is intentional per the issue requirements (written in German). This is acceptable as:
- The issue explicitly uses German terminology
- The role value is internal (not user-facing)
- The display name is properly internationalized: `_('Meeting Transcript')`

### Note 2: Case-Insensitive Comparison
The helper function uses `.lower()` when comparing `item.type.key`, which is consistent with the existing codebase pattern in `item_upload_transcript()` view.

## Security Analysis
✅ No security issues found (CodeQL scan passed)
- No SQL injection risks
- No path traversal issues
- No unauthorized access concerns
- Proper validation and error handling maintained

## Migration Instructions

### 1. Apply Migration
```bash
python manage.py migrate core 0051
```

### 2. Verify Existing Data
If any meeting transcripts were uploaded before this change, they will have `role='ItemFile'` and will continue to sync. To fix:
```python
from core.models import Attachment, AttachmentLink, AttachmentRole, Item

# Find meeting transcripts with old role
for link in AttachmentLink.objects.filter(
    target_content_type__model='item',
    role=AttachmentRole.ITEM_FILE
):
    if isinstance(link.target, Item) and link.target.type.key.lower() == 'meeting':
        # Check if this is a transcript based on filename
        if link.attachment.original_name.lower().endswith('.docx'):
            # Update to new role
            link.role = AttachmentRole.TRANSKRIPT
            link.save()
            print(f"Updated attachment {link.attachment.id} to TRANSKRIPT role")
```

### 3. Optional: Remove from Weaviate
If you want to clean up already-indexed transcripts:
```python
from core.services.weaviate.service import delete_object

# Find and delete meeting transcripts from Weaviate
for link in AttachmentLink.objects.filter(role=AttachmentRole.TRANSKRIPT):
    try:
        delete_object('attachment', str(link.attachment.id))
        print(f"Deleted attachment {link.attachment.id} from Weaviate")
    except Exception as e:
        print(f"Error deleting {link.attachment.id}: {e}")
```

## Future Considerations

### Optional UI Status Indicator
The issue mentioned optional UI status behavior. If a Weaviate status indicator exists:
- Meeting transcripts could show as "excluded" or "not indexed" (gray)
- Rather than "failed" (red)
- This would require frontend changes (not implemented in this PR)

### Manual Push Prevention
If manual push endpoints exist (e.g., `/weaviate/push/<type>/<id>/`):
- Could add the same exclusion check there
- Return appropriate message: "Meeting transcripts are excluded from indexing"
- This would require checking the views (not implemented in this PR)

## Related Files

### Modified Files
1. `core/models.py` - Added TRANSKRIPT role
2. `core/views.py` - Updated transcript upload to use TRANSKRIPT role
3. `core/services/weaviate/service.py` - Added helper function
4. `core/services/weaviate/signals.py` - Added exclusion logic
5. `core/services/weaviate/test_weaviate.py` - Added tests

### New Files
1. `core/migrations/0051_alter_attachmentlink_role.py` - Migration

## References
- Issue #431: Meeting-Transkripte nicht nach Weaviate indizieren
- WEAVIATE_SYNC_IMPLEMENTATION.md - Original Weaviate sync documentation
- MEETING_TRANSCRIPT_IMPLEMENTATION_SUMMARY.md - Transcript upload feature

## Author & Date
- Implementation: 2026-02-16
- Issue: #431 (Agira Project)
