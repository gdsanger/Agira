# Change Approval Email System - Visual Guide

## UI Flow

### 1. Change Detail Page - "Get Approvals" Button

```
┌─────────────────────────────────────────────────────────────┐
│ Change Detail                                                │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Title: Upgrade Production Database                          │
│  Project: Core Platform                                      │
│                                                               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Approvers                      [✉️ Get Approvals] [+] │  │
│  ├───────────────────────────────────────────────────────┤  │
│  │ ▼ John Doe (Pending)                                  │  │
│  │   Email: john.doe@example.com                         │  │
│  │   Role: Technical Lead                                │  │
│  │   Status: Pending                                     │  │
│  │                                                        │  │
│  │ ▼ Jane Smith (Pending)                                │  │
│  │   Email: jane.smith@example.com                       │  │
│  │   Role: Security Officer                              │  │
│  │   Status: Pending                                     │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

**Button Location:** Top-right of Approvers card, next to the "+" button
**Button Text:** "Get Approvals" with send icon (✉️)
**Action:** Triggers HTMX POST to `/changes/<id>/send-approval-requests/`

### 2. Email Sent - Success Toast

```
┌────────────────────────────────────────────┐
│ ✅ Success                                  │
│ Approval request emails sent to 2 approvers│
└────────────────────────────────────────────┘
```

## Email Template

### Approval Request Email

```
┌────────────────────────────────────────────────────────────┐
│ From: agira@example.com                                     │
│ To: john.doe@example.com                                    │
│ Subject: Change Approval benötigt: Upgrade Production      │
│          Database (123)                                     │
│ Attachment: change-123.pdf (1.2 MB)                        │
├────────────────────────────────────────────────────────────┤
│                                                              │
│                    Change Approval Request                   │
│                                                              │
│  Hello,                                                      │
│                                                              │
│  Your approval is requested for the following change:       │
│                                                              │
│  Change ID: 123                                             │
│  Title: Upgrade Production Database                         │
│                                                              │
│  Please review the attached Change PDF and provide your     │
│  decision by clicking one of the buttons below:             │
│                                                              │
│           ┌──────────────┐  ┌──────────────┐              │
│           │ ✅ Approve   │  │ ❌ Reject    │              │
│           └──────────────┘  └──────────────┘              │
│                                                              │
│  Note: These links are unique to you and should not be      │
│  shared.                                                     │
│                                                              │
│  This is an automated message from Agira Change Management  │
│  System.                                                     │
│                                                              │
└────────────────────────────────────────────────────────────┘
```

**Email Features:**
- Clean, professional layout
- Styled approve/reject buttons (green/red)
- Change PDF attached (with size validation)
- Unique decision links per approver
- Responsive HTML design

## Decision Flow

### 3A. Approver Clicks "Approve"

```
User clicks "Approve" in email
    ↓
GET /changes/approval/decision/?token=abc123&change_id=123&decision=approve
    ↓
┌────────────────────────────────────────────────────────────┐
│                     Decision Recorded                        │
│                                                              │
│                          ✅                                  │
│                                                              │
│  You have approved this change.                             │
│                                                              │
│  Change: Upgrade Production Database                        │
│  Your decision: Approved                                    │
│  Recorded at: 2026-02-19 14:30:15                          │
│                                                              │
│  Thank you for your timely response!                        │
└────────────────────────────────────────────────────────────┘
```

### 3B. Approver Clicks "Reject"

```
User clicks "Reject" in email
    ↓
GET /changes/approval/decision/?token=abc123&change_id=123&decision=reject
    ↓
