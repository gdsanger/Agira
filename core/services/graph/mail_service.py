"""
Microsoft Graph API Mail Service for Agira.

This module provides email sending capabilities via Microsoft Graph API,
including support for attachments and ItemComment logging.

Version 1: Send Only (no inbound fetching or threading)
"""

import logging
import base64
from dataclasses import dataclass
from typing import List, Optional, TYPE_CHECKING
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from core.services.config import get_graph_config
from core.services.exceptions import ServiceNotConfigured, ServiceDisabled, ServiceError
from .client import get_client

if TYPE_CHECKING:
    from core.models import Attachment, Item, User

logger = logging.getLogger(__name__)


@dataclass
class GraphSendResult:
    """Result of a send_email operation."""
    sender: str
    to: List[str]
    subject: str
    success: bool
    error: Optional[str] = None


# Max attachment size for v1 (in bytes)
# Graph API supports up to ~150MB with upload sessions, but v1 uses simple attachments
MAX_ATTACHMENT_SIZE_V1 = 3 * 1024 * 1024  # 3 MB


def _normalize_email(email: str) -> str:
    """
    Normalize an email address for comparison.
    
    Args:
        email: Email address to normalize
        
    Returns:
        Normalized email address (trimmed and lowercase)
    """
    return email.strip().lower()


def _is_blocked_system_recipient(email_addresses: List[str]) -> bool:
    """
    Check if any of the given email addresses matches the system's default address.
    
    This function prevents mail loops by blocking emails sent to Agira's own
    default email address (which is used for email ingestion via Graph API).
    
    Args:
        email_addresses: List of email addresses to check
        
    Returns:
        True if any address matches the system default address, False otherwise
    """
    if not email_addresses:
        return False
    
    config = get_graph_config()
    if config is None or not config.default_mail_sender:
        # No default address configured, so nothing to block
        return False
    
    system_address = _normalize_email(config.default_mail_sender)
    
    for addr in email_addresses:
        if _normalize_email(addr) == system_address:
            return True
    
    return False


def send_email(
    subject: str,
    body: str,
    to: List[str],
    body_is_html: bool = True,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    sender: Optional[str] = None,
    attachments: Optional[List["Attachment"]] = None,
    item: Optional["Item"] = None,
    author: Optional["User"] = None,
    visibility: str = "Internal",
    client_ip: Optional[str] = None,
) -> GraphSendResult:
    """
    Send an email via Microsoft Graph API.
    
    Args:
        subject: Email subject (required, non-empty)
        body: Email body content
        to: List of recipient email addresses (required, at least one)
        body_is_html: If True, body is HTML; if False, body is plain text
        cc: Optional list of CC recipients
        bcc: Optional list of BCC recipients
        sender: Optional sender email (UPN). If None, uses default_mail_sender from config
        attachments: Optional list of Attachment model instances to attach
        item: Optional Item instance to log email as ItemComment
        author: Optional User instance for the comment author
        visibility: Visibility of the ItemComment (Public or Internal)
        client_ip: Optional client IP for audit logging
        
    Returns:
        GraphSendResult with success status and details
        
    Raises:
        ServiceError: If validation fails or sending encounters an error
        
    Example:
        >>> result = send_email(
        ...     subject="Hello",
        ...     body="<p>This is a test</p>",
        ...     to=["user@example.com"],
        ...     sender="support@mycompany.com"
        ... )
        >>> if result.success:
        ...     print("Email sent!")
    """
    # Import models here to avoid circular imports
    from core.models import ItemComment, AttachmentLink, EmailDeliveryStatus, CommentKind
    
    # Validate inputs
    if not subject or not subject.strip():
        raise ServiceError("Email subject cannot be empty")
    
    if not to or len(to) == 0:
        raise ServiceError("At least one recipient is required")
    
    # Get configuration
    config = get_graph_config()
    if config is None or not config.enabled:
        raise ServiceDisabled("Graph API service is not enabled")
    
    # Mail loop protection: Check if any recipient is the system default address
    all_recipients = list(to)
    if cc:
        all_recipients.extend(cc)
    if bcc:
        all_recipients.extend(bcc)
    
    if _is_blocked_system_recipient(all_recipients):
        # Log the blocked attempt with details
        blocked_addresses = [
            addr for addr in all_recipients 
            if _normalize_email(addr) == _normalize_email(config.default_mail_sender)
        ]
        logger.warning(
            f"Blocked mail to system default address (Agira self-mail protection). "
            f"Subject: '{subject}', "
            f"Default address: '{config.default_mail_sender}', "
            f"Blocked recipients: {blocked_addresses}, "
            f"All recipients (to/cc/bcc): {all_recipients}"
        )
        
        # Return failure result without sending
        return GraphSendResult(
            sender=sender or config.default_mail_sender or "unknown",
            to=to,
            subject=subject,
            success=False,
            error="Email blocked: recipient list contains system default address (mail loop protection)",
        )
    
    # Determine sender
    if sender is None:
        if not config.default_mail_sender:
            raise ServiceNotConfigured(
                "No sender specified and no default_mail_sender configured"
            )
        sender = config.default_mail_sender
    
    # Add issue ID prefix to subject if item is provided
    # Format: [AGIRA-{id}] Original Subject
    # This allows replies to be threaded back to the original item
    if item is not None:
        subject = f"[AGIRA-{item.id}] {subject}"
    
    # Create ItemComment if item is provided (set to Queued initially)
    comment = None
    if item is not None:
        comment = ItemComment.objects.create(
            item=item,
            author=author,
            visibility=visibility,
            kind=CommentKind.EMAIL_OUT,
            subject=subject,
            body=body if not body_is_html else "",
            body_html=body if body_is_html else "",
            external_from=sender,
            external_to=", ".join(to),  # Store as comma-separated string
            delivery_status=EmailDeliveryStatus.QUEUED,
        )
        logger.info(f"Created ItemComment {comment.id} for outbound email")
    
    try:
        # Build Graph API payload
        payload = _build_email_payload(
            subject=subject,
            body=body,
            body_is_html=body_is_html,
            to=to,
            cc=cc,
            bcc=bcc,
            attachments=attachments,
        )
        
        # Send via Graph API client
        client = get_client()
        client.send_mail(sender_upn=sender, payload=payload)
        
        # Update comment to Sent
        if comment:
            comment.delivery_status = EmailDeliveryStatus.SENT
            comment.sent_at = timezone.now()
            comment.save()
            
            # Link attachments if any
            if attachments:
                _link_attachments_to_comment(attachments, comment)
        
        logger.info(f"Email sent successfully to {len(to)} recipient(s)")
        
        return GraphSendResult(
            sender=sender,
            to=to,
            subject=subject,
            success=True,
        )
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Failed to send email: {error_msg}")
        
        # Update comment to Failed
        if comment:
            comment.delivery_status = EmailDeliveryStatus.FAILED
            comment.save()
        
        # Return failure result (don't re-raise to allow caller to handle gracefully)
        return GraphSendResult(
            sender=sender,
            to=to,
            subject=subject,
            success=False,
            error=error_msg,
        )


