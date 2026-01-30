"""
HTML Sanitization Utilities.

This module provides shared sanitization constants and utilities for converting
Markdown to HTML and sanitizing HTML content to prevent XSS attacks.
"""

import markdown
import bleach
from bleach.css_sanitizer import CSSSanitizer
from django.utils.safestring import mark_safe


# Allowed HTML tags for sanitization
ALLOWED_TAGS = [
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'p', 'br', 'strong', 'em', 'u', 'strike',
    'ul', 'ol', 'li',
    'blockquote', 'code', 'pre',
    'a', 'img',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'div', 'span'
]

# Allowed HTML attributes for sanitization
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


def sanitize_html(html):
    """
    Sanitize HTML content to prevent XSS attacks while preserving formatting.
    
    Args:
        html: HTML string to sanitize
        
    Returns:
        Safe HTML string with dangerous elements stripped (marked as safe)
    """
    if not html:
        return ""
    
    sanitized_html = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        css_sanitizer=css_sanitizer,
        strip=True
    )
    
    return mark_safe(sanitized_html)


def convert_markdown_to_html(text):
    """
    Convert Markdown text to sanitized HTML.
    
    This function is used for converting Markdown content (e.g., solution_description)
    to HTML for display in web pages and email templates.
    
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
    
    # Reset parser state to prevent accumulation between calls
    md_parser.reset()
    
    # Sanitize HTML to prevent XSS attacks and return as safe HTML
    return sanitize_html(html_content)


def strip_html_tags(html):
    """
    Strip all HTML tags from a string, leaving only the text content.
    
    This is useful for converting HTML to plain text (e.g., for email subjects).
    
    Args:
        html: HTML string
        
    Returns:
        Plain text string with all HTML tags removed
    """
    if not html:
        return ""
    
    # Use bleach to strip all tags
    return bleach.clean(html, tags=[], strip=True)
