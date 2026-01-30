"""
Mail Template Processing Service.

This module provides functionality to process mail templates by replacing
template variables with actual values from Item instances.
"""

import html
from typing import TYPE_CHECKING
from core.utils.html_sanitization import convert_markdown_to_html, strip_html_tags

if TYPE_CHECKING:
    from core.models import Item, MailTemplate


def process_template(template: "MailTemplate", item: "Item") -> dict:
    """
    Process a mail template by replacing template variables with item data.
    
    User-provided data is HTML-escaped to prevent XSS vulnerabilities.
    
    Special handling for solution_description:
    - The solution_description field contains Markdown content
    - It is converted from Markdown to HTML before being inserted into email templates
    - The HTML output is sanitized but NOT escaped (to preserve HTML tags)
    
    Note: To avoid N+1 queries when processing multiple items, callers should
    prefetch related data using:
    - select_related('requester', 'solution_release')
    - prefetch_related('requester__user_organisations__organisation')
    
    Supported variables:
    - {{ issue.title }} - Item title
    - {{ issue.description }} - Item description
    - {{ issue.solution_description }} - Solution description converted from Markdown to HTML
    - {{ solution_description }} - Solution description (backward compatibility alias, converted from Markdown to HTML)
    - {{ issue.status }} - Item status (display name)
    - {{ issue.type }} - Item type name
    - {{ issue.project }} - Project name
    - {{ issue.requester }} - Requester name (or empty if not set)
    - {{ issue.assigned_to }} - Assigned user name (or empty if not set)
    - {{ issue.organisation }} - Requester's primary organisation name (or empty if not set)
    - {{ issue.solution_release }} - Solution release info with name, version and date (or empty if not set)
    
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
    # Build replacement dictionary - escape user-provided values
    # Get requester's primary organisation if available
    requester_org = ''
    if item.requester:
        primary_org = item.requester.user_organisations.filter(is_primary=True).first()
        if primary_org:
            requester_org = primary_org.organisation.name
    
    # Build solution release info with name, version and date
    solution_release_info = ''
    if item.solution_release:
        parts = []
        if item.solution_release.name:
            parts.append(item.solution_release.name)
        if item.solution_release.version:
            parts.append(f"Version {item.solution_release.version}")
        if item.solution_release.update_date:
            # Format date as YYYY-MM-DD
            date_str = item.solution_release.update_date.strftime('%Y-%m-%d')
            parts.append(f"Planned: {date_str}")
        solution_release_info = ' - '.join(parts)
    
    # Convert solution_description from Markdown to HTML for message body
    # For subjects, we need plain text (HTML tags look unprofessional in subject lines)
    solution_description_html = convert_markdown_to_html(item.solution_description or '')
    solution_description_plain = strip_html_tags(solution_description_html)
    
    # Replacements for message body (HTML content)
    message_replacements = {
        '{{ issue.title }}': html.escape(item.title or ''),
        '{{ issue.description }}': html.escape(item.description or ''),
        # solution_description is converted from Markdown to HTML (not escaped)
        '{{ issue.solution_description }}': solution_description_html,
        # Special case: Support non-prefixed {{ solution_description }} for backward compatibility
        # This addresses Issue #261 where users were using the non-prefixed format
        '{{ solution_description }}': solution_description_html,
        '{{ issue.status }}': html.escape(item.get_status_display() or ''),
        '{{ issue.type }}': html.escape(item.type.name if item.type else ''),
        '{{ issue.project }}': html.escape(item.project.name if item.project else ''),
        '{{ issue.requester }}': html.escape(item.requester.name if item.requester else ''),
        '{{ issue.assigned_to }}': html.escape(item.assigned_to.name if item.assigned_to else ''),
        '{{ issue.organisation }}': html.escape(requester_org),
        '{{ issue.solution_release }}': html.escape(solution_release_info),
    }
    
    # Replacements for subject (plain text - no HTML tags)
    subject_replacements = {
        '{{ issue.title }}': html.escape(item.title or ''),
        '{{ issue.description }}': html.escape(item.description or ''),
        # solution_description in subject: use plain text version (HTML stripped)
        '{{ issue.solution_description }}': html.escape(solution_description_plain),
        '{{ solution_description }}': html.escape(solution_description_plain),
        '{{ issue.status }}': html.escape(item.get_status_display() or ''),
        '{{ issue.type }}': html.escape(item.type.name if item.type else ''),
        '{{ issue.project }}': html.escape(item.project.name if item.project else ''),
        '{{ issue.requester }}': html.escape(item.requester.name if item.requester else ''),
        '{{ issue.assigned_to }}': html.escape(item.assigned_to.name if item.assigned_to else ''),
        '{{ issue.organisation }}': html.escape(requester_org),
        '{{ issue.solution_release }}': html.escape(solution_release_info),
    }
    
    # Process subject with plain text replacements
    subject = template.subject
    for var, value in subject_replacements.items():
        subject = subject.replace(var, value)
    
    # Process message with HTML replacements
    message = template.message
    for var, value in message_replacements.items():
        message = message.replace(var, value)
    
    return {
        'subject': subject,
        'message': message,
    }
