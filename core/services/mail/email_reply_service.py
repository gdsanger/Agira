"""
Email Reply and Forward Service for Agira.

This service provides functionality for replying to and forwarding emails
stored as ItemComments.
"""

import logging
import re
from typing import Dict, List, Optional, TYPE_CHECKING
from django.utils import timezone

if TYPE_CHECKING:
    from core.models import ItemComment, User

logger = logging.getLogger(__name__)


def _parse_email_addresses(email_string: str) -> List[str]:
    """
    Parse a semicolon or comma-separated string of email addresses.
    
    Args:
        email_string: String containing email addresses
        
    Returns:
        List of email addresses
    """
    if not email_string:
        return []
    
    # Split by semicolon or comma
    addresses = re.split(r'[;,]', email_string)
    
    # Clean up and filter empty strings
    return [addr.strip() for addr in addresses if addr.strip()]


def _ensure_subject_prefix(subject: str, prefix: str) -> str:
    """
    Add prefix to subject if not already present.
    
    Args:
        subject: Original subject
        prefix: Prefix to add (e.g., "RE:", "FW:")
        
    Returns:
        Subject with prefix
    """
    if not subject:
        return prefix
    
    # Check if subject already starts with the prefix (case-insensitive)
    prefix_upper = prefix.upper().rstrip(':')
    subject_upper = subject.upper()
    
    # Common reply/forward prefixes
    common_prefixes = ['RE:', 'FW:', 'FWD:', 'AW:', 'WG:']
    
    for common_prefix in common_prefixes:
        if subject_upper.startswith(common_prefix):
            # Already has a prefix, don't add another
            return subject
    
    return f"{prefix} {subject}"


def _get_system_default_address() -> Optional[str]:
    """
    Get the system's default mail sender address.
    
    Returns:
        Default mail sender address or None
    """
    from core.services.config import get_graph_config
    
    config = get_graph_config()
    if config and config.default_mail_sender:
        return config.default_mail_sender.lower().strip()
    
    return None


def _filter_recipients(addresses: List[str], exclude_user: Optional["User"] = None) -> List[str]:
    """
    Filter recipients to exclude system address and optionally current user.
    
    Args:
        addresses: List of email addresses
        exclude_user: Optional user to exclude from recipient list
        
    Returns:
        Filtered list of email addresses
    """
    system_address = _get_system_default_address()
    
    filtered = []
    for addr in addresses:
        addr_normalized = addr.lower().strip()
        
        # Skip system address (mail loop protection)
        if system_address and addr_normalized == system_address:
            continue
        
        # Skip current user's email if provided
        if exclude_user and exclude_user.email and addr_normalized == exclude_user.email.lower().strip():
            continue
        
        filtered.append(addr)
    
    return filtered


def prepare_reply(comment: "ItemComment", current_user: Optional["User"] = None) -> Dict[str, any]:
    """
    Prepare data for replying to an email comment.
    
    Args:
        comment: ItemComment to reply to (should be EMAIL_IN or EMAIL_OUT)
        current_user: Current user composing the reply
        
    Returns:
        Dictionary with prepared reply data:
        - to: List of recipient addresses
        - cc: List of CC addresses (empty for simple reply)
        - subject: Subject with RE: prefix
        - body: Quoted original message body
        - in_reply_to: Message ID for threading
    """
    # Determine who to reply to
    # For incoming emails, reply to the sender
    # For outgoing emails, reply to the original recipients
    if comment.kind == 'EmailIn':
        to_addresses = [comment.external_from] if comment.external_from else []
    else:
        # For outgoing emails, reply to the recipients
        to_addresses = _parse_email_addresses(comment.external_to)
    
    # Filter recipients (remove system address)
    to_addresses = _filter_recipients(to_addresses, exclude_user=None)
    
    # Subject with RE: prefix
    subject = _ensure_subject_prefix(comment.subject, "RE:")
    
    # Prepare quoted body
    body = _prepare_quoted_body(comment)
    
    return {
        'to': to_addresses,
        'cc': [],
        'subject': subject,
        'body': body,
        'in_reply_to': comment.message_id,
    }