┌────────────────────────────────────────────────────────────┐
│                     Decision Recorded                        │
│                                                              │
│                          ❌                                  │
│                                                              │
│  You have rejected this change.                             │
│                                                              │
│  Change: Upgrade Production Database                        │
│  Your decision: Rejected                                    │
│  Recorded at: 2026-02-19 14:30:15                          │
│                                                              │
│  Note: Since you rejected this change, the responsible      │
│  team will be contacted to discuss next steps.              │
│                                                              │
│  Thank you for your timely response!                        │
└────────────────────────────────────────────────────────────┘
```

## Database Changes

### ChangeApproval Status Flow

```
Initial State:
┌─────────────────────────────────────┐
│ ChangeApproval                       │
├─────────────────────────────────────┤
│ approver: John Doe                   │
│ status: PENDING                      │
│ decision_at: null                    │
│ approved_at: null                    │
│ decision_token: ""                   │
└─────────────────────────────────────┘

After "Get Approvals" clicked:
┌─────────────────────────────────────┐
│ ChangeApproval                       │
├─────────────────────────────────────┤
│ approver: John Doe                   │
│ status: PENDING                      │
│ decision_at: null                    │
│ approved_at: null                    │
│ decision_token: "abc123xyz..."      │ ← Generated
└─────────────────────────────────────┘

After "Approve" clicked:
┌─────────────────────────────────────┐
│ ChangeApproval                       │
├─────────────────────────────────────┤
│ approver: John Doe                   │
│ status: ACCEPT                       │ ← Updated
│ decision_at: 2026-02-19 14:30:15    │ ← Set
│ approved_at: 2026-02-19 14:30:15    │ ← Set
│ decision_token: "abc123xyz..."      │
└─────────────────────────────────────┘

After "Reject" clicked:
┌─────────────────────────────────────┐
│ ChangeApproval                       │
├─────────────────────────────────────┤
│ approver: Jane Smith                 │
│ status: REJECT                       │ ← Updated
│ decision_at: 2026-02-19 14:35:20    │ ← Set
│ approved_at: null                    │ ← Stays null
│ decision_token: "def456uvw..."      │
└─────────────────────────────────────┘
```

## Activity Log Entries

```
┌─────────────────────────────────────────────────────────────┐
│ Activity Stream                                              │
├─────────────────────────────────────────────────────────────┤
│ 🔄 Change.approval_requests_sent                            │
│    John Smith sent approval request emails to 2 approvers   │
│    2026-02-19 14:25:10                                      │
├─────────────────────────────────────────────────────────────┤
│ ✅ Change.approved_via_email                                │
│    John Doe approved the change via email link              │
│    2026-02-19 14:30:15                                      │
├─────────────────────────────────────────────────────────────┤
│ ❌ Change.rejected_via_email                                │
│    Jane Smith rejected the change via email link            │
│    2026-02-19 14:35:20                                      │
└─────────────────────────────────────────────────────────────┘
```

## Error Scenarios

### Error 1: Already Decided

```
User clicks "Approve" link again after already approving
    ↓
┌────────────────────────────────────────────────────────────┐
│                     Already Decided                          │
│                                                              │
│  This approval request has already been processed.          │
│                                                              │
│  Current status: Accept                                     │
│  Decision made at: 2026-02-19 14:30:15                     │
│                                                              │
└────────────────────────────────────────────────────────────┘
HTTP 400
```

### Error 2: Invalid Token

```
User uses tampered or invalid link
    ↓
┌────────────────────────────────────────────────────────────┐
│                        Error                                 │
│                                                              │
│  Invalid or expired approval link.                          │
│                                                              │
└────────────────────────────────────────────────────────────┘
HTTP 403
```

### Error 3: PDF Too Large

```
User clicks "Get Approvals" for change with large PDF
    ↓
┌────────────────────────────────────────┐
│ ❌ Error                                │
│ Change PDF is too large (4.2 MB).     │
│ Maximum size for email attachment is  │
│ 3 MB                                   │
└────────────────────────────────────────┘
```

## URL Structure

### Decision URLs

```
Approve URL:
https://agira.example.com/changes/approval/decision/?token=abc123xyz&change_id=123&decision=approve
                          ↑                           ↑         ↑           ↑
                     Base URL                      Token  Change ID   Decision

