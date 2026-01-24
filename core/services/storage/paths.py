"""
Path generation and sanitization for attachment storage
"""

import os
import re
from pathlib import Path
from typing import Union

# Configuration constants
MAX_FILENAME_LENGTH = 100  # Maximum length for sanitized filename (excluding extension)


def sanitize_filename(filename: str) -> str:
    """
    Sanitize filename to prevent directory traversal and ensure filesystem compatibility.
    
    Args:
        filename: Original filename
        
    Returns:
        Sanitized filename safe for filesystem storage
    """
    # Get basename to prevent directory traversal
    filename = os.path.basename(filename)
    
    # Split filename and extension
    name_parts = filename.rsplit('.', 1)
    name = name_parts[0]
    ext = f".{name_parts[1]}" if len(name_parts) > 1 else ""
    
    # Replace problematic characters with underscores
    # Keep alphanumeric, dash, underscore, and spaces
    name = re.sub(r'[^a-zA-Z0-9\-_ ]', '_', name)
    
    # Collapse multiple underscores/spaces
    name = re.sub(r'[_\s]+', '_', name)
    
    # Trim leading/trailing underscores
    name = name.strip('_')
    
    # Ensure not empty
    if not name:
        name = "file"
    
    # Limit length (leave room for attachment_id prefix and extension)
    if len(name) > MAX_FILENAME_LENGTH:
        name = name[:MAX_FILENAME_LENGTH]
    
    return f"{name}{ext}"


def build_attachment_path(target, attachment_id: int, original_name: str) -> str:
    """
    Build a stable, unique storage path for an attachment.
    
    Path structure:
    - projects/{project_id}/project/{attachment_id}__{safe_filename}
    - projects/{project_id}/items/{item_id}/item/{attachment_id}__{safe_filename}
    - projects/{project_id}/items/{item_id}/comments/{comment_id}/comment/{attachment_id}__{safe_filename}
    
    Args:
        target: Target object (Project, Item, or ItemComment)
        attachment_id: Unique attachment ID
        original_name: Original filename
        
    Returns:
        Relative path from AGIRA_DATA_DIR
    """
    from core.models import Project, Item, ItemComment
    
    safe_filename = sanitize_filename(original_name)
    filename_with_id = f"{attachment_id}__{safe_filename}"
    
    if isinstance(target, Project):
        # projects/{project_id}/project/{attachment_id}__{safe_filename}
        path = os.path.join(
            'projects',
            str(target.id),
            'project',
            filename_with_id
        )
    elif isinstance(target, Item):
        # projects/{project_id}/items/{item_id}/item/{attachment_id}__{safe_filename}
        path = os.path.join(
            'projects',
            str(target.project.id),
            'items',
            str(target.id),
            'item',
            filename_with_id
        )
    elif isinstance(target, ItemComment):
        # projects/{project_id}/items/{item_id}/comments/{comment_id}/comment/{attachment_id}__{safe_filename}
        path = os.path.join(
            'projects',
            str(target.item.project.id),
            'items',
            str(target.item.id),
            'comments',
            str(target.id),
            'comment',
            filename_with_id
        )
    else:
        raise ValueError(f"Unsupported target type: {type(target).__name__}")
    
    return path


def get_absolute_path(data_dir: Union[str, Path], relative_path: str) -> Path:
    """
    Convert a relative storage path to an absolute filesystem path.
    
    Args:
        data_dir: Base data directory (AGIRA_DATA_DIR)
        relative_path: Relative path from build_attachment_path
        
    Returns:
        Absolute Path object
    """
    data_dir = Path(data_dir)
    abs_path = (data_dir / relative_path).resolve()
    
    # Security check: ensure resolved path is still within data_dir
    try:
        abs_path.relative_to(data_dir.resolve())
    except ValueError:
        raise ValueError(f"Path traversal detected: {relative_path}")
    
    return abs_path
