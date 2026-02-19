# Change Approval Email System - Implementation Summary

## Overview
This implementation adds a complete email-based approval workflow for Changes in Agira. Approvers receive emails with clickable Approve/Reject buttons and a PDF of the Change. Decisions are recorded with timestamps and activity logging.

## Architecture

### Components

#### 1. Database Model Extensions
**File:** `core/models.py`

- **ChangeApproval Model**
  - Added `decision_token` field (CharField, max_length=64, unique=True)
  - Added `ensure_token()` method to generate secure tokens using `secrets.token_urlsafe(32)`
  
- **Change Model**
  - Added `get_approvals()` helper method that returns `self.approvals.all()`

**Migration:** `core/migrations/0055_add_changeapproval_decision_token.py`

#### 2. Email Service Layer
**File:** `core/services/changes/approval_mailer.py`

**Main Functions:**

- `send_change_approval_request_emails(change, request_base_url)`
  - Orchestrates the entire email sending process
  - Loads MailTemplate
  - Generates PDF
  - Iterates through approvals and sends emails
  - Returns dict with success status, counts, and errors

- `generate_change_pdf_bytes(change, request_base_url)`
  - Generates Change PDF using existing `PdfRenderService`
  - Validates 3MB size limit (GraphAPI constraint)
  - Returns PDF as bytes

- `build_decision_url(change_id, token, decision)`
  - Constructs absolute URLs for approve/reject links
  - Uses `settings.APP_BASE_URL` + reverse URL

- `render_template(template, change, approve_url, reject_url)`
  - Simple variable replacement in template
  - Supports: `{{ change_id }}`, `{{ change_title }}`, `{{ approve_url }}`, `{{ reject_url }}`

- `create_attachment_from_bytes(pdf_bytes, filename, change)`
  - Creates Attachment model instance from bytes
  - Associates with Change's project

#### 3. Decision Endpoint (Public)
**File:** `core/views.py`
**Function:** `change_approval_decision(request)`
**Route:** `/changes/approval/decision/` (GET)

**Features:**
- No authentication required (uses token for security)
- Validates query parameters: `token`, `change_id`, `decision`
- Looks up ChangeApproval by token + change_id
- Idempotency guard: Returns 400 if status != PENDING
- On approve: Sets status=ACCEPT, decision_at=now, approved_at=now
- On reject: Sets status=REJECT, decision_at=now (approved_at stays None)
- Returns styled HTML confirmation page
- Logs activity with ActivityService

**Error Responses:**
- 400: Missing/invalid parameters, already decided
- 403: Invalid token or approval not found

#### 4. Trigger Endpoint (Authenticated)
**File:** `core/views.py`
**Function:** `change_send_approval_requests(request, id)`
**Route:** `/changes/<int:id>/send-approval-requests/` (POST)

**Features:**
- Requires authentication (`@login_required`)
- Calls approval mailer service
- Returns JSON with success/error status
- Logs activity on success

#### 5. UI Integration
**File:** `templates/change_detail.html`

**Button Added:**
- Location: Change detail page, Approvers card header
- Label: "Get Approvals" with send icon
- Uses HTMX for async POST
- Shows spinner during request
- Toast notifications for success/error

#### 6. Email Template
**Migration:** `core/migrations/0056_add_change_approval_mail_template.py`

**MailTemplate:**
- Key: `change-approval-request`
- Subject: `Change Approval benötigt: {{ change_title }} ({{ change_id }})`
- Message: HTML with styled approve/reject buttons
- Active by default

#### 7. Configuration
**File:** `agira/settings.py` and `.env.example`

- Added `APP_BASE_URL` setting (default: `http://localhost:8000`)
- Used for generating absolute URLs in emails

## Security Features

1. **Unique Decision Tokens**
   - 32-byte URL-safe tokens using `secrets.token_urlsafe()`
   - Unique constraint in database
   - One token per approval

2. **Idempotency**
   - Decision endpoint checks status before updating
   - Prevents double-clicking or replay attacks

3. **Token Scoping**
   - Token tied to specific change_id and approver
   - Cannot be used for different approvals

4. **Activity Logging**
   - All decisions logged with timestamp and actor
   - Audit trail for compliance

5. **Attachment Size Validation**
   - 3MB limit enforced (GraphAPI constraint)
   - Clear error message if exceeded

## Data Flow

### 1. Sending Approval Requests

```
User clicks "Get Approvals" 
  → change_send_approval_requests view
  → send_change_approval_request_emails service
    → Load MailTemplate
    → Generate PDF (with size check)
    → For each approval:
      → Ensure token (generate if needed)
      → Build approve/reject URLs
      → Render email template
      → send_email via GraphAPI
    → Return results
  → Show success/error toast
```

### 2. Approver Decision

```
Approver clicks link in email
  → change_approval_decision view (GET)
  → Validate parameters
  → Lookup approval by token + change_id
  → Check if already decided (guard)
  → Update status + timestamps
  → Log activity
  → Return HTML confirmation
```

## Status Values

