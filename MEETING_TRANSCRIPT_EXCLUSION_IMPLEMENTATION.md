# Meeting Transcript Weaviate Exclusion Implementation

## Overview
This document describes the implementation of meeting transcript exclusion from Weaviate sync to prevent timeout errors caused by large transcript files.

## Problem Statement
Meeting transcripts are large files that cause Weaviate timeouts when being indexed. Error logs showed:
- `context deadline exceeded` errors during vectorization
- Weaviate INSERT failures for meeting transcript attachments
- Repeated sync attempts that always fail

Example error from logs:
```
[ERROR] Weaviate INSERT failed for attachment:597:
  Error: context deadline exceeded (Client.Timeout exceeded while awaiting headers)
```

## Solution Architecture

### 1. Identification Logic
Meeting transcripts are identified by TWO criteria (both must be true):
- **ItemType**: The linked Item has `type.key = 'meeting'` (case-insensitive)
- **AttachmentRole**: The AttachmentLink has `role = 'transkript'` (AttachmentRole.TRANSKRIPT)

### 2. Core Implementation

#### Service Layer (`core/services/weaviate/service.py`)

**Function: `is_meeting_transcript_attachment(attachment)`**
- Checks if an attachment is a meeting transcript
- Iterates through attachment's links
- Returns True if any link has role='transkript' AND targets a Meeting item
- Returns False otherwise

**Function: `is_excluded_from_sync(obj_type, obj_id)`**
- Centralized exclusion check for any object type
- Currently only checks attachments
- Returns tuple: (is_excluded: bool, reason: Optional[str])
- Reason is human-readable message for UI display

**Modified: `upsert_object(type, object_id)`**
- Added check: Skip if attachment is meeting transcript
- Logs info message when skipping
- Returns None instead of attempting sync

**Modified: `upsert_instance(instance, ...)`**
- Added check: Skip if attachment is meeting transcript
- Logs info message when skipping
- Returns None instead of attempting sync

#### Signal Layer (`core/services/weaviate/signals.py`)
**Note**: This was already implemented in previous PR #578, but included for completeness.

**Function: `_safe_upsert(instance)`**
- Checks if instance is meeting transcript before syncing
- Logs skip message and returns early
- Prevents automatic sync via post_save signal

#### View Layer (`core/views.py`)

**Function: `weaviate_status(request, object_type, object_id)`**
- Added exclusion check before checking existence
- If excluded: renders button with `excluded=True` flag
- Button shows as gray/disabled instead of red/failed

**Function: `weaviate_push(request, object_type, object_id)`**
- Added exclusion check before attempting push
- If excluded: renders modal with info message
- Prevents manual sync attempts that would fail

### 3. UI Implementation

#### Template: `templates/partials/weaviate_button.html`
Added new state for excluded objects:
```html
{% elif excluded %}
    <!-- Object is excluded from sync -->
    <button type="button" class="btn btn-outline-secondary" disabled
        title="This object is excluded from Weaviate indexing">
        <svg>...</svg>
        <svg><!-- dash circle icon --></svg>
    </button>
{% else %}
    <!-- Normal green/red button -->
{% endif %}
```

#### Template: `templates/partials/weaviate_modal_content.html`
Added new section for excluded objects:
```html
{% elif excluded %}
    <div class="alert alert-info" role="alert">
        <strong>Object Excluded from Weaviate</strong>
    </div>
    <p class="text-muted">
        {{ info_message|default:"..." }}
    </p>
{% elif error %}
    <!-- Error handling -->
{% endif %}
```

## Test Coverage

### Service Tests (`core/services/weaviate/test_weaviate.py`)

