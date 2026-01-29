# GitHub Issue Creation Mail Handling - Implementation Summary

## Overview
Successfully implemented mail handling for GitHub issue creation. When creating a GitHub issue through the UI, the item status is automatically changed to "WORKING" and a mail preview modal is shown if a MailActionMapping exists for the new status.

## Problem Statement (Issue #114)
The requirement (translated from German):
- When creating a GitHub issue, a status change occurs and the item is assigned to user "copilot"
- In this case, the mail handling event must also be triggered, as the status is set to "working"
- First, changes to the issue must be made and saved, then as in the normal flow, the module with the pre-filled mail must open where the user decides whether to send the mail or not

## Implementation Details

### 1. Backend Service Layer Changes

#### Modified: `core/services/github/service.py`

**Method: `create_issue_for_item()`**

Added functionality:
- New parameter `change_status_to_working` (default: True)
- Stores old status before making any changes
- Changes item status to WORKING if valid transition exists
- Uses ItemWorkflowGuard to validate transitions
- Thread-safe with `transaction.atomic()` and `select_for_update()`
- Logs status change activity via ActivityService
- Handles gracefully when Copilot user doesn't exist

```python
def create_issue_for_item(
    self,
    item: Item,
    *,
    title: Optional[str] = None,
    body: Optional[str] = None,
    labels: Optional[list[str]] = None,
    actor=None,
    change_status_to_working: bool = True,  # NEW
) -> ExternalIssueMapping:
```

**Key Implementation Details:**
- Only changes status if `change_status_to_working=True` AND status != WORKING
- Validates transition using workflow guard's VALID_TRANSITIONS
- Logs warning if transition is invalid instead of failing
- Assigns to Copilot user in the same transaction as status change
- Logs separate activity for status change (in addition to issue creation activity)

### 2. Backend View Layer Changes

#### Modified: `core/views.py`

**Function: `item_create_github_issue()`**

Added functionality:
- Tracks old status before creating GitHub issue
- Refreshes item from database after issue creation to get updated status
- Detects if status changed (old_status != item.status)
- Checks for MailActionMapping if status changed
- Returns JSON response with mail preview when trigger exists

**Response Formats:**

**With Mail Trigger (JSON):**
```json
{
    "success": true,
    "mail_preview": {
        "subject": "...",
        "message": "...",
        "from_name": "...",
        "from_address": "...",
        "cc_address": "..."
    },
    "github_tab_html": "<div>...</div>",
    "item_id": 123
}
```

**Without Mail Trigger (HTML):**
Returns the rendered `item_github_tab.html` template with HTMX headers.

### 3. Frontend Changes

#### Modified: `templates/partials/item_github_tab.html`

**Form Updates:**
- Changed `hx-swap="innerHTML"` to `hx-swap="none"` for custom processing
- Changed `hx-target="#github"` removed (handled by JavaScript)
- Added `hx-on::after-request="handleGitHubIssueCreation(event)"`

**New JavaScript Function:**
```javascript
function handleGitHubIssueCreation(event) {
    // 1. Check if response is successful
    // 2. Try to parse as JSON
    // 3. If JSON with mail_preview:
    //    - Close follow-up modal if open
    //    - Update GitHub tab HTML
    //    - Call showMailConfirmationModal()
    // 4. If HTML response:
    //    - Update GitHub tab
    //    - Show success toast
    // 5. Handle errors appropriately
}
```

**Integration:**
- Reuses existing `showMailConfirmationModal()` function from `item_form.html`
- Reuses existing `showToast()` function for notifications
- Handles both regular and follow-up issue creation flows

### 4. Test Coverage

#### Updated: `core/test_github_issue_creation.py`

Added 3 new tests:

1. **`test_admin_action_changes_status_to_working_for_backlog_item`**
   - Creates item in BACKLOG status
   - Creates GitHub issue via admin action
   - Verifies status changed to WORKING
   - Verifies assigned to Copilot user

2. **`test_admin_action_keeps_working_status_if_already_working`**
   - Creates item already in WORKING status
   - Creates GitHub issue via admin action
   - Verifies status remains WORKING (no change)
   - Verifies assigned to Copilot user

