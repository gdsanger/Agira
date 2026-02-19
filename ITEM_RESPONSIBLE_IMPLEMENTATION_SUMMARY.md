# Item Responsible Field Implementation Summary

## Overview
Successfully implemented the "Responsible" field feature for Items in the Agira application as specified in issue #451. This feature allows Items to have an optional responsible person (Agent role only) with "Take over" and "Assign" actions, including email notifications.

## Implementation Details

### 1. Database Model Changes

**File:** `core/models.py`
- Added `responsible` field to Item model:
  ```python
  responsible = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='responsible_items')
  ```
- Added validation in `Item.clean()` method to ensure only users with `role='Agent'` can be set as responsible
- Follows the same pattern as existing `assigned_to` field

**Migrations:**
- `core/migrations/0053_add_item_responsible.py` - Adds the database field
- `core/migrations/0054_add_responsible_mail_template.py` - Creates email template

### 2. Backend Views

**File:** `core/views.py`

**Updated Views:**
- `item_detail()`: Added `responsible` to select_related, added `agents` to context
- `item_edit()`: Added `agents` filtered list to context
- `item_create()`: Added `agents` to context, handles responsible in POST
- `item_update()`: Handles responsible field with validation

**New Action Endpoints:**
- `item_take_over_responsible()`: Sets responsible to current agent user
  - Only available to users with Agent role (403 for non-agents)
  - Idempotent: returns success with no_change flag if already responsible
  - Logs activity and sends email on change
  
- `item_assign_responsible()`: Sets responsible to selected agent
  - Validates selected user has Agent role
  - Idempotent: returns success with no_change flag if already set
  - Logs activity and sends email on change

**Helper Function:**
- `_send_responsible_notification()`: Sends email using 'resp' template
  - Uses GlobalSettings.base_url for absolute links
  - Renders template with item details
  - Integrates with Microsoft Graph mail service

**File:** `core/urls.py`
- Added URL patterns for both new actions

### 3. UI Templates

**File:** `templates/item_detail.html`
- Added "Responsible" display field above "Assigned To" (line ~613)
- Added "Take over" button (visible only to Agents)
- Added "Assign" button (visible to all)
- Added "Assign Responsible" modal with agent selection dropdown
- Implemented JavaScript handlers for both actions with proper error handling

**File:** `templates/item_form.html`
- Added "Responsible" dropdown field above "Assigned To" (line ~332)
- Dropdown populated only with agents from `agents` context variable
- Supports selection and clearing (None option)

### 4. Email Notification

**Template Details:**
- Key: `resp`
- Subject: `Item zugewiesen: {{ issue.title }}`
- Format: Outlook-compatible HTML with inline styles
- Content includes:
  - Title, Type, Project
  - Responsible, Assigned To, Requester
  - Status
  - Absolute link to item detail view

**Sending Logic:**
- Only sends when responsible actually changes
- Uses `send_email()` from `core.services.graph.mail_service`
- Recipient: new responsible user's email
- Body rendered as HTML

### 5. Testing

**File:** `core/test_item_responsible.py`

Test coverage includes:
- Default value is None
- Setting agent as responsible works
- Validation prevents non-agents from being responsible
- Null values are allowed
- "Take over" action (agent-only access, idempotent behavior)
- "Assign" action (role validation, idempotent behavior)

**Test Results:**
- 10 tests created
- All tests properly structured
- Cannot run without database, but syntax verified

### 6. Security

**CodeQL Scan:** ✅ 0 alerts
**Code Review:** ✅ No issues found

**Security Measures:**
- Role-based access control enforced
- Input validation on all endpoints
- CSRF protection on all POST requests
- Proper parameterized queries (no SQL injection)
- XSS protection via Django templates

## Business Rules Implemented

✅ `Item.responsible` is nullable ForeignKey to User
✅ Only users with `role='Agent'` can be set as responsible
✅ "Take over" sets responsible to current agent
✅ "Assign" sets responsible to selected agent
✅ Email sent only when responsible actually changes
✅ Idempotent behavior for both actions

## Files Modified

1. `core/models.py` - Added field and validation
2. `core/views.py` - Added views and helper function
3. `core/urls.py` - Added URL patterns
4. `templates/item_detail.html` - Added UI and actions
5. `templates/item_form.html` - Added dropdown field

## Files Created

1. `core/migrations/0053_add_item_responsible.py` - Database migration
2. `core/migrations/0054_add_responsible_mail_template.py` - Email template
3. `core/test_item_responsible.py` - Test suite

## Acceptance Criteria Status

### Datenmodell/API ✅
- ✅ `Item.responsible` exists in DB (Migration)
- ✅ Item-Detail liefert `responsible`
- ✅ Item kann mit `responsible` gespeichert/aktualisiert werden
- ✅ Speichern ist auf `User.role == 'agent'` begrenzt; `null` erlaubt

### UI ✅
- ✅ Feld „Responsible" sichtbar und direkt über „Assigned To"
- ✅ Dropdown listet ausschließlich Agenten
- ✅ Responsible kann leer sein (keine Validierungsfehler bei NULL)

### Take over ✅
- ✅ Für Nicht-Agenten deaktiviert (403 Forbidden)
- ✅ Für Agenten setzt „Take over" den Responsible und speichert
- ✅ Mail wird nur versendet, wenn sich Responsible ändert

### Assign ✅
- ✅ „Assign" öffnet Modal zur Auswahl eines Agent-Users
- ✅ Auswahl enthält ausschließlich Agenten
- ✅ Nach Bestätigung wird Responsible gesetzt und gespeichert
- ✅ Mail wird nur versendet, wenn sich Responsible ändert

### Mail ✅
- ✅ Template per Migration angelegt (key='resp')
- ✅ Outlook-kompatibles HTML
- ✅ Enthält alle Pflichtfelder
- ✅ Link ist absolut (GlobalSettings.base_url)
- ✅ Versand nur bei tatsächlicher Änderung

## Next Steps

1. Deploy to test environment
2. Verify migrations run successfully
3. Test email delivery in production environment
4. Validate UI rendering across browsers
5. Monitor for any edge cases

## Notes

- The feature follows existing patterns in the codebase (similar to `assigned_to` field)
- All changes are minimal and surgical as requested
- Email template uses Jinja2-style placeholders ({{ }})
- Bootstrap modal and forms used for consistency
- JavaScript uses fetch API with proper error handling
- Activity logging included for audit trail
