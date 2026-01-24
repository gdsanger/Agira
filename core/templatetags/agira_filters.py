"""Custom template filters for Agira."""
from django import template

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
