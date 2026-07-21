"""Custom template filters for Agira."""
from django import template
from django.utils.html import escape
from django.utils.safestring import mark_safe
from core.utils.html_sanitization import (
    convert_markdown_to_html,
    sanitize_html,
)
from core.services.comments.mentions import MENTION_PATTERN

register = template.Library()


@register.filter
def filesize(bytes_value):
    """
    Format file size in human-readable format.
    
    Args:
        bytes_value: File size in bytes
        
    Returns:
        Formatted string (e.g., "1.5 MB", "256 KB", "42 B")
    """
    try:
        bytes_value = int(bytes_value)
    except (ValueError, TypeError):
        return "0 B"
    
    if bytes_value < 1024:
        return f"{bytes_value} B"
    elif bytes_value < 1048576:  # 1024 * 1024
        return f"{bytes_value / 1024:.1f} KB"
    elif bytes_value < 1073741824:  # 1024 * 1024 * 1024
        return f"{bytes_value / 1048576:.1f} MB"
    else:
        return f"{bytes_value / 1073741824:.1f} GB"


@register.filter
def render_markdown(text):
    """
    Render Markdown text to HTML with sanitization.
    
    Args:
        text: Markdown-formatted text
        
    Returns:
        Safe HTML string
    """
    return convert_markdown_to_html(text)


@register.filter
def render_mentions(text):
    """
    Escape plain-text comment body and render structured @mention tokens
    (@[Display Name](user:<id>)) as highlighted, non-editable mention spans.

    Args:
        text: Plain-text comment body, possibly containing mention tokens

    Returns:
        Safe HTML string with mentions rendered as <span class="mention"> tags
        and all other content HTML-escaped.
    """
    if not text:
        return ""

    def replace(match):
        # match.group("name") is already HTML-escaped (matched against the
        # pre-escaped text below) - escaping it again would double-encode
        # entities such as "&#x27;" into "&amp;#x27;".
        return (
            f'<span class="mention" data-user-id="{match.group("id")}">'
            f'@{match.group("name")}</span>'
        )

    escaped = escape(text)
    # Re-run the mention pattern against the escaped text: escape() does not
    # alter '@[', ']', '(', ')', ':' or digits, so token boundaries survive.
    rendered = MENTION_PATTERN.sub(replace, escaped)
    return mark_safe(rendered)


@register.filter
def safe_html(text):
    """
    Sanitize HTML content to prevent XSS attacks while preserving formatting.
    
    Args:
        text: HTML-formatted text
        
    Returns:
        Safe HTML string with dangerous elements stripped
    """
    return sanitize_html(text)


@register.filter
def trim(text):
    """
    Remove leading and trailing whitespace from text.
    
    Args:
        text: Text string to trim
        
    Returns:
        Trimmed string or empty string if input is None
    """
    if text is None:
        return ""
    return str(text).strip()


@register.filter
def release_status_badge_class(status):
    """
    Get Bootstrap badge class for release status.
    
    Args:
        status: Release status value from the database (e.g., 'Planned', 'Working', 'Closed').
                For the Release model, the internal value and display value are the same.
        
    Returns:
        Bootstrap badge class (e.g., 'bg-info', 'bg-warning', 'bg-success')
    """
    status_colors = {
        'Planned': 'bg-info',      # Blue - informational/planned
        'Working': 'bg-warning',   # Yellow - in progress
        'Closed': 'bg-success',    # Green - completed
    }
    return status_colors.get(status, 'bg-secondary')  # Default to secondary if unknown


@register.filter
def lookup(dictionary, key):
    """
    Lookup a key in a dictionary.
    
    Args:
        dictionary: Dictionary to lookup
        key: Key to lookup
        
    Returns:
        Value for the key or empty list if not found
    """
    if dictionary is None:
        return []
    return dictionary.get(key, [])

