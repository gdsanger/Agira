"""
Weaviate serializers for Agira models.

This module provides serialization functions to convert Django model instances
into AgiraObject dictionaries for storage in Weaviate.
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime
from django.db import models

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


def to_agira_object(instance: models.Model) -> Optional[Dict[str, Any]]:
    """
    Convert a Django model instance to an AgiraObject dictionary.
    
    This is the main entry point for serialization. It dispatches to
    type-specific serializers based on the model type.
    
    Args:
        instance: Django model instance to serialize
        
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
        return _serialize_github_issue(instance)
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
            if hasattr(first_link.target, 'project_id'):
                project_id = str(first_link.target.project_id)
            if hasattr(first_link.target, 'organisation_id') and first_link.target.organisation_id:
                org_id = str(first_link.target.organisation_id)
    
    # Build text content
    text = f"Attachment: {attachment.original_name}"
    if attachment.content_type:
        text += f" ({attachment.content_type})"
    
    # Add file metadata
    if attachment.size_bytes:
        text += f"\nSize: {attachment.size_bytes} bytes"
    
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
        'created_at': datetime.now(),  # Projects don't have created_at
        'updated_at': datetime.now(),
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
        'created_at': datetime.now(),  # Nodes don't have created_at
        'updated_at': datetime.now(),
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
        'created_at': release.update_date or datetime.now(),
        'updated_at': release.update_date or datetime.now(),
    }


def _serialize_github_issue(mapping) -> Dict[str, Any]:
    """Serialize an ExternalIssueMapping instance (GitHub issue/PR)."""
    # Determine if it's an issue or PR
    obj_type = 'github_pr' if mapping.kind == 'PR' else 'github_issue'
    
    # Build external key from item's GitHub info
    external_key = None
    if mapping.item and mapping.item.project:
        project = mapping.item.project
        if project.github_owner and project.github_repo:
            external_key = f"{project.github_owner}/{project.github_repo}#{mapping.number}"
    
    # Build title and text from the mapped item
    title = mapping.item.title if mapping.item else f"GitHub {mapping.kind} #{mapping.number}"
    text = mapping.item.description if mapping.item else ""
    
    # Add GitHub state
    if mapping.state:
        text = f"State: {mapping.state}\n\n{text}"
    
    return {
        'type': obj_type,
        'object_id': str(mapping.id),
        'project_id': str(mapping.item.project_id) if mapping.item and mapping.item.project_id else None,
        'org_id': str(mapping.item.organisation_id) if mapping.item and mapping.item.organisation_id else None,
        'title': title,
        'text': text,
        'status': mapping.state,
        'url': mapping.html_url or f"/items/{mapping.item_id}/",
        'source_system': 'github',
        'external_key': external_key,
        'created_at': datetime.now(),  # ExternalIssueMapping doesn't have created_at
        'updated_at': mapping.last_synced_at,
    }