**Existing Tests** (from PR #578):
- `test_is_meeting_transcript_attachment_returns_true_for_transcript()`
- `test_is_meeting_transcript_attachment_returns_false_for_regular_file()`
- `test_is_meeting_transcript_attachment_returns_false_for_non_meeting_item()`
- `test_is_meeting_transcript_attachment_returns_false_for_unlinked()`
- `test_signal_skips_meeting_transcript()`
- `test_signal_syncs_regular_attachment()`

**New Tests** (this PR):
- `test_upsert_object_skips_meeting_transcript()` - Verifies upsert_object returns None
- `test_upsert_instance_skips_meeting_transcript()` - Verifies upsert_instance returns None
- `test_is_excluded_from_sync_returns_true_for_meeting_transcript()` - Tests helper function
- `test_is_excluded_from_sync_returns_false_for_regular_attachment()` - Tests helper function

**View Tests** (this PR):
- `test_weaviate_status_shows_excluded_for_meeting_transcript()` - Status endpoint shows excluded
- `test_weaviate_push_prevents_manual_sync_of_meeting_transcript()` - Push endpoint blocked
- `test_weaviate_status_allows_regular_attachment()` - Regular attachments work normally

## Behavior Matrix

| Scenario | Signal Sync | Manual Push | Status Button | Notes |
|----------|-------------|-------------|---------------|-------|
| Meeting transcript (transkript + Meeting) | ❌ Skipped | ❌ Blocked | 🔘 Gray/Disabled | Info message shown |
| Regular attachment | ✅ Synced | ✅ Allowed | 🟢 Green (exists) or 🔴 Red (not synced) | Normal behavior |
| Meeting item (non-transcript) | ✅ Synced | ✅ Allowed | 🟢/🔴 Normal | Only role=transkript excluded |
| Attachment on non-Meeting item | ✅ Synced | ✅ Allowed | 🟢/🔴 Normal | Only Meeting+transkript excluded |

## Code Flow

### Automatic Sync (via Signal)
```
1. Attachment saved → post_save signal triggered
2. signals._safe_upsert() called
3. ├─ is_meeting_transcript_attachment() → True?
4. │  └─ YES: Log skip message, return early ✅
5. └─ NO: Continue to transaction.on_commit(sync_to_weaviate)
6.         └─ upsert_instance() → Weaviate sync
```

### Manual Push (via View)
```
1. User clicks "Push to Weaviate" button
2. POST to weaviate_push view
3. ├─ is_excluded_from_sync() → (True, reason)?
4. │  └─ YES: Render modal with info alert ✅
5. └─ NO: Call upsert_object()
6.         └─ Checks again (defense in depth)
7.             └─ Syncs to Weaviate
```

### Status Check (via View)
```
1. Page loads or user clicks Weaviate button
2. GET to weaviate_status view
3. ├─ is_excluded_from_sync() → (True, reason)?
4. │  └─ YES: Render gray disabled button ✅
5. └─ NO: Check exists_object()
6.         └─ Render green (exists) or red (not synced)
```

## Security Validation

**CodeQL Scan Results**: ✅ 0 alerts
- No SQL injection vulnerabilities
- No XSS vulnerabilities
- No sensitive data exposure
- Type safety maintained (Tuple import for Python 3.8+)

## Acceptance Criteria

✅ **AC1**: Meeting transcripts (Meeting + transkript) NOT synced to Weaviate
- Implemented in signals, upsert_object, and upsert_instance

✅ **AC2**: No Weaviate timeout/error logs for these attachments
- No sync attempts = no errors

✅ **AC3**: Other attachments sync normally
- All checks are specific to meeting transcripts only

✅ **AC4**: Status UI shows "excluded" not "failed"
- Gray disabled button with dash icon
- Info message in modal

✅ **AC5**: Manual push prevented with clear message
- View checks exclusion before attempting push
- Info alert explains why excluded

✅ **AC6**: Comprehensive test coverage
- 11 total tests covering all scenarios
- Both excluded and non-excluded paths tested

## Implementation Checklist

- [x] Exclusion logic in signals (from PR #578)
- [x] Exclusion logic in upsert_object
- [x] Exclusion logic in upsert_instance
- [x] Centralized is_excluded_from_sync helper
- [x] View endpoint updates (status, push)
- [x] Template updates (button, modal)
- [x] Service-level tests
- [x] View-level tests
- [x] Code review completed
- [x] Type annotation compatibility fixed
- [x] CodeQL security scan passed

## Files Modified

1. `core/services/weaviate/service.py` - Core exclusion logic
2. `core/services/weaviate/signals.py` - Signal handler (from PR #578)
3. `core/views.py` - View endpoints
4. `templates/partials/weaviate_button.html` - Status button UI
5. `templates/partials/weaviate_modal_content.html` - Modal content UI
6. `core/services/weaviate/test_weaviate.py` - Tests

## Deployment Notes

### No Migration Required
This change only affects application logic, not database schema.

### No Configuration Changes
Works with existing ItemType (Meeting) and AttachmentRole (transkript).

### Backward Compatible
- Existing meeting transcripts simply won't sync anymore
- No need to clean up already-synced transcripts (they'll just remain)
- Regular attachments completely unaffected

### Rollback Plan
If issues arise, revert commits in reverse order:
1. 359f725 - Type annotation fix
2. 9e79c8e - Test additions
3. 94d95e9 - View and template changes
4. Keep PR #578 (signals) as it's the core safety net

## Future Enhancements

### Possible Extensions
1. **Exclusion by file size**: Exclude any attachment > X MB
2. **Exclusion by content type**: Exclude specific MIME types
3. **Admin override**: Allow force-sync via admin interface
4. **Bulk cleanup**: Command to remove existing meeting transcripts from Weaviate
5. **Metrics**: Track how many objects are excluded and why

### Monitoring
Recommended metrics to track:
- Number of meeting transcripts uploaded per day
- Number of exclusions triggered (check logs for "Skipping Weaviate sync")
- Weaviate error rate before/after implementation
- Average attachment sync time

## Related Issues

- **Issue #431**: Original feature request
- **PR #578**: First implementation (signals only)
- **PR #XXX**: This implementation (complete coverage)

## Conclusion

This implementation provides defense-in-depth exclusion of meeting transcripts from Weaviate sync:
1. **Signal layer**: Automatic sync blocked
2. **Service layer**: Programmatic sync blocked (upsert_object, upsert_instance)
3. **View layer**: Manual push blocked with clear UI feedback
4. **UI layer**: Status shown as "excluded" not "failed"

All acceptance criteria met. All tests passing. No security issues. Ready for deployment.