3. **`test_admin_action_changes_testing_to_working`**
   - Creates item in TESTING status
   - Creates GitHub issue via admin action
   - Verifies status changed to WORKING (valid workflow transition)
   - Verifies assigned to Copilot user

#### New File: `core/test_github_mail_integration.py`

Added 3 new integration tests:

1. **`test_github_issue_creation_triggers_mail_preview`**
   - Creates MailActionMapping for WORKING status
   - Creates item in BACKLOG status
   - POSTs to create-github-issue endpoint
   - Verifies JSON response with mail_preview
   - Verifies status changed to WORKING
   - Verifies mail preview contains correct data

2. **`test_github_issue_creation_no_mail_trigger_when_no_mapping`**
   - No MailActionMapping created
   - Creates item in BACKLOG status
   - POSTs to create-github-issue endpoint
   - Verifies HTML response (not JSON)
   - Verifies status changed to WORKING

3. **`test_github_issue_creation_no_mail_when_already_working`**
   - Creates MailActionMapping for WORKING status
   - Creates item already in WORKING status
   - POSTs to create-github-issue endpoint
   - Verifies HTML response (status didn't change, no trigger)
   - Verifies status remains WORKING

### Test Results
```
✅ All 43 GitHub & Mail tests: PASSED
✅ CodeQL Security Scan: 0 alerts
```

## Workflow Validation

### Valid Status Transitions (from ItemWorkflowGuard)
```python
VALID_TRANSITIONS = {
    ItemStatus.INBOX: [ItemStatus.BACKLOG, ItemStatus.WORKING, ItemStatus.CLOSED],
    ItemStatus.BACKLOG: [ItemStatus.WORKING, ItemStatus.CLOSED],  # ✅
    ItemStatus.WORKING: [ItemStatus.TESTING, ItemStatus.BACKLOG, ItemStatus.CLOSED],
    ItemStatus.TESTING: [ItemStatus.READY_FOR_RELEASE, ItemStatus.WORKING, ItemStatus.CLOSED],  # ✅
    ItemStatus.READY_FOR_RELEASE: [ItemStatus.CLOSED, ItemStatus.TESTING],
    ItemStatus.CLOSED: [],
}
```

**Transitions that trigger status change to WORKING:**
- BACKLOG → WORKING ✅
- TESTING → WORKING ✅ (valid workflow reversal)

**Transitions that don't trigger status change:**
- WORKING → WORKING (already in WORKING)
- INBOX → Cannot create GitHub issue (status check fails)
- READY_FOR_RELEASE → Cannot create GitHub issue (status check fails)
- CLOSED → Cannot create GitHub issue (status check fails)

## User Flow

### Scenario: Create GitHub Issue for Backlog Item with Mail Trigger

1. **User navigates to item detail page**
   - Item is in BACKLOG status
   - GitHub tab shows "Create GitHub Issue" button

2. **User clicks "Create GitHub Issue"**
   - HTMX POST request to `/items/{id}/create-github-issue/`

3. **Backend processes request**
   - Validates GitHub is enabled and configured
   - Validates item status allows issue creation
   - Calls `github_service.create_issue_for_item()`
     - Creates GitHub issue via API
     - Assigns item to Copilot user
     - Changes status from BACKLOG → WORKING
     - Logs activities

4. **Backend checks for mail trigger**
   - Detects status changed (BACKLOG → WORKING)
   - Calls `check_mail_trigger(item)`
   - Finds active MailActionMapping for (WORKING, ItemType)
   - Calls `prepare_mail_preview(item, mapping)`

5. **Backend returns JSON response**
   ```json
   {
       "success": true,
       "mail_preview": {...},
       "github_tab_html": "...",
       "item_id": 123
   }
   ```

6. **Frontend handles response**
   - Parses JSON response
   - Updates GitHub tab with new HTML
   - Calls `showMailConfirmationModal(mail_preview, item_id)`

7. **User sees mail confirmation modal**
   - Subject and message pre-filled from template
   - Sender and recipient information displayed
   - Two buttons: "Mail senden" and "Abbrechen"

8. **User decides:**
   - **Send Mail**: AJAX call to `/items/{id}/send-status-mail/`
     - Mail sent via Graph API
     - ItemComment created with mail details
     - Success toast shown
   - **Cancel**: Modal closes, no mail sent
     - "Item saved - Mail not sent" toast shown

### Scenario: Create GitHub Issue Without Mail Trigger

1. User clicks "Create GitHub Issue"
2. Backend creates issue and changes status
3. No MailActionMapping exists for (WORKING, ItemType)
4. Backend returns HTML response
5. Frontend updates GitHub tab
6. Success toast shown: "GitHub issue created successfully"

## Security Considerations

### Thread Safety
- Uses `transaction.atomic()` for database consistency
- Uses `select_for_update()` to prevent race conditions
- Multiple concurrent issue creations handled correctly

### Input Validation
- Status change validated through workflow guard
- Only allows valid status transitions
- Gracefully handles invalid transitions (logs warning, continues)

### Authorization
- Requires user authentication (enforced by view decorator)
- Uses existing GitHub integration permissions

### XSS Prevention
- Mail preview content sanitized by existing template processor
- Uses HTML escaping for all user-provided data
- Reuses existing security measures from mail handling system

### CodeQL Analysis
- 0 security alerts found
- No new vulnerabilities introduced

## Edge Cases Handled

### 1. Copilot User Doesn't Exist
- Issue still created successfully
- Warning logged instead of failure
- Status change still occurs if enabled

### 2. Status Change Fails Validation
- Issue still created successfully
- Warning logged about invalid transition
- Status remains unchanged
- No mail trigger occurs

### 3. Item Already in WORKING Status
- Issue created successfully
- Status remains WORKING (no change)
- No mail trigger occurs (status didn't change)

### 4. MailActionMapping Doesn't Exist
- Issue created successfully
- Regular HTML response returned
- No modal shown, just success toast

### 5. Follow-up Issue Creation
- Same mail handling logic applies
- Follow-up modal closes before mail modal shows
- Notes appended to item description
- Mail preview reflects current status

## Files Modified

1. `core/services/github/service.py` - Added status change functionality
2. `core/views.py` - Added mail trigger detection and JSON response
3. `templates/partials/item_github_tab.html` - Added JavaScript handler
4. `core/test_github_issue_creation.py` - Added 3 status change tests
5. `core/test_github_mail_integration.py` - Added 3 mail integration tests (NEW)

## Acceptance Criteria ✅

**Original Requirements (Issue #114):**

✅ **Status Change**: Item status changes to WORKING when GitHub issue is created  
✅ **Assignment**: Item assigned to Copilot user (already implemented)  
✅ **Mail Event Trigger**: Mail handling event triggered when status changes to WORKING  
✅ **Save First**: Changes saved before mail module opens  
✅ **User Decision**: User decides whether to send mail or not via modal  
✅ **Normal Flow**: Follows same flow as regular status changes  

**Additional Quality Criteria:**

✅ **Backward Compatibility**: Existing functionality preserved  
✅ **Test Coverage**: 6 new tests, all passing  
✅ **Security**: 0 CodeQL alerts, no new vulnerabilities  
✅ **Thread Safety**: Proper transaction handling  
✅ **Error Handling**: Graceful degradation for edge cases  

## Future Enhancements (Optional)

1. **Admin Action Mail Handling**: Currently only works in UI, could extend to admin
2. **Configurable Status**: Allow configuration of target status (not hardcoded to WORKING)
3. **Multiple Status Changes**: Handle multiple status changes in sequence
4. **Mail Template Selection**: Allow user to select from multiple templates
5. **Batch Operations**: Handle mail triggers for bulk GitHub issue creation

## Conclusion

The implementation is complete, secure, and production-ready. All requirements from Issue #114 have been met:
- Status automatically changes to WORKING
- Mail preview modal shown when MailActionMapping exists
- User can decide to send or cancel the mail
- Follows existing mail handling patterns
- Comprehensive test coverage
- No security vulnerabilities

The solution integrates seamlessly with existing mail handling infrastructure and maintains backward compatibility with previous GitHub issue creation behavior.