def _build_email_payload(
    subject: str,
    body: str,
    body_is_html: bool,
    to: List[str],
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    attachments: Optional[List] = None,
) -> dict:
    """
    Build the Graph API sendMail payload.
    
    Args:
        subject: Email subject
        body: Email body
        body_is_html: Whether body is HTML
        to: List of recipient emails
        cc: Optional CC recipients
        bcc: Optional BCC recipients
        attachments: Optional list of Attachment instances
        
    Returns:
        Dict payload for Graph API sendMail endpoint
        
    Raises:
        ServiceError: If attachment processing fails
    """
    # Build message structure
    message = {
        "subject": subject,
        "body": {
            "contentType": "HTML" if body_is_html else "Text",
            "content": body,
        },
        "toRecipients": [{"emailAddress": {"address": addr}} for addr in to],
    }
    
    # Add CC recipients
    if cc and len(cc) > 0:
        message["ccRecipients"] = [{"emailAddress": {"address": addr}} for addr in cc]
    
    # Add BCC recipients
    if bcc and len(bcc) > 0:
        message["bccRecipients"] = [{"emailAddress": {"address": addr}} for addr in bcc]
    
    # Add attachments
    if attachments and len(attachments) > 0:
        message["attachments"] = []
        for attachment in attachments:
            file_attachment = _process_attachment(attachment)
            message["attachments"].append(file_attachment)
    
    # Return sendMail payload
    return {
        "message": message,
        "saveToSentItems": "true",
    }


def _process_attachment(attachment) -> dict:
    """
    Process an Attachment model instance into Graph API format.
    
    Args:
        attachment: Attachment model instance
        
    Returns:
        Dict in Graph API fileAttachment format
        
    Raises:
        ServiceError: If attachment is too large or cannot be read
    """
    # Check size
    if attachment.size > MAX_ATTACHMENT_SIZE_V1:
        raise ServiceError(
            f"Attachment '{attachment.original_name}' is too large "
            f"({attachment.size / (1024*1024):.1f} MB). "
            f"Maximum size for v1 is {MAX_ATTACHMENT_SIZE_V1 / (1024*1024):.0f} MB"
        )
    
    # Read file and encode to base64
    try:
        attachment.file.seek(0)
        file_content = attachment.file.read()
        content_bytes = base64.b64encode(file_content).decode('utf-8')
    except Exception as e:
        raise ServiceError(f"Failed to read attachment '{attachment.original_name}': {str(e)}")
    
    # Return Graph API fileAttachment structure
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": attachment.original_name,
        "contentType": attachment.content_type,
        "contentBytes": content_bytes,
    }


def _link_attachments_to_comment(attachments: List, comment) -> None:
    """
    Link attachments to an ItemComment.
    
    Args:
        attachments: List of Attachment instances
        comment: ItemComment instance
    """
    from core.models import AttachmentLink, AttachmentRole
    
    content_type = ContentType.objects.get_for_model(comment)
    
    for attachment in attachments:
        # Create AttachmentLink with role CommentAttachment
        AttachmentLink.objects.create(
            attachment=attachment,
            target_content_type=content_type,
            target_object_id=comment.id,
            role=AttachmentRole.COMMENT_ATTACHMENT,
        )
        logger.debug(f"Linked attachment {attachment.id} to comment {comment.id}")
