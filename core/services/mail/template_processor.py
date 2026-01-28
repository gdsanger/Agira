"""
Mail Template Processing Service.

This module provides functionality to process mail templates by replacing
template variables with actual values from Item instances.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models import Item, MailTemplate


def process_template(template: "MailTemplate", item: "Item") -> dict:
    """
    Process a mail template by replacing template variables with item data.
    
    Supported variables:
    - {{ issue.title }} - Item title
    - {{ issue.status }} - Item status (display name)
    - {{ issue.type }} - Item type name
    - {{ issue.project }} - Project name
    - {{ issue.requester }} - Requester name (or empty if not set)
    - {{ issue.assigned_to }} - Assigned user name (or empty if not set)
    - {{ issue.solution_release }} - Solution release name (or empty if not set)
    
    Args:
        template: MailTemplate instance with subject and message containing variables
        item: Item instance to extract values from
        
    Returns:
        dict with 'subject' and 'message' keys containing processed strings
        
    Example:
        >>> template = MailTemplate.objects.get(key='status-changed')
        >>> item = Item.objects.get(id=123)
        >>> result = process_template(template, item)
        >>> print(result['subject'])  # Variables replaced with actual values
    """
    # Build replacement dictionary
    replacements = {
        '{{ issue.title }}': item.title or '',
        '{{ issue.status }}': item.get_status_display() or '',
        '{{ issue.type }}': item.type.name if item.type else '',
        '{{ issue.project }}': item.project.name if item.project else '',
        '{{ issue.requester }}': item.requester.name if item.requester else '',
        '{{ issue.assigned_to }}': item.assigned_to.name if item.assigned_to else '',
        '{{ issue.solution_release }}': item.solution_release.name if item.solution_release else '',
    }
    
    # Process subject
    subject = template.subject
    for var, value in replacements.items():
        subject = subject.replace(var, value)
    
    # Process message
    message = template.message
    for var, value in replacements.items():
        message = message.replace(var, value)
    
    return {
        'subject': subject,
        'message': message,
    }