**ApprovalStatus enum:**
- `PENDING` = 'Pending'
- `ACCEPT` = 'Accept' (used for approve)
- `REJECT` = 'Reject' (used for reject)
- `ABSTAINED` = 'Abstained'
- `INFO` = 'Info'

## Error Handling

### Service Layer
- MailTemplate not found → ServiceError with clear message
- PDF generation fails → ServiceError with exception details
- PDF too large (>3MB) → ServiceError with size details
- Email send fails → Logged as error, counted in failed_count

### Decision Endpoint
- Missing parameters → HTTP 400 with error message
- Invalid decision value → HTTP 400
- Invalid/expired token → HTTP 403
- Already decided → HTTP 400 with "Already decided" message

### UI Layer
- Service errors → JSON response with error field
- Display via toast notification
- Failed count shown in error message

## Testing Strategy

**Areas to Test:**
1. Token generation and uniqueness
2. Decision endpoint (approve/reject/idempotency/validation)
3. Approval mailer service (with mocks)
4. UI trigger endpoint (with mocks)
5. Integration test: Full flow end-to-end

**Test Infrastructure:**
- Django TestCase
- Mock `send_email` and `generate_change_pdf_bytes`
- RequestFactory for view tests
- Fixtures for test data

## Dependencies

### Existing Services Used:
- `core.services.graph.mail_service.send_email` - Email sending via GraphAPI
- `core.printing.service.PdfRenderService` - PDF generation
- `core.services.activity.ActivityService` - Activity logging

### Models:
- `Change`, `ChangeApproval`, `ApprovalStatus`
- `MailTemplate`
- `Attachment`, `Project`, `User`

## Configuration Requirements

### Environment Variables
- `APP_BASE_URL` - Base URL for email links (e.g., `https://agira.example.com`)

### MailTemplate Setup
- Migration automatically creates template
- Can be customized in Django admin
- Template must be active (`is_active=True`)

### GraphAPI Setup
- Microsoft Graph API must be configured
- Default mail sender configured in settings
- 3MB attachment size limit

## Future Enhancements

1. **Email Template Improvements**
   - Support for Markdown in template
   - More sophisticated variable replacement
   - Multi-language support

2. **Reminder Emails**
   - Send reminders for pending approvals
   - Configurable reminder schedule

3. **Bulk Operations**
   - Approve/reject multiple changes at once
   - Batch email sending

4. **Analytics**
   - Approval response time metrics
   - Approval rate statistics
   - Dashboard for approval status

5. **Mobile Optimization**
   - Responsive email template
   - Mobile-friendly decision page

## Known Limitations

1. **PDF Size Limit**
   - 3MB maximum due to GraphAPI v1 attachment limit
   - Changes with large attachments may fail
   - Solution: Use GraphAPI upload sessions (future enhancement)

2. **Token Expiration**
   - Tokens currently don't expire
   - Old tokens remain valid indefinitely
   - Solution: Add expiration timestamp (future enhancement)

3. **Template Rendering**
   - Simple string replacement only
   - No support for loops or conditions
   - Solution: Use Django template engine (future enhancement)

## Acceptance Criteria ✅

All acceptance criteria from the original specification have been met:

- ✅ `Change.get_approvals()` exists and returns `self.approvals.all()`
- ✅ `ChangeApproval.decision_token` exists with `unique=True`, migration created
- ✅ Token ensured and saved during email sending
- ✅ MailTemplate `change-approval-request` loaded with `is_active=True`
- ✅ Email sent via `core.services.graph.send_email` to `ChangeApproval.approver.email`
- ✅ Email contains approve/reject links with querystring params
- ✅ Email contains `change-<id>.pdf` attachment (under 3MB, with error handling)
- ✅ Endpoint `/changes/approval/decision/` implemented:
  - ✅ Approve: Sets status=ACCEPT, decision_at=now, approved_at=now
  - ✅ Reject: Sets status=REJECT, decision_at=now
  - ✅ Idempotency guard: HTTP 400 when status != PENDING
  - ✅ Invalid parameters → HTTP 400
  - ✅ Invalid token → HTTP 403
  - ✅ Success response with confirmation + thank you message
- ✅ UI: "Get Approvals" button exists and triggers email sending (POST)

## Code Quality

- ✅ Code review completed, issues fixed
- ✅ CodeQL security scan passed (0 alerts)
- ✅ Follows project conventions
- ✅ Activity logging integrated
- ✅ Error handling comprehensive

## Security Summary

**No security vulnerabilities detected** by CodeQL analysis.

**Security measures implemented:**
1. Unique, secure tokens (32 bytes, URL-safe)
2. Token scoping to specific approvals
3. Idempotency guard against replay attacks
4. Input validation on decision endpoint
5. Activity logging for audit trail
6. Attachment size validation
7. No authentication bypass (public endpoint secured by token)

**Recommendations for production:**
1. Add token expiration (e.g., 7 days)
2. Rate limiting on decision endpoint
3. Monitor for suspicious token usage patterns
4. Consider adding CAPTCHA for repeated failed attempts
