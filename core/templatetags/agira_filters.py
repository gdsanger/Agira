"""Custom template filters for Agira."""
from django import template
from django.utils.safestring import mark_safe
import markdown
import bleach

register = template.Library()

# Allowed HTML tags and attributes for sanitization
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
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'code': ['class'],
    'pre': ['class'],
    'div': ['class'],
    'span': ['class'],
}


def _sanitize_html(html):
    """
    Helper function to sanitize HTML and prevent XSS attacks.
    
    Args:
        html: HTML string to sanitize
        
    Returns:
        Safe HTML string with dangerous elements stripped
    """
    if not html:
        return ""
    
    sanitized_html = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        strip=True
    )
    
    return mark_safe(sanitized_html)


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
    if not text:
        return ""
    
    # Create a new markdown parser instance for thread safety
    md_parser = markdown.Markdown(extensions=['extra', 'fenced_code'])
    
    # Convert markdown to HTML
    html = md_parser.convert(text)
    
    # Sanitize HTML to prevent XSS attacks
    return _sanitize_html(html)


@register.filter
def safe_html(text):
    """
    Sanitize HTML content to prevent XSS attacks while preserving formatting.
    
    Args:
        text: HTML-formatted text
        
    Returns:
        Safe HTML string with dangerous elements stripped
    """
    return _sanitize_html(text)

