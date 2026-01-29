"""
Mail Trigger Service.

This module provides functionality to check if a mail should be triggered
based on item status and type, and to prepare mail previews.
"""

from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Item, MailActionMapping

from .template_processor import process_template


def get_notification_recipients_for_item(item: "Item") -> dict:
    """
    Get email recipients for item notifications.
    
    Args:
        item: Item instance to get recipients for
        
    Returns:
        dict with 'to' (requester email) and 'cc' (list of follower emails)
        
    Example:
        >>> item = Item.objects.get(id=123)
        >>> recipients = get_notification_recipients_for_item(item)
        >>> print(recipients['to'])  # requester@example.com
        >>> print(recipients['cc'])  # ['follower1@example.com', 'follower2@example.com']
    """
    result = {
        'to': None,
        'cc': []
    }
    
    # Get requester email for 'to'
    if item.requester and item.requester.email:
        result['to'] = item.requester.email
    
    # Get follower emails for 'cc'
    followers = item.get_followers().filter(email__isnull=False).exclude(email='')
    follower_emails = list(followers.values_list('email', flat=True))
    
    # Remove duplicates and exclude requester from CC if present
    unique_emails = []
    seen = set()
    if result['to']:
        seen.add(result['to'])
    
    for email in follower_emails:
        if email and email not in seen:
            unique_emails.append(email)
            seen.add(email)
    
    result['cc'] = unique_emails
    
    return result


def check_mail_trigger(item: "Item") -> Optional["MailActionMapping"]:
    """
    Check if there is an active MailActionMapping for the given item's status and type.
    
    Args:
        item: Item instance to check
        
    Returns:
        MailActionMapping instance if found and active, None otherwise
        
    Example:
        >>> item = Item.objects.get(id=123)
        >>> mapping = check_mail_trigger(item)
        >>> if mapping:
        ...     print(f"Mail template: {mapping.mail_template.key}")
    """
    from core.models import MailActionMapping
    
    # Look for active mapping matching item's status and type
    try:
        mapping = MailActionMapping.objects.get(
            is_active=True,
            item_status=item.status,
            item_type=item.type
        )
        return mapping
    except MailActionMapping.DoesNotExist:
        return None
    except MailActionMapping.MultipleObjectsReturned:
        # If multiple mappings exist (shouldn't happen with proper constraints),
        # return the first one
        return MailActionMapping.objects.filter(
            is_active=True,
            item_status=item.status,
            item_type=item.type
        ).first()


def prepare_mail_preview(item: "Item", mapping: "MailActionMapping") -> dict:
    """
    Prepare a mail preview by processing the template with item data.
    
    Args:
        item: Item instance to use for variable replacement
        mapping: MailActionMapping containing the template to use
        
    Returns:
        dict with processed 'subject', 'message', and template metadata
        
    Example:
        >>> mapping = check_mail_trigger(item)
        >>> if mapping:
        ...     preview = prepare_mail_preview(item, mapping)
        ...     print(preview['subject'])
        ...     print(preview['message'])
    """
    template = mapping.mail_template
    
    # Process template variables
    processed = process_template(template, item)
    
    # Return preview with additional metadata
    return {
        'subject': processed['subject'],
        'message': processed['message'],
        'template_key': template.key,
        'from_name': template.from_name or '',
        'from_address': template.from_address or '',
        'cc_address': template.cc_address or '',
    }
