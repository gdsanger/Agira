"""
Mail Template Processing Service.

This module provides functionality to process mail templates by replacing
template variables with actual values from Item instances.
"""

import html
from typing import TYPE_CHECKING
import markdown
import bleach
from bleach.css_sanitizer import CSSSanitizer
from django.utils.safestring import mark_safe

if TYPE_CHECKING:
    from core.models import Item, MailTemplate


# Allowed HTML tags and attributes for sanitization
# (used when converting Markdown to HTML for solution_description)
ALLOWED_TAGS = [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'br', 'strong', 'em', 'u', 'strike',
    'ul', 'ol', 'li',
    'blockquote', 'code', 'pre',
    'a', 'img',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'div', 'span'
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target', 'rel', 'style'],
    'img': ['src', 'alt', 'title', 'width', 'height', 'style'],
    'code': ['class', 'style'],
    'pre': ['class', 'style'],
    'div': ['class', 'style'],
    'span': ['class', 'style'],
    'p': ['style'],
    'h1': ['style'],
    'h2': ['style'],
    'h3': ['style'],
    'h4': ['style'],
    'h5': ['style'],
    'h6': ['style'],
    'td': ['style'],
    'th': ['style'],
    'tr': ['style'],
    'table': ['style'],
    'thead': ['style'],
    'tbody': ['style'],
    'ul': ['style'],
    'ol': ['style'],
    'li': ['style'],
    'strong': ['style'],
    'em': ['style'],
    'u': ['style'],
    'strike': ['style'],
    'blockquote': ['style'],
}

# CSS properties that are allowed in inline styles
ALLOWED_CSS_PROPERTIES = [
    'color', 'background-color', 'font-size', 'font-weight', 'font-family', 'font-style',
    'text-align', 'text-decoration', 'line-height', 'letter-spacing', 'vertical-align',
    'margin', 'margin-top', 'margin-right', 'margin-bottom', 'margin-left',
    'padding', 'padding-top', 'padding-right', 'padding-bottom', 'padding-left',
    'border', 'border-width', 'border-style', 'border-color', 'border-radius',
    'border-top', 'border-right', 'border-bottom', 'border-left',
    'width', 'height', 'max-width', 'max-height', 'min-width', 'min-height',
    'display', 'float', 'clear', 'text-transform'
]

# Create a CSS sanitizer for safe inline styles
css_sanitizer = CSSSanitizer(allowed_css_properties=ALLOWED_CSS_PROPERTIES)


def _convert_markdown_to_html(text):
    """
    Convert Markdown text to sanitized HTML.
    
    This function is specifically used for the solution_description field which
    contains Markdown content that needs to be rendered as HTML in email templates.
    
    Args:
        text: Markdown-formatted text
        
    Returns:
        Safe HTML string (marked as safe to prevent double-escaping)
    """
    if not text:
        return ""
    
    # Create a new markdown parser instance for thread safety
    md_parser = markdown.Markdown(extensions=['extra', 'fenced_code'])
    
    # Convert markdown to HTML
    html_content = md_parser.convert(text)
    
    # Sanitize HTML to prevent XSS attacks
    sanitized_html = bleach.clean(
        html_content,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        css_sanitizer=css_sanitizer,
        strip=True
    )
    
    # Mark as safe to prevent double-escaping in email templates
    return mark_safe(sanitized_html)


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
    
    # Convert solution_description from Markdown to HTML
    # This field contains Markdown content that needs to be rendered as HTML in emails
    solution_description_html = _convert_markdown_to_html(item.solution_description or '')
    
    replacements = {
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