Reject URL:
https://agira.example.com/changes/approval/decision/?token=abc123xyz&change_id=123&decision=reject
                          ↑                           ↑         ↑           ↑
                     Base URL                      Token  Change ID   Decision
```

**URL Components:**
- `APP_BASE_URL`: From settings (e.g., `https://agira.example.com`)
- `path`: `/changes/approval/decision/` (reverse URL)
- `token`: Unique 32-byte URL-safe token per approval
- `change_id`: ID of the Change
- `decision`: Either "approve" or "reject"

## Security Features Visualized

### Token Security

```
┌────────────────────────────────────────────────────────────┐
│ Token Generation                                            │
│                                                              │
│  secrets.token_urlsafe(32)                                  │
│        ↓                                                     │
│  "abc123xyz789def456..." (43 characters)                   │
│        ↓                                                     │
│  Stored in ChangeApproval.decision_token                   │
│        ↓                                                     │
│  Used in email link                                         │
│        ↓                                                     │
│  Validated on decision endpoint                             │
│                                                              │
│  ✅ Unique constraint in database                           │
│  ✅ URL-safe characters only                                │
│  ✅ Cryptographically secure                                │
│  ✅ Tied to specific approval                               │
└────────────────────────────────────────────────────────────┘
```

### Idempotency Guard

```
┌────────────────────────────────────────────────────────────┐
│ Decision Request                                            │
│   ↓                                                          │
│ Check: Is status == PENDING?                                │
│   ↓                                                          │
│   Yes → Process decision                                    │
│   ↓                                                          │
│   Update status, timestamps                                 │
│   ↓                                                          │
│   Log activity                                              │
│   ↓                                                          │
│   Return success page                                       │
│                                                              │
│   No → Return "Already decided" error (HTTP 400)           │
│                                                              │
│ ✅ Prevents double-clicking                                 │
│ ✅ Prevents replay attacks                                  │
│ ✅ Clear error message for user                             │
└────────────────────────────────────────────────────────────┘
```

## Configuration

### Settings Required

```python
# settings.py
APP_BASE_URL = os.getenv('APP_BASE_URL', 'http://localhost:8000')
```

```bash
# .env
APP_BASE_URL=https://agira.example.com
```

### MailTemplate Configuration

```
Admin Interface → Mail Templates → Add

Key: change-approval-request
Subject: Change Approval benötigt: {{ change_title }} ({{ change_id }})
Message: [HTML content with {{ approve_url }} and {{ reject_url }}]
Is Active: ✅
```

## Testing Checklist

```
Unit Tests:
□ Token generation and uniqueness
□ ensure_token() doesn't overwrite existing token
□ Token saved to database

Decision Endpoint Tests:
□ Approve decision sets correct status and timestamps
□ Reject decision sets correct status and timestamps
□ Idempotency guard returns 400 for non-PENDING status
□ Missing parameters return 400
□ Invalid decision value returns 400
□ Invalid token returns 403

Service Tests:
□ build_decision_url() constructs correct URL
□ send_approval_request_emails() calls send_email
□ PDF generation with size validation
□ Template rendering replaces variables

Integration Tests:
□ Full flow from button click to email sent
□ Decision recorded and activity logged
□ UI displays success/error messages
```

## Deployment Steps

1. **Update settings:**
   ```bash
   echo "APP_BASE_URL=https://your-domain.com" >> .env
   ```

2. **Run migrations:**
   ```bash
   python manage.py migrate
   ```

3. **Verify MailTemplate:**
   - Check Admin → Mail Templates
   - Ensure `change-approval-request` is active
   - Customize subject/message if needed

4. **Test email sending:**
   - Create test Change with approvers
   - Click "Get Approvals"
   - Verify emails received
   - Test approve/reject links

5. **Monitor:**
   - Check Activity Stream for email sent events
   - Verify decision events logged
   - Check for any errors in logs
