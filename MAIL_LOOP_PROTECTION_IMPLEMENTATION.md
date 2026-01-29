# Mail Loop Protection Implementation

## Overview

This document describes the mail loop protection mechanism implemented in Agira to prevent the system from sending emails to its own default email address.

## Problem Statement

Agira uses Microsoft Graph API for both sending and receiving emails through a configured default email address (`GraphAPIConfiguration.default_mail_sender`). Without protection, the following mail loop scenario could occur:

1. Agira sends an email to the default address
2. Graph API email ingestion service reads this email from the mailbox
3. Potentially triggers additional emails or AI processing
4. Results in unnecessary costs and system spam

## Solution

A centralized protection mechanism was implemented in the `core/services/graph/mail_service.py` module that blocks all outbound emails containing the system's default address in any recipient field (to, cc, or bcc).

## Implementation Details

### Location
- **Primary Module**: `core/services/graph/mail_service.py`
- **Test Module**: `core/services/graph/test_mail_service.py`

### Key Components

#### 1. Email Normalization Function
```python
def _normalize_email(email: str) -> str:
    """Normalize an email address for comparison (trim + lowercase)."""
    return email.strip().lower()
```

#### 2. Blocking Check Function
```python
def _is_blocked_system_recipient(email_addresses: List[str]) -> bool:
    """
    Check if any email address matches the system's default address.
    Returns True if blocked, False otherwise.
    """
```

This function:
- Retrieves the default address from `GraphAPIConfiguration`
- Returns `False` if no default is configured (fail-safe)
- Normalizes all addresses for case-insensitive comparison
- Returns `True` if any address matches the system default

#### 3. Integration in send_email()

The blocking logic is integrated early in the `send_email()` function:

```python
def send_email(...):
    # ... validation checks ...
    
    # Mail loop protection
    all_recipients = list(to)
    if cc:
        all_recipients.extend(cc)
    if bcc:
        all_recipients.extend(bcc)
    
    if _is_blocked_system_recipient(all_recipients):
        # Log detailed warning
        logger.warning(
            f"Blocked mail to system default address (Agira self-mail protection). "
            f"Subject: '{subject}', Default address: '{config.default_mail_sender}', "
            f"Blocked recipients: [...], All recipients (to/cc/bcc): [...]"
        )
        
        # Return failure result
        return GraphSendResult(
            sender=...,
            to=to,
            subject=subject,
            success=False,
            error="Email blocked: recipient list contains system default address (mail loop protection)",
        )
    
    # ... continue with normal sending ...
```

### Behavior Characteristics

1. **Fail-Safe**: If no default address is configured, no blocking occurs
2. **Early Exit**: Blocking happens before any external API calls
3. **Non-Throwing**: Returns a failure result instead of raising an exception
4. **Comprehensive**: Checks all recipient fields (to, cc, bcc)
5. **Case-Insensitive**: Handles different case variations
6. **Whitespace-Tolerant**: Trims whitespace before comparison

### Logging

Blocked emails are logged at WARNING level with the following information:
- "Agira self-mail protection" identifier
- Email subject
- System default address
- List of blocked addresses (those matching the default)
- All recipients (to/cc/bcc combined)

Example log entry:
```
WARNING - Blocked mail to system default address (Agira self-mail protection). 
Subject: 'Status Update', Default address: 'system@example.com', 
Blocked recipients: ['system@example.com'], 
All recipients (to/cc/bcc): ['user@example.com', 'system@example.com']
```

## Testing

### Test Coverage

15 comprehensive unit tests were added in `MailLoopProtectionTestCase`:

1. **Helper Function Tests**:
   - `test_normalize_email_lowercase` - Lowercase conversion
   - `test_normalize_email_strips_whitespace` - Whitespace handling
   - `test_is_blocked_system_recipient_no_config` - No config edge case
   - `test_is_blocked_system_recipient_empty_list` - Empty list handling
   - `test_is_blocked_system_recipient_matches` - Positive matching
   - `test_is_blocked_system_recipient_no_match` - Negative matching

2. **Integration Tests**:
   - `test_blocks_email_to_default_address_in_to_field` - Block in TO field
   - `test_blocks_email_to_default_address_in_cc_field` - Block in CC field
   - `test_blocks_email_to_default_address_in_bcc_field` - Block in BCC field
   - `test_blocks_email_case_insensitive` - Case variation handling
   - `test_blocks_email_with_whitespace` - Whitespace in addresses
   - `test_allows_email_to_different_address` - Normal emails work
   - `test_allows_email_when_no_default_configured` - No config edge case
   - `test_blocked_email_logs_details` - Logging verification
   - `test_multiple_recipients_with_mixed_addresses` - Multiple recipients

### Running Tests

```bash
# Run mail loop protection tests only
python manage.py test core.services.graph.test_mail_service.MailLoopProtectionTestCase --settings=agira.test_settings

# Run all mail service tests
python manage.py test core.services.graph.test_mail_service --settings=agira.test_settings
```

### Test Results

All tests passing:
- ✅ 15 new mail loop protection tests
- ✅ 10 existing SendEmailTestCase tests  
- ✅ 11 mail event integration tests
- ✅ CodeQL security scan: 0 alerts

## Configuration

No additional configuration is required. The protection uses the existing `GraphAPIConfiguration.default_mail_sender` field.

## Scope and Limitations

### Scope
The protection applies to ALL email sending paths that use the `send_email()` function in `core/services/graph/mail_service.py`, including:
- Event-based status emails
- Manual emails from the UI
- Automated emails from workflows
- GitHub issue creation emails

### Limitations
1. **Exact Match Only**: The protection only blocks exact matches to the configured default address. It does not handle:
   - Email aliases or alternative addresses for the same mailbox
   - Plus-addressing (e.g., user+tag@domain.com)
   - Domain-level wildcards

2. **Single Default Only**: Only the `default_mail_sender` is protected. If emails are sent from other addresses, those are not protected.

3. **No Retroactive Effect**: The protection only affects new email send attempts. It does not clean up or prevent processing of emails already in the mailbox.

## Migration and Deployment

### Deployment Steps
1. Deploy the updated `mail_service.py` file
2. No database migrations required
3. No configuration changes required
4. Clear Django cache (if necessary): `cache.clear()`

### Rollback
If needed, the changes can be rolled back by reverting the two modified files:
- `core/services/graph/mail_service.py`
- `core/services/graph/test_mail_service.py`

No database rollback is required.

## Monitoring

To monitor the effectiveness of the protection:

1. **Search Application Logs** for:
   - Search term: "Agira self-mail protection"
   - Log level: WARNING
   
2. **Metrics to Track**:
   - Number of blocked emails per day/week
   - Subjects of blocked emails (to identify patterns)
   - Source of blocked emails (which workflows trigger them)

3. **Action Items**:
   - If many emails are being blocked, investigate why workflows are attempting to send to the system address
   - Consider fixing the root cause (incorrect recipient configuration) rather than relying solely on the protection

## Future Enhancements

Potential future improvements:
1. Support for blocking multiple system addresses
2. Support for email aliases and plus-addressing
3. Configurable block list beyond just the default address
4. Admin UI for viewing blocked email statistics
5. Email notification to administrators when blocking occurs
6. Rate limiting on blocked attempts (to detect misconfigured workflows)

## References

- **Issue**: #120 - Erweiterung Mailing System in/out in Agira
- **Related**: #207 - Mailversand bei Item EventChange geht nicht
- **Related**: #188 - MailTemplate Model für E-Mail-Templates einführen
- **Implementation PR**: [Link to PR will be added]

## Contact

For questions or issues related to this implementation, contact the Agira development team.
