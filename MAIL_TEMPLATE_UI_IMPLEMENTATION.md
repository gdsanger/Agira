# MailTemplate UI Implementation

## Overview
Complete UI implementation for managing email templates with AI-powered content generation.

## Features

### List View
- **URL:** `/mail-templates/`
- Search by key or subject
- Filter by active/inactive status
- Sortable table with key, subject, status, from_address, cc_address, updated_at
- Create new template button
- Edit action for each row

### Detail View
- **URL:** `/mail-templates/{id}/`
- Display all template fields
- HTML source code view (safe, no XSS)
- Edit and Delete buttons
- Metadata card with timestamps

### Create/Edit Form
- **URL:** `/mail-templates/new/` or `/mail-templates/{id}/edit/`
- TinyMCE WYSIWYG editor for HTML message
- All fields: key, subject, message, from_name, from_address, cc_address, is_active
- Save / Save & Close / Delete / Cancel buttons
- Key is readonly after creation

### AI Generation
- **Endpoint:** `/mail-templates/{id}/ai/generate/`
- Input: Context/description textarea
- AI agent: `create-mail-template.yml`
- Output: Auto-fills Subject and Message fields
- Overwrite protection with checkbox
- Error handling with user-friendly messages

## Technical Stack
- **Backend:** Django views with JSON responses
- **Frontend:** Bootstrap 5.3, HTMX 2.0, TinyMCE 6
- **AI:** OpenAI GPT-4o-mini via Agent Service
- **Security:** CSRF protection, XSS prevention, login required

## Validation
- Key: Unique, slug format (lowercase, numbers, hyphens)
- Subject: Required, max 500 characters
- Message: Required (HTML)
- Email fields: Valid email format
- Server-side validation with clear error messages

## Testing
- 16 automated tests (100% pass rate)
- Coverage: CRUD, search, filter, validation, AI endpoint
- Security scan: 0 vulnerabilities

## Files Changed
- `agents/create-mail-template.yml` - AI agent configuration
- `core/views.py` - 7 new view functions
- `core/urls.py` - 7 new URL patterns
- `templates/base.html` - Navigation link
- `templates/mail_templates.html` - List view
- `templates/mail_template_form.html` - Create/Edit form
- `templates/mail_template_detail.html` - Detail view
- `core/test_mail_template_views.py` - Test suite

## Usage Example

### Creating a Template with AI
1. Navigate to Mail Templates in sidebar
2. Click "New Template"
3. Enter key: `welcome-email`
4. In AI Generation section, enter: "Welcome email for new users who just signed up"
5. Click "Generate with AI"
6. Review and adjust generated Subject and Message
7. Fill in From Address, CC if needed
8. Click "Save & Close"

### Using the Template
The templates are stored in the database and can be retrieved by key:
```python
template = MailTemplate.objects.get(key='welcome-email')
subject = template.subject
message = template.message.replace('{{username}}', user.username)
```

## Activity Logging
All operations are logged to the Activity stream:
- `mail_template.created`
- `mail_template.updated`
- `mail_template.deleted`
- `mail_template.ai_generated`
