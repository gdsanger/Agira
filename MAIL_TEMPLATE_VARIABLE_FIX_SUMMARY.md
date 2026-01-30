# Mail Template Variable Replacement - Issue #112 Final Resolution

## Summary

**Issue #112 has been fully resolved.** All three variables are now correctly implemented and tested:

1. ✅ `{{ issue.description }}` - Replaces with full item description
2. ✅ `{{ issue.solution_description }}` - Replaces with solution description (Issue #134)
3. ✅ `{{ issue.organisation }}` - Replaces with requester's **primary** organisation name  
4. ✅ `{{ issue.solution_release }}` - Replaces with "Name - Version X.X.X - Planned: YYYY-MM-DD"

## Changes Made

### Code Changes
1. **Fixed misleading help text** in `core/models.py` (MailTemplate model)
   - **Before:** "Placeholders are allowed but not evaluated"
   - **After:** Clear instructions on how to use {{ issue.variable }} placeholders
   - This was confusing users who thought variables wouldn't work

### Implementation Verified
The actual implementation in `core/services/mail/template_processor.py` is correct and working:
- All 12 unit tests passing ✅
- Integration tests confirm all three variables work correctly ✅
- Real-world usage scenarios tested ✅

## Implementation Location

**File:** `/home/runner/work/Agira/Agira/core/services/mail/template_processor.py`

This file contains the `process_template()` function that handles all variable replacements.

## Test Results

### Unit Tests
- **File:** `core/test_template_processor.py`
- **Tests:** 12/12 passing ✅
- **Coverage:** All three variables + edge cases

### Integration Test
Created comprehensive integration test simulating real-world usage:
- Item with full data (description, requester with primary org, release with all fields)
- Mail template using all three variables
- Result: All variables correctly replaced ✅

**Output:**
```
Subject: Status Changed: Implement New Feature X
Description: We need to implement feature X to improve user experience...
Organisation: ACME Corporation  
Solution Release: Release 2.5 - Version 2.5.0 - Planned: 2026-06-30
```

## Important Notes

### Organisation Variable
The `{{ issue.organisation }}` variable uses the **requester's PRIMARY organisation**, NOT the `item.organisation` field.

This is per the requirement:
> "{{ issue.organisation }} muss durch die Primäre Organisation des Requesters ersetzt werden"

**How it works:**
1. Gets the `item.requester` (User object)
2. Looks up `user.user_organisations.filter(is_primary=True).first()`
3. Returns the organisation name
4. If no primary organisation exists, returns empty string

### Solution Release Variable  
The `{{ issue.solution_release }}` variable includes ALL three pieces of information:
- Release name
- Version (if set)
- Planned date (if set)

**Format:** `"Name - Version X.X.X - Planned: YYYY-MM-DD"`

**Examples:**
- Full: `"Release 2.5 - Version 2.5.0 - Planned: 2026-06-30"`
- Name only: `"Release 2.5"`
- Name + Version: `"Release 2.5 - Version 2.5.0"`

## Usage

### In Mail Templates
Use these variables in the subject or message fields:

```
Subject: Status Changed: {{ issue.title }}

Message:
Hello {{ issue.requester }},

Your issue has been updated:

Title: {{ issue.title }}
Description: {{ issue.description }}
Solution: {{ issue.solution_description }}
Status: {{ issue.status }}
Organisation: {{ issue.organisation }}
Planned Release: {{ issue.solution_release }}

Best regards,
{{ issue.project }} Team
```

### Important: Data Requirements
For variables to be replaced with actual values, the Item must have the corresponding data:

- `{{ issue.description }}` → Item must have `description` field set
- `{{ issue.solution_description }}` → Item must have `solution_description` field set
- `{{ issue.organisation }}` → Item's requester must have a **primary organisation** set via UserOrganisation
- `{{ issue.solution_release }}` → Item must have `solution_release` foreign key set to a Release object

If data is missing, the variable is replaced with an empty string (not an error).

## Troubleshooting

If variables appear not to be working:

1. **Check Template Syntax**
   - Recommended: `{{ issue.variable }}` (with spaces - more readable)
   - Also works: `{{issue.variable}}` (without spaces)
   - Does NOT work: `{issue.variable}` (single braces)

2. **Check Data Availability**
   - For description: `item.description` must be set
   - For solution description: `item.solution_description` must be set
   - For organisation: `item.requester` must exist AND have a primary organisation
   - For release: `item.solution_release` must be set

3. **Check Primary Organisation**
   - The requester must have exactly ONE organisation marked as `is_primary=True`
   - Check: `UserOrganisation.objects.filter(user=item.requester, is_primary=True).exists()`

4. **Check Release Fields**
   - For full output, release needs: `name`, `version`, AND `update_date`
   - Partial data will show partial output (e.g., just name if version/date are empty)

## Conclusion

**Issue #112 is RESOLVED.** The implementation is correct and all tests pass.

### What Was Fixed
The misleading help text in the MailTemplate model that said "Placeholders are allowed but not evaluated" has been corrected. The actual template processing code was already working correctly.

### If Issues Persist
If you still experience problems with variable replacement, check:
- Missing data on items (description, requester, release, etc.)
- Template syntax errors (must use {{ issue.variable }} with double braces)
- Requester not having a primary organisation set  
- Using an old deployment without the latest code
