# Microsoft Graph API Mail Service

## Overview

The Graph API Mail Service provides email sending capabilities for Agira through Microsoft Graph API. This is a **version 1 (Send Only)** implementation that focuses on reliable outbound email delivery with attachment support and comprehensive logging.

**Current capabilities:**
- Send emails via Microsoft Graph API
- Support for HTML and plain text bodies
- Support for CC and BCC recipients
- Attachment support (up to 3 MB per attachment)
- Automatic logging as ItemComment (EmailOut)
- Token caching and automatic refresh

**Not included in v1:**
- Inbound email fetching
- Email threading/conversation tracking
- Large attachment support (>3 MB requires upload sessions)
- Auto-triage or email processing

## Prerequisites

### Azure App Registration

You need to create an Azure AD Application with the following setup:

1. **Register Application**:
   - Go to [Azure Portal](https://portal.azure.com) → Azure Active Directory → App Registrations
   - Click "New registration"
   - Name: e.g., "Agira Mail Service"
   - Supported account types: "Single tenant" (recommended)
   - No redirect URI needed for app-only flow

2. **Configure API Permissions**:
   - Go to "API permissions"
   - Add permission → Microsoft Graph → Application permissions
   - Add: `Mail.Send`
   - **Important**: Click "Grant admin consent" for your tenant

3. **Create Client Secret**:
   - Go to "Certificates & secrets"
   - Click "New client secret"
   - Description: e.g., "Agira production"
   - Expires: Choose appropriate expiration (12/24 months)
   - **Copy the value immediately** - you won't be able to see it again

4. **Note Configuration Values**:
   - Application (client) ID
   - Directory (tenant) ID
   - Client secret value

### Sender Mailbox

The sender email address (UPN) must:
- Be a valid mailbox in your Microsoft 365 / Azure AD tenant
- Be accessible by the application (Mail.Send permission allows sending as any user)
- Typically a shared mailbox like `support@company.com` or `noreply@company.com`

## Configuration in Agira

### Database Configuration

1. Navigate to **Django Admin** → **Graph API Configuration**

2. Set the following fields:
   - **Enabled**: ✓ (check to enable the service)
   - **Tenant ID**: Your Azure AD tenant ID
   - **Client ID**: Your application (client) ID
   - **Client Secret**: Your client secret value (encrypted automatically)
   - **Default Mail Sender**: Default sender email address (UPN), e.g., `support@yourcompany.com`

3. Click **Save**

### Field Descriptions

| Field | Description | Example |
|-------|-------------|---------|
| `tenant_id` | Azure AD tenant ID (GUID) | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| `client_id` | Application (client) ID (GUID) | `12345678-90ab-cdef-1234-567890abcdef` |
| `client_secret` | Client secret value (encrypted in DB) | `abc123~DEF.456GHI_789jkl` |
| `default_mail_sender` | Default sender email (UPN) | `support@yourcompany.com` |
| `enabled` | Whether the service is active | `True` |

**Security Note**: The `client_secret` field is encrypted using `django-encrypted-model-fields`. In the admin interface, it shows as `••••••••` when editing an existing configuration.

## Usage

### Basic Email Sending

```python
from core.services.graph import send_email

# Send a simple HTML email
result = send_email(
    subject="Welcome to Agira",
    body="<p>Hello! Welcome to our system.</p>",
    to=["user@example.com"],
)

if result.success:
    print(f"Email sent to {result.to}")
else:
    print(f"Failed to send email: {result.error}")
```

### Send with CC and BCC

```python
result = send_email(
    subject="Project Update",
    body="<h1>Update</h1><p>Here's the latest update...</p>",
    to=["client@example.com"],
    cc=["team@mycompany.com"],
    bcc=["archive@mycompany.com"],
    sender="projects@mycompany.com",  # Override default sender
)
```

### Send Plain Text Email

```python
result = send_email(
    subject="System Notification",
    body="This is a plain text email.\n\nBest regards,\nAgira System",
    body_is_html=False,  # Set to False for plain text
    to=["admin@example.com"],
)
```

### Send with Attachments

```python
from core.models import Attachment

# Assuming you have Attachment objects
attachments = Attachment.objects.filter(project=my_project, id__in=[1, 2, 3])

result = send_email(
    subject="Report with Attachments",
    body="<p>Please find the attached reports.</p>",
    to=["recipient@example.com"],
    attachments=list(attachments),
)
```

**Attachment Limits (v1)**:
- Maximum size per attachment: **3 MB**
- Larger attachments will raise `ServiceError`
- For larger files, consider providing download links instead

### Send and Log to Item

```python
from core.models import Item, User

# Get item and user
item = Item.objects.get(id=123)
user = User.objects.get(username="agent")

# Send email and automatically log as ItemComment
result = send_email(
    subject="Issue Update",
    body="<p>We've updated your issue status.</p>",
    to=["client@example.com"],
    item=item,           # Links to this Item
    author=user,         # Sets comment author
    visibility="Public", # or "Internal"
)

# ItemComment is created automatically with:
# - kind = EmailOut
# - delivery_status = Sent (or Failed)
# - sent_at = current timestamp
# - subject, body, external_from, external_to populated
```

### Function Signature

```python
def send_email(
    subject: str,
    body: str,
    to: List[str],
    body_is_html: bool = True,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    sender: Optional[str] = None,
    attachments: Optional[List[Attachment]] = None,
    item: Optional[Item] = None,
    author: Optional[User] = None,
    visibility: str = "Internal",
    client_ip: Optional[str] = None,
) -> GraphSendResult
```

**Parameters**:
- `subject` (required): Email subject line, must not be empty
- `body` (required): Email body content (HTML or plain text)
- `to` (required): List of recipient email addresses (at least one)
- `body_is_html`: If `True`, body is treated as HTML; if `False`, plain text
- `cc`: Optional list of CC recipients
- `bcc`: Optional list of BCC recipients
- `sender`: Optional sender UPN (uses `default_mail_sender` if not specified)
- `attachments`: Optional list of `Attachment` model instances
- `item`: Optional `Item` instance to log email as `ItemComment`
- `author`: Optional `User` instance for comment author
- `visibility`: Comment visibility (`"Public"` or `"Internal"`)
- `client_ip`: Optional client IP for future audit logging

**Returns**: `GraphSendResult`
- `sender`: Sender email address
- `to`: List of recipient addresses
- `subject`: Email subject
- `success`: `True` if sent successfully, `False` otherwise
- `error`: Error message if `success=False`, otherwise `None`

## ItemComment Integration

When you pass an `item` parameter, the service automatically creates an `ItemComment`:

1. **Before sending**: Comment created with `delivery_status=Queued`
2. **On success**: Status updated to `Sent`, `sent_at` timestamp set
3. **On failure**: Status updated to `Failed`

**Comment fields populated**:
- `kind`: `EmailOut`
- `subject`: Email subject
- `body` / `body_html`: Email body (depending on `body_is_html`)
- `external_from`: Sender email
- `external_to`: Comma-separated recipient list
- `delivery_status`: `Queued` → `Sent` or `Failed`
- `sent_at`: Timestamp when sent (if successful)
- `author`: User who sent the email
- `visibility`: Public or Internal

**Attachments**: If attachments are provided, `AttachmentLink` objects are created automatically with `role=CommentAttachment`.

### Query Sent Emails

```python
from core.models import ItemComment, CommentKind, EmailDeliveryStatus

# Get all sent emails for an item
sent_emails = ItemComment.objects.filter(
    item=my_item,
    kind=CommentKind.EMAIL_OUT,
    delivery_status=EmailDeliveryStatus.SENT
)

# Get failed emails
failed_emails = ItemComment.objects.filter(
    kind=CommentKind.EMAIL_OUT,
    delivery_status=EmailDeliveryStatus.FAILED
)
```

## Error Handling

The service raises or returns errors in the following scenarios:

### Exceptions Raised

- **`ServiceDisabled`**: Graph API is not enabled in configuration
- **`ServiceNotConfigured`**: Graph API is enabled but missing required fields
- **`ServiceError`**: Validation errors (e.g., empty subject, no recipients)

### Graceful Failures

The `send_email()` function catches exceptions during the actual send operation and returns a `GraphSendResult` with `success=False` and an `error` message. This allows callers to handle failures gracefully without catching exceptions.

```python
result = send_email(...)
if not result.success:
    logger.error(f"Email send failed: {result.error}")
    # Handle failure (e.g., notify admin, retry later)
```

### Common Error Scenarios

| Error | Cause | Solution |
|-------|-------|----------|
| Service not enabled | `enabled=False` in config | Enable in admin panel |
| Service not configured | Missing tenant_id, client_id, or client_secret | Complete configuration in admin |
| Invalid credentials | Wrong client_id or client_secret | Verify Azure app credentials |
| Missing permissions | App doesn't have Mail.Send permission | Add permission and grant admin consent |
| Invalid sender | Sender mailbox doesn't exist | Use valid UPN from your tenant |
| Attachment too large | Attachment > 3 MB | Use smaller files or provide download links |
| Empty subject | Subject is empty or whitespace | Provide non-empty subject |
| No recipients | `to` list is empty | Provide at least one recipient |

## Security Considerations

### Token Handling

- Access tokens are cached in memory with automatic expiry tracking
- Tokens are refreshed automatically 5 minutes before expiry
- Tokens are never logged or exposed in error messages

### Client Secret Storage

- Client secrets are encrypted in the database using `django-encrypted-model-fields`
- The encryption key is stored in Django's `SECRET_KEY` setting
- Never commit secrets to version control

### Permissions

The Graph API application requires **Mail.Send** (application permission):
- Allows sending email as any user in the tenant
- Does not allow reading emails
- Requires admin consent

**Best practice**: Use a dedicated service account or shared mailbox as the sender, not personal accounts.

## Admin Panel

### Configuration Admin

The `GraphAPIConfiguration` admin provides:
- Masked display of `client_secret` field (shows `••••••••`)
- Help text for each field
- Single-instance model (singleton)

### ItemComment Admin

You can filter `ItemComment` entries by:
- `kind=EmailOut` to see all outbound emails
- `delivery_status` to find failed sends

## Testing

### Running Tests

```bash
# Run all Graph service tests
python manage.py test core.services.graph

# Run client tests only
python manage.py test core.services.graph.test_client

# Run mail service tests only
python manage.py test core.services.graph.test_mail_service
```

### Manual Testing

```python
# In Django shell
from core.services.graph import send_email

result = send_email(
    subject="Test Email from Agira",
    body="<p>This is a test email.</p>",
    to=["your-email@example.com"],
)

print(f"Success: {result.success}")
if result.error:
    print(f"Error: {result.error}")
```

## Troubleshooting

### "Service not enabled"

**Cause**: `enabled=False` in `GraphAPIConfiguration`

**Solution**: Go to Django admin → Graph API Configuration → check "Enabled" → Save

### "Service not configured"

**Cause**: Missing `tenant_id`, `client_id`, or `client_secret`

**Solution**: Fill in all required fields in Graph API Configuration

### "Failed to acquire token: invalid_client"

**Cause**: Incorrect `client_id` or `client_secret`

**Solution**: 
1. Verify client_id matches your Azure app
2. Generate a new client secret in Azure Portal
3. Update client_secret in Agira configuration

### "Failed to acquire token: unauthorized_client"

**Cause**: Application doesn't have Mail.Send permission or admin consent not granted

**Solution**:
1. Azure Portal → Your App → API permissions
2. Add `Mail.Send` (Application)
3. Click "Grant admin consent"

### "Graph API request failed (403): Forbidden"

**Cause**: Token doesn't have required permissions, or sender mailbox doesn't exist

**Solution**:
1. Verify Mail.Send permission is granted
2. Verify sender email is a valid mailbox in your tenant
3. Check if conditional access policies block app-only authentication

### Email not received

**Possible causes**:
- Email in spam/junk folder
- Sender mailbox has sending restrictions
- Recipient address is incorrect
- Delay in email delivery (check after a few minutes)

**Check**:
1. Verify `ItemComment` has `delivery_status=Sent`
2. Check sender's "Sent Items" folder in Outlook
3. Check recipient spam folder
4. Verify recipient email address is correct

## Roadmap (Future Versions)

**v2: Inbound & Threading**
- Fetch incoming emails
- Thread detection and linking
- Auto-create items from emails
- Handle replies and forwarding

**v3: Advanced Features**
- Large attachment support (upload sessions)
- Email templates
- Bulk sending with rate limiting
- Read receipts / delivery reports
- Calendar integration

## References

- [Microsoft Graph API - Send mail](https://learn.microsoft.com/en-us/graph/api/user-sendmail)
- [Microsoft Graph API - File attachments](https://learn.microsoft.com/en-us/graph/api/resources/fileattachment)
- [MSAL Python Documentation](https://msal-python.readthedocs.io/)
- [Azure AD App Registration](https://learn.microsoft.com/en-us/azure/active-directory/develop/quickstart-register-app)

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review logs in `core.services.graph.client` and `core.services.graph.mail_service`
3. Verify Azure app configuration
4. Test token acquisition separately using MSAL

---

*Last updated: 2026-01-24*
*Version: 1.0 (Send Only)*
