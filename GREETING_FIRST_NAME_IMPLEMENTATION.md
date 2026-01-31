# Status-Change Email Greeting: First Name Implementation

## Overview

This implementation adds support for personalized greetings using only the first name in status-change emails (triggered via Action Mapping).

## Issue Reference

- **GitHub Issue:** gdsanger/Agira#247
- **Local Task:** /items/191/

## Implementation

### New Template Variable

A new template variable has been added to the mail template processor:

```
{{ issue.requester_first_name }}
```

This variable extracts the first name from the requester's full name using the following logic:
1. Trim leading and trailing whitespace from the full name
2. Split on any whitespace character(s) using Python's `split(maxsplit=1)` method
3. Take the first part (substring before the first whitespace)

### Examples

| Full Name (`{{ issue.requester }}`) | First Name (`{{ issue.requester_first_name }}`) |
|--------------------------------------|--------------------------------------------------|
| `Max Mustermann`                     | `Max`                                            |
| `Madonna`                            | `Madonna`                                        |
| `  Anna   Maria  Muster `           | `Anna`                                           |
| `John\t\nDoe` (with tabs/newlines)  | `John`                                           |
| (empty or no requester)              | (empty string)                                   |

### Security

- The first name is **HTML-escaped** like all other template variables to prevent XSS attacks
- Input with malicious HTML tags will be properly escaped

### Backward Compatibility

- The existing `{{ issue.requester }}` variable continues to work and returns the full name
- Templates that don't use the new variable are unaffected
- Both variables can be used in the same template if needed

## Usage

### How to Use the New Variable

1. **Navigate to Mail Templates** in the Agira admin interface
2. **Create or Edit** a mail template for status-change notifications
3. **Use the new variable** in your greeting:

```html
<p>Hallo {{ issue.requester_first_name }},</p>
```

Instead of:

```html
<p>Hallo {{ issue.requester }},</p>
```

### Example Template Update

**Before:**
```html
<p>Hallo {{ issue.requester }},</p>

<p>das Item <strong>"{{ issue.title }}"</strong> hat den Status gewechselt.</p>

<p>Neuer Status: {{ issue.status }}</p>
```

**After:**
```html
<p>Hallo {{ issue.requester_first_name }},</p>

<p>das Item <strong>"{{ issue.title }}"</strong> hat den Status gewechselt.</p>

<p>Neuer Status: {{ issue.status }}</p>
```

### Handling Edge Cases

**Empty or Missing Requester:**
If there's no requester or the name is empty, the variable returns an empty string. You may want to use a fallback:

```html
<p>Hallo{% if issue.requester_first_name %} {{ issue.requester_first_name }}{% endif %},</p>
```

Or simply:
```html
<p>Hallo,</p>
```

**Note:** Django templates don't support `{% if %}` statements in the current implementation. The templates use simple variable replacement. If you need conditional logic, the template content should include both options in the message field.

## Available Template Variables

All template variables for status-change emails:

- `{{ issue.title }}` - Item title
- `{{ issue.description }}` - Item description
- `{{ issue.solution_description }}` - Solution description (Markdown → HTML)
- `{{ issue.status }}` - Item status (with emoji)
- `{{ issue.type }}` - Item type name
- `{{ issue.project }}` - Project name
- `{{ issue.requester }}` - Requester **full name**
- `{{ issue.requester_first_name }}` - Requester **first name only** ⭐ NEW
- `{{ issue.assigned_to }}` - Assigned user name
- `{{ issue.organisation }}` - Requester's primary organisation
- `{{ issue.solution_release }}` - Release info (name, version, date)
- `{{ solution_description }}` - Alias for `{{ issue.solution_description }}` (backward compatibility)

## Testing

### Automated Tests

9 new test cases have been added in `core/test_template_processor.py`:

1. `test_requester_first_name_extraction_normal_name` - "Max Mustermann" → "Max"
2. `test_requester_first_name_single_name` - "Madonna" → "Madonna"
3. `test_requester_first_name_multiple_whitespace` - "  Anna   Maria  Muster " → "Anna"
4. `test_requester_first_name_empty_string` - Empty name → Empty string
5. `test_requester_first_name_no_requester` - No requester → Empty string
6. `test_requester_first_name_with_tabs_and_newlines` - Handles \t and \n
7. `test_requester_first_name_html_escaping` - XSS protection
8. `test_requester_full_name_still_works` - Backward compatibility
9. `test_requester_first_name_only_whitespace` - Whitespace only → Empty string

All tests pass (38/38).

### Manual Testing

To test the implementation:

1. Create a test item with a requester named "Max Mustermann"
2. Create a mail template with `{{ issue.requester_first_name }}` in the greeting
3. Create a MailActionMapping linking the template to a status+type combination
4. Change the item's status to trigger the email
5. Verify the email greeting shows "Hallo Max," instead of "Hallo Max Mustermann,"

## Migration Guide

### For Existing Templates

If you have existing status-change mail templates:

1. **Identify** which templates are used for status-change emails (check MailActionMapping)
2. **Edit** those templates in the admin interface
3. **Replace** `{{ issue.requester }}` with `{{ issue.requester_first_name }}` in greetings
4. **Save** and test

### For New Templates

Simply use `{{ issue.requester_first_name }}` when creating new status-change mail templates.

## Technical Details

### Code Changes

**File:** `core/services/mail/template_processor.py`
- Added first name extraction logic (lines 81-89)
- Added `{{ issue.requester_first_name }}` to message replacements (line 109)
- Added `{{ issue.requester_first_name }}` to subject replacements (line 126)
- Updated docstring to document the new variable (line 41)

**File:** `core/models.py`
- Updated MailTemplate field help text to mention the new variable (lines 947-951)

**File:** `core/test_template_processor.py`
- Added 9 comprehensive test cases for the new functionality

### Implementation Notes

- Uses Python's `str.split(maxsplit=1)[0]` for efficient first-word extraction
- Handles all Unicode whitespace characters (spaces, tabs, newlines, etc.)
- No global side effects - only affects template rendering
- No database migrations needed (variable is processed at runtime)
- No changes to the MailTemplate or MailActionMapping models

## Acceptance Criteria

✅ User-Name `"Max Mustermann"` → Anrede: `"Hallo Max"`
✅ User-Name `"Madonna"` → Anrede: `"Hallo Madonna"`
✅ User-Name `"  Anna   Maria  Muster "` → Anrede: `"Hallo Anna"`
✅ Keine Auswirkung auf andere Mailtypen (nur Status-Change-Mails aus Action Mapping)
✅ Automatisierte Tests vorhanden und decken die Fälle ab

## Next Steps

Users can now:
1. Update their existing status-change mail templates to use `{{ issue.requester_first_name }}`
2. Create new templates with personalized greetings using only the first name
3. Continue using `{{ issue.requester }}` for full name where appropriate

The implementation is **complete and ready for production use**.