def prepare_reply_all(comment: "ItemComment", current_user: Optional["User"] = None) -> Dict[str, any]:
    """
    Prepare data for replying to all recipients of an email comment.
    
    Args:
        comment: ItemComment to reply to (should be EMAIL_IN or EMAIL_OUT)
        current_user: Current user composing the reply
        
    Returns:
        Dictionary with prepared reply data (same structure as prepare_reply)
    """
    # For incoming emails
    if comment.kind == 'EmailIn':
        # To: original sender
        to_addresses = [comment.external_from] if comment.external_from else []
        
        # CC: original To and CC recipients
        cc_addresses = []
        cc_addresses.extend(_parse_email_addresses(comment.external_to))
        cc_addresses.extend(_parse_email_addresses(comment.external_cc))
    else:
        # For outgoing emails, include all original recipients
        to_addresses = _parse_email_addresses(comment.external_to)
        cc_addresses = _parse_email_addresses(comment.external_cc)
    
    # Filter recipients (remove system address and current user)
    to_addresses = _filter_recipients(to_addresses, exclude_user=current_user)
    cc_addresses = _filter_recipients(cc_addresses, exclude_user=current_user)
    
    # Remove duplicates while preserving order
    seen = set()
    to_unique = []
    for addr in to_addresses:
        addr_lower = addr.lower()
        if addr_lower not in seen:
            seen.add(addr_lower)
            to_unique.append(addr)
    
    cc_unique = []
    for addr in cc_addresses:
        addr_lower = addr.lower()
        if addr_lower not in seen:
            seen.add(addr_lower)
            cc_unique.append(addr)
    
    # Subject with RE: prefix
    subject = _ensure_subject_prefix(comment.subject, "RE:")
    
    # Prepare quoted body
    body = _prepare_quoted_body(comment)
    
    return {
        'to': to_unique,
        'cc': cc_unique,
        'subject': subject,
        'body': body,
        'in_reply_to': comment.message_id,
    }


def prepare_forward(comment: "ItemComment", current_user: Optional["User"] = None) -> Dict[str, any]:
    """
    Prepare data for forwarding an email comment.
    
    Args:
        comment: ItemComment to forward (should be EMAIL_IN or EMAIL_OUT)
        current_user: Current user composing the forward
        
    Returns:
        Dictionary with prepared forward data:
        - to: Empty list (user will fill in)
        - cc: Empty list (user will fill in)
        - subject: Subject with FW: prefix
        - body: Original message with headers
        - in_reply_to: Empty (not a direct reply)
    """
    # Subject with FW: prefix
    subject = _ensure_subject_prefix(comment.subject, "FW:")
    
    # Prepare forwarded body with full headers
    body = _prepare_forwarded_body(comment)
    
    return {
        'to': [],
        'cc': [],
        'subject': subject,
        'body': body,
        'in_reply_to': '',
    }


def _prepare_quoted_body(comment: "ItemComment") -> str:
    """
    Prepare quoted body for reply (HTML format).
    
    Args:
        comment: ItemComment with original message
        
    Returns:
        HTML string with quoted original message
    """
    # Use original HTML if available, otherwise use body
    original_content = comment.body_original_html if comment.body_original_html else comment.body_html
    
    # If still no HTML, convert plain text body to HTML
    if not original_content:
        original_content = comment.body.replace('\n', '<br>')
    
    # Format as quoted reply
    from_name = comment.author.name if comment.author else comment.external_from
    created_at = comment.created_at.strftime("%Y-%m-%d %H:%M") if comment.created_at else ""
    
    quoted_body = f"""
<p><br></p>
<p><br></p>
<hr>
<p><strong>From:</strong> {from_name}<br>
<strong>Sent:</strong> {created_at}<br>
<strong>Subject:</strong> {comment.subject}</p>
<blockquote style="border-left: 3px solid #ccc; padding-left: 10px; margin-left: 0;">
{original_content}
</blockquote>
"""
    
    return quoted_body


def _prepare_forwarded_body(comment: "ItemComment") -> str:
    """
    Prepare body for forward with full email headers (HTML format).
    
    Args:
        comment: ItemComment with original message
        
    Returns:
        HTML string with forwarded message and headers
    """
    # Use original HTML if available
    original_content = comment.body_original_html if comment.body_original_html else comment.body_html
    
    # If still no HTML, convert plain text body to HTML
    if not original_content:
        original_content = comment.body.replace('\n', '<br>')
    
    # Format forwarded message with full headers
    from_name = comment.author.name if comment.author else comment.external_from
    to_addresses = comment.external_to if comment.external_to else ""
    cc_addresses = comment.external_cc if comment.external_cc else ""
    created_at = comment.created_at.strftime("%Y-%m-%d %H:%M") if comment.created_at else ""
    
    forwarded_body = f"""
<p><br></p>
<p><br></p>
<hr>
<p><strong>---------- Forwarded message ----------</strong></p>
<p><strong>From:</strong> {from_name}<br>
<strong>Date:</strong> {created_at}<br>
<strong>Subject:</strong> {comment.subject}<br>
<strong>To:</strong> {to_addresses}"""
    
    if cc_addresses:
        forwarded_body += f"<br><strong>CC:</strong> {cc_addresses}"
    
    forwarded_body += f"""</p>
<p><br></p>
{original_content}
"""
    
    return forwarded_body
