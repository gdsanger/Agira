"""
HTML Sanitizer for Printing Framework

Provides a second layer of protection for HTML content before rendering to PDF.
Note: Quill-HTML is already sanitized on save, this is optional defense-in-depth.
"""

import logging
from typing import Optional

try:
    import bleach
    from bleach.css_sanitizer import CSSSanitizer
    BLEACH_AVAILABLE = True
except ImportError:
    BLEACH_AVAILABLE = False


logger = logging.getLogger(__name__)


# Allowlist similar to Quill rich text fields
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'u', 's', 'a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'blockquote', 'ol', 'ul', 'li', 'pre', 'code',
    'span', 'div', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'img', 'hr',
]

ALLOWED_ATTRIBUTES = {
    '*': ['class', 'id', 'style'],
    'a': ['href', 'title', 'target'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'table': ['border', 'cellpadding', 'cellspacing'],
}

ALLOWED_CSS_PROPERTIES = [
    'color', 'background-color', 'font-size', 'font-weight', 'font-style',
    'text-align', 'text-decoration', 'margin', 'padding',
]


def sanitize_html(html: str, *, strict: bool = False) -> str:
    """
    Sanitize HTML content before rendering to PDF.
    
    This provides defense-in-depth protection, even though Quill content
    is already sanitized on save.
    
    Args:
        html: HTML string to sanitize
        strict: If True, uses stricter rules (no inline styles)
        
    Returns:
        Sanitized HTML string
        
    Raises:
        ImportError: If bleach is not installed
    """
    if not BLEACH_AVAILABLE:
        logger.warning(
            "Bleach is not installed. HTML sanitization skipped. "
            "Install with: pip install bleach"
        )
        return html
    
    try:
        # Determine allowed attributes
        attrs = ALLOWED_ATTRIBUTES.copy()
        
        # Configure CSS sanitizer
        css_sanitizer = None
        if not strict:
            css_sanitizer = CSSSanitizer(allowed_css_properties=ALLOWED_CSS_PROPERTIES)
        else:
            # Remove style attribute in strict mode
            attrs['*'] = [a for a in attrs.get('*', []) if a != 'style']
        
        # Sanitize
        clean_html = bleach.clean(
            html,
            tags=ALLOWED_TAGS,
            attributes=attrs,
            css_sanitizer=css_sanitizer,
            strip=True
        )
        
        return clean_html
        
    except Exception as e:
        logger.error(f"HTML sanitization failed: {e}", exc_info=True)
        # On error, return original (already sanitized by Quill)
        return html
