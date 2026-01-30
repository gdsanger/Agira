"""Custom template filters for Agira."""
from django import template
from core.utils.html_sanitization import (
    convert_markdown_to_html,
    sanitize_html,
)

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
def safe_html(text):
    """
    Sanitize HTML content to prevent XSS attacks while preserving formatting.
    
    Args:
        text: HTML-formatted text
        
    Returns:
        Safe HTML string with dangerous elements stripped
    """
    return sanitize_html(text)

