"""
Weaviate serializers for Agira models.

This module provides serialization functions to convert Django model instances
into AgiraObject dictionaries for storage in Weaviate.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from django.db import models
from core.services.storage.service import AttachmentStorageService

logger = logging.getLogger(__name__)


def _get_model_type(instance: models.Model) -> Optional[str]:
    """
    Determine the type string for a Django model instance.
    
    Args:
        instance: Django model instance
        
    Returns:
        Type string (e.g., "item", "comment") or None if unsupported
    """
    model_name = instance.__class__.__name__
    
    # Map model names to type strings
    type_map = {
        'Item': 'item',
        'ItemComment': 'comment',
        'Attachment': 'attachment',
        'Project': 'project',
        'Change': 'change',
        'Node': 'node',
        'Release': 'release',
        'ExternalIssueMapping': 'github_issue',  # Will be refined in serializer
    }
    
    return type_map.get(model_name)


def to_agira_object(instance: models.Model, fetch_from_github: bool = False) -> Optional[Dict[str, Any]]:
    """
    Convert a Django model instance to an AgiraObject dictionary.
    
    This is the main entry point for serialization. It dispatches to
    type-specific serializers based on the model type.
    
    Args:
        instance: Django model instance to serialize
        fetch_from_github: For ExternalIssueMapping, fetch fresh data from GitHub API
        
    Returns:
        Dictionary with AgiraObject properties, or None if unsupported type
        
    Example:
        >>> from core.models import Item
        >>> item = Item.objects.get(pk=1)
        >>> obj_dict = to_agira_object(item)
        >>> print(obj_dict['title'], obj_dict['type'])
    """
    from core.models import (
        Item, ItemComment, Attachment, Project, Change,
        Node, Release, ExternalIssueMapping
    )
    
    # Dispatch to type-specific serializers
    if isinstance(instance, Item):
        return _serialize_item(instance)
    elif isinstance(instance, ItemComment):
        return _serialize_comment(instance)
    elif isinstance(instance, Attachment):
        return _serialize_attachment(instance)
    elif isinstance(instance, Project):
        return _serialize_project(instance)
    elif isinstance(instance, Change):
        return _serialize_change(instance)
    elif isinstance(instance, Node):
        return _serialize_node(instance)
    elif isinstance(instance, Release):
        return _serialize_release(instance)
    elif isinstance(instance, ExternalIssueMapping):
        return _serialize_github_issue(instance, fetch_from_github=fetch_from_github)
    else:
        logger.warning(f"Unsupported model type for Weaviate: {instance.__class__.__name__}")
        return None


def _serialize_item(item) -> Dict[str, Any]:
    """Serialize an Item instance."""
    # Build text content
    text_parts = []
    if item.description:
        text_parts.append(item.description)
    
    if item.solution_description:
        text_parts.append("\n\nSolution:\n" + item.solution_description)
    
    text = "\n".join(text_parts) if text_parts else ""
    
    # Add metadata to text
    if item.status:
        text = f"Status: {item.status}\n\n{text}"
    
    return {
        'type': 'item',
        'object_id': str(item.id),
        'project_id': str(item.project_id) if item.project_id else None,
        'org_id': str(item.organisation_id) if item.organisation_id else None,
        'title': item.title or '',
        'text': text,
        'status': item.status,
        'url': f"/items/{item.id}/",
        'source_system': 'agira',
        'created_at': item.created_at,
        'updated_at': item.updated_at,
    }


def _extract_plain_text(file_path: str, encoding: str = 'utf-8') -> Optional[str]:
    """
    Extract text from plain text files.
    
    Handles: .json, .html, .py, .xml, .cs, .txt, .yml, .yaml
    
    Args:
        file_path: Path to the file
        encoding: Text encoding (default: utf-8)
        
    Returns:
        Extracted text content, or None if extraction fails
    """
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            return f.read()
    except UnicodeDecodeError:
        # Try with latin-1 as fallback
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Could not decode file {file_path} as UTF-8 or latin-1: {e}")
            return None
    except Exception as e:
        logger.error(f"Error reading plain text file {file_path}: {e}")
        return None


def _extract_pdf_text(file_path: str) -> Optional[str]:
    """
    Extract text from PDF files using PyPDF2.
    
    Args:
        file_path: Path to the PDF file
        
    Returns:
        Extracted text content, or None if extraction fails
    """
    try:
        from PyPDF2 import PdfReader
        
        reader = PdfReader(file_path)
        text_parts = []
        
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text_parts.append(page_text)
        
        return '\n\n'.join(text_parts) if text_parts else None
        
    except ImportError:
        logger.error("PyPDF2 library not available for PDF text extraction")
        return None
    except Exception as e:
        logger.warning(f"Error extracting text from PDF {file_path}: {e}")
        return None


def _extract_docx_text(file_path: str) -> Optional[str]:
    """
    Extract text from DOCX files using python-docx.
    
    Args:
        file_path: Path to the DOCX file
        
    Returns:
        Extracted text content, or None if extraction fails
    """
    try:
        from docx import Document
        
        doc = Document(file_path)
        text_parts = []
        
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():
                text_parts.append(paragraph.text)
        
        return '\n\n'.join(text_parts) if text_parts else None
        
    except ImportError:
        logger.error("python-docx library not available for DOCX text extraction")
        return None
    except Exception as e:
        logger.warning(f"Error extracting text from DOCX {file_path}: {e}")
        return None


def _serialize_comment(comment) -> Dict[str, Any]:
    """Serialize an ItemComment instance."""
    # Build title
    title = comment.subject if comment.subject else f"Comment on {comment.item.title}"
    if len(title) > 100:
        title = title[:97] + "..."
    
    # Build text content
    text = comment.body or ''
    
    # Add metadata
    if comment.kind:
        text = f"Type: {comment.kind}\n\n{text}"
    
    return {
        'type': 'comment',
        'object_id': str(comment.id),
        'project_id': str(comment.item.project_id) if comment.item else None,
        'org_id': str(comment.item.organisation_id) if comment.item and comment.item.organisation_id else None,
        'title': title,
        'text': text,
        'status': comment.delivery_status if hasattr(comment, 'delivery_status') else None,
        'url': f"/items/{comment.item_id}/",
        'source_system': 'agira',
        'parent_object_id': str(comment.item_id) if comment.item_id else None,
        'created_at': comment.created_at,
        'updated_at': comment.created_at,  # Comments don't have updated_at
    }


def _get_attachment_text_content(attachment) -> str:
    """
    Get text content for an attachment.
    
    Extracts and returns actual file content for supported file types:
    - Plain text: .md, .json, .html, .py, .xml, .cs, .txt, .yml, .yaml
    - PDF: .pdf
    - DOCX: .docx
    
    For unsupported files, returns a description with metadata.
    
    Args:
        attachment: Attachment instance
        
    Returns:
        Text content for indexing in Weaviate
    """
    # Determine file extension
    filename = attachment.original_name or ''
    file_extension = filename.lower().split('.')[-1] if '.' in filename else ''
    
    # Define supported plain text extensions
    plain_text_extensions = {'md', 'json', 'html', 'py', 'xml', 'cs', 'txt', 'yml', 'yaml'}
    
    # Check if file type is supported for content extraction
    is_plain_text = file_extension in plain_text_extensions
    is_pdf = file_extension == 'pdf'
    is_docx = file_extension == 'docx'
    
    # If file type supports content extraction, try to extract it
    if is_plain_text or is_pdf or is_docx:
        try:
            storage_service = AttachmentStorageService()
            file_path = storage_service.get_file_path(attachment)
            
            # Extract content based on file type
            if is_plain_text:
                content = _extract_plain_text(file_path)
            elif is_pdf:
                content = _extract_pdf_text(file_path)
            else:  # is_docx
                content = _extract_docx_text(file_path)
            
            # If extraction succeeded, return the content
            if content:
                return content
            
            # If extraction returned None/empty, fall back to filename
            logger.warning(
                f"Content extraction for {filename} (attachment {attachment.id}) "
                f"returned empty result, using filename fallback"
            )
            
        except FileNotFoundError as e:
            logger.warning(
                f"File not found for attachment {attachment.id} "
                f"(path: {attachment.storage_path}): {e}"
            )
        except Exception as e:
            logger.error(f"Error extracting content from {filename} (attachment {attachment.id}): {e}")
    
    # For unsupported files or when extraction fails, use filename-based text
    text = f"Attachment: {attachment.original_name}"
    if attachment.content_type:
        text += f" ({attachment.content_type})"
    
    # Add file metadata
    if attachment.size_bytes:
        text += f"\nSize: {attachment.size_bytes} bytes"
    
    return text


def _serialize_attachment(attachment) -> Dict[str, Any]:
    """Serialize an Attachment instance."""
    # Determine parent (could be item or comment via AttachmentLink)
    parent_object_id = None
    project_id = None
    org_id = None
    
    # Try to get parent from first link
    if hasattr(attachment, 'links'):
        first_link = attachment.links.first()
        if first_link:
            parent_object_id = str(first_link.target_object_id)
            
            # Try to get project/org from parent
            # For Project attachments, the target IS the project
            target = first_link.target
            if target:
                # If target is a Project, use its ID as project_id
                if target.__class__.__name__ == 'Project':
                    project_id = str(target.id)
                # Otherwise, check if target has project_id attribute (Item, ItemComment, Change, etc.)
                elif hasattr(target, 'project_id') and target.project_id:
                    project_id = str(target.project_id)
                
                # Get org_id from target
                if hasattr(target, 'organisation_id') and target.organisation_id:
                    org_id = str(target.organisation_id)
    
    # Build text content
    # For markdown files, read the actual file content
    text = _get_attachment_text_content(attachment)
    
    return {
        'type': 'attachment',
        'object_id': str(attachment.id),
        'project_id': project_id,
        'org_id': org_id,
        'title': attachment.original_name or 'Unnamed Attachment',
        'text': text,
        'url': f"/attachments/{attachment.id}/",
        'source_system': 'agira',
        'parent_object_id': parent_object_id,
        'mime_type': attachment.content_type or None,
        'size_bytes': int(attachment.size_bytes) if attachment.size_bytes else None,
        'sha256': attachment.sha256 or None,
        'created_at': attachment.created_at,
        'updated_at': attachment.created_at,  # Attachments don't have updated_at
    }


def _serialize_project(project) -> Dict[str, Any]:
    """Serialize a Project instance."""
    text = project.description or ''
    
    # Add metadata
    if project.status:
        text = f"Status: {project.status}\n\n{text}"
    
    return {
        'type': 'project',
        'object_id': str(project.id),
        'project_id': str(project.id),  # Project references itself
        'title': project.name or '',
        'text': text,
        'status': project.status,
        'url': f"/projects/{project.id}/",
        'source_system': 'agira',
        'created_at': datetime.now(timezone.utc),  # Projects don't have created_at
        'updated_at': datetime.now(timezone.utc),
    }


def _serialize_change(change) -> Dict[str, Any]:
    """Serialize a Change instance."""
    # Build text content
    text = change.description or ''
    
    # Add metadata
    metadata_parts = []
    if change.status:
        metadata_parts.append(f"Status: {change.status}")
    if change.risk:
        metadata_parts.append(f"Risk: {change.risk}")
    
    if metadata_parts:
        text = "\n".join(metadata_parts) + "\n\n" + text
    
    # Add additional sections
    if change.rollback_plan:
        text += f"\n\nRollback Plan:\n{change.rollback_plan}"
    
    return {
        'type': 'change',
        'object_id': str(change.id),
        'project_id': str(change.project_id) if change.project_id else None,
        'title': change.title or '',
        'text': text,
        'status': change.status,
        'url': f"/changes/{change.id}/",
        'source_system': 'agira',
        'created_at': change.created_at,
        'updated_at': change.updated_at,
    }


def _serialize_node(node) -> Dict[str, Any]:
    """Serialize a Node instance."""
    text = node.description or ''
    
    # Add metadata
    if node.type:
        text = f"Type: {node.type}\n\n{text}"
    
    return {
        'type': 'node',
        'object_id': str(node.id),
        'project_id': str(node.project_id) if node.project_id else None,
        'title': node.name or '',
        'text': text,
        'url': f"/nodes/{node.id}/",
        'source_system': 'agira',
        'parent_object_id': str(node.parent_node_id) if node.parent_node_id else None,
        'created_at': datetime.now(timezone.utc),  # Nodes don't have created_at
        'updated_at': datetime.now(timezone.utc),
    }


def _serialize_release(release) -> Dict[str, Any]:
    """Serialize a Release instance."""
    # Build text content
    text_parts = []
    if release.risk_description:
        text_parts.append(f"Risk Description:\n{release.risk_description}")
    if release.risk_mitigation:
        text_parts.append(f"\nRisk Mitigation:\n{release.risk_mitigation}")
    if release.rescue_measure:
        text_parts.append(f"\nRescue Measure:\n{release.rescue_measure}")
    
    text = "\n".join(text_parts) if text_parts else ""
    
    # Add metadata
    metadata_parts = []
    if release.version:
        metadata_parts.append(f"Version: {release.version}")
    if release.status:
        metadata_parts.append(f"Status: {release.status}")
    if release.risk:
        metadata_parts.append(f"Risk: {release.risk}")
    
    if metadata_parts:
        text = "\n".join(metadata_parts) + "\n\n" + text
    
    return {
        'type': 'release',
        'object_id': str(release.id),
        'project_id': str(release.project_id) if release.project_id else None,
        'title': release.name or release.version or '',
        'text': text,
        'status': release.status,
        'url': f"/releases/{release.id}/",
        'source_system': 'agira',
        'created_at': release.update_date or datetime.now(timezone.utc),
        'updated_at': release.update_date or datetime.now(timezone.utc),
    }


def _serialize_github_issue(mapping, fetch_from_github: bool = False) -> Dict[str, Any]:
    """
    Serialize an ExternalIssueMapping instance (GitHub issue/PR).
    
    Args:
        mapping: ExternalIssueMapping instance
        fetch_from_github: If True, fetch the actual issue/PR data from GitHub API
        
    Returns:
        Dictionary with AgiraObject properties
    """
    # Determine if it's an issue or PR
    obj_type = 'github_pr' if mapping.kind == 'PR' else 'github_issue'
    
    # Build external key from item's GitHub info
    external_key = None
    project = mapping.item.project if mapping.item else None
    if project and project.github_owner and project.github_repo:
        external_key = f"{project.github_owner}/{project.github_repo}#{mapping.number}"
    
    # Default values from local Item data
    title = mapping.item.title if mapping.item else f"GitHub {mapping.kind} #{mapping.number}"
    text = mapping.item.description if mapping.item else ""
    state = mapping.state
    created_at = None
    updated_at = mapping.last_synced_at
    
    # Optionally fetch from GitHub API for richer data
    if fetch_from_github and project and project.github_owner and project.github_repo:
        try:
            github_data = _fetch_github_issue_data(
                owner=project.github_owner,
                repo=project.github_repo,
                number=mapping.number,
                kind=mapping.kind
            )
            
            if github_data:
                # Use GitHub data if available
                title = github_data.get('title', title)
                body = github_data.get('body', '')
                state = github_data.get('state', state)
                
                # Build richer text content
                text_parts = []
                if body:
                    text_parts.append(body)
                
                # Add labels if present
                labels = github_data.get('labels', [])
                if labels:
                    # Filter out labels without names
                    label_names = [label['name'] for label in labels if isinstance(label, dict) and label.get('name')]
                    if label_names:
                        text_parts.append(f"\n\nLabels: {', '.join(label_names)}")
                
                text = '\n'.join(text_parts) if text_parts else ''
                
                # Parse timestamps - GitHub uses ISO format with 'Z' suffix
                if github_data.get('created_at'):
                    try:
                        # Replace 'Z' with '+00:00' for proper ISO 8601 parsing
                        created_at = datetime.fromisoformat(github_data['created_at'].replace('Z', '+00:00'))
                    except (ValueError, AttributeError) as e:
                        logger.debug(f"Could not parse created_at timestamp: {e}")
                        pass
                
                if github_data.get('updated_at'):
                    try:
                        # Replace 'Z' with '+00:00' for proper ISO 8601 parsing
                        updated_at = datetime.fromisoformat(github_data['updated_at'].replace('Z', '+00:00'))
                    except (ValueError, AttributeError) as e:
                        logger.debug(f"Could not parse updated_at timestamp: {e}")
                        pass
                
                logger.info(f"Fetched GitHub {mapping.kind} data for #{mapping.number}: {title}")
        except Exception as e:
            # Log error but continue with local data
            logger.warning(f"Failed to fetch GitHub data for {mapping.kind} #{mapping.number}: {e}")
    
    # Add state prefix to text
    if state:
        text = f"State: {state}\n\n{text}"
    
    return {
        'type': obj_type,
        'object_id': str(mapping.id),
        'project_id': str(mapping.item.project_id) if mapping.item and mapping.item.project_id else None,
        'org_id': str(mapping.item.organisation_id) if mapping.item and mapping.item.organisation_id else None,
        'title': title,
        'text': text,
        'status': state,
        'url': mapping.html_url or f"/items/{mapping.item_id}/",
        'source_system': 'github',
        'external_key': external_key,
        'created_at': created_at or datetime.now(timezone.utc),
        'updated_at': updated_at or datetime.now(timezone.utc),
    }


def _fetch_github_issue_data(owner: str, repo: str, number: int, kind: str) -> Optional[Dict[str, Any]]:
    """
    Fetch issue or PR data from GitHub API.
    
    Args:
        owner: Repository owner
        repo: Repository name
        number: Issue/PR number
        kind: 'Issue' or 'PR'
        
    Returns:
        GitHub issue/PR data dictionary, or None if unavailable
    """
    try:
        from core.services.github.service import GitHubService
        
        github_service = GitHubService()
        
        # Check if GitHub is available
        if not github_service.is_enabled() or not github_service.is_configured():
            logger.debug("GitHub service not available, skipping fetch")
            return None
        
        client = github_service._get_client()
        
        # Fetch issue or PR data
        if kind == 'PR':
            data = client.get_pr(owner, repo, number)
        else:
            data = client.get_issue(owner, repo, number)
        
        return data
        
    except Exception as e:
        logger.warning(f"Failed to fetch GitHub {kind} {owner}/{repo}#{number}: {e}")
        return None
