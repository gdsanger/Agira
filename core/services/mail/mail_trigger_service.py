"""
Mail Trigger Service.

This module provides functionality to check if a mail should be triggered
based on item status and type, and to prepare mail previews.
"""

from typing import Optional, TYPE_CHECKING
from .template_processor import process_template

if TYPE_CHECKING:
    from core.models import Item, MailActionMapping


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
