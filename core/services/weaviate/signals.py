"""
Django signals for automatic Weaviate synchronization.

This module sets up signal handlers to automatically sync Django models
to Weaviate when they are saved or deleted.
"""

import logging
from django.db import transaction
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from core.services.weaviate.client import is_available
from core.services.weaviate.service import upsert_instance, delete_object
from core.services.weaviate.serializers import _get_model_type

logger = logging.getLogger(__name__)


def _safe_upsert(instance):
    """
    Safely upsert an instance to Weaviate.
    
    Catches all exceptions to prevent signal from breaking save operations.
    Uses transaction.on_commit() to ensure DB transaction completes first.
    """
    if not is_available():
        return
    
    def sync_to_weaviate():
        try:
            upsert_instance(instance)
        except Exception as e:
            # Log error but don't break the save operation
            logger.error(
                f"Failed to sync {instance.__class__.__name__} (pk={instance.pk}) to Weaviate: {e}",
                exc_info=True
            )
    
    # Only sync after DB transaction commits successfully
    try:
        transaction.on_commit(sync_to_weaviate)
    except Exception as e:
        # If not in a transaction or other error, log and continue
        logger.warning(
            f"Could not schedule Weaviate sync for {instance.__class__.__name__} (pk={instance.pk}): {e}"
        )


def _safe_delete(sender, instance):
    """
    Safely delete an instance from Weaviate.
    
    Catches all exceptions to prevent signal from breaking delete operations.
    """
    if not is_available():
        return
    
    # Get the type for this model
    obj_type = _get_model_type(instance)
    if obj_type is None:
        return
    
    try:
        delete_object(obj_type, str(instance.pk))
    except Exception as e:
        # Log error but don't break the delete operation
        logger.error(
            f"Failed to delete {sender.__name__} (pk={instance.pk}) from Weaviate: {e}",
            exc_info=True
        )


# Register signal handlers for supported models
@receiver(post_save, sender='core.Item')
def sync_item_to_weaviate(sender, instance, created, **kwargs):
    """Sync Item to Weaviate on save."""
    _safe_upsert(instance)


@receiver(post_delete, sender='core.Item')
def delete_item_from_weaviate(sender, instance, **kwargs):
    """Delete Item from Weaviate on delete."""
    _safe_delete(sender, instance)


@receiver(post_save, sender='core.ItemComment')
def sync_comment_to_weaviate(sender, instance, created, **kwargs):
    """Sync ItemComment to Weaviate on save."""
    _safe_upsert(instance)


@receiver(post_delete, sender='core.ItemComment')
def delete_comment_from_weaviate(sender, instance, **kwargs):
    """Delete ItemComment from Weaviate on delete."""
    _safe_delete(sender, instance)


@receiver(post_save, sender='core.Attachment')
def sync_attachment_to_weaviate(sender, instance, created, **kwargs):
    """Sync Attachment to Weaviate on save."""
    _safe_upsert(instance)


@receiver(post_delete, sender='core.Attachment')
def delete_attachment_from_weaviate(sender, instance, **kwargs):
    """Delete Attachment from Weaviate on delete."""
    _safe_delete(sender, instance)


@receiver(post_save, sender='core.Project')
def sync_project_to_weaviate(sender, instance, created, **kwargs):
    """Sync Project to Weaviate on save."""
    _safe_upsert(instance)


@receiver(post_delete, sender='core.Project')
def delete_project_from_weaviate(sender, instance, **kwargs):
    """Delete Project from Weaviate on delete."""
    _safe_delete(sender, instance)


@receiver(post_save, sender='core.Change')
def sync_change_to_weaviate(sender, instance, created, **kwargs):
    """Sync Change to Weaviate on save."""
    _safe_upsert(instance)


@receiver(post_delete, sender='core.Change')
def delete_change_from_weaviate(sender, instance, **kwargs):
    """Delete Change from Weaviate on delete."""
    _safe_delete(sender, instance)


@receiver(post_save, sender='core.Node')
def sync_node_to_weaviate(sender, instance, created, **kwargs):
    """Sync Node to Weaviate on save."""
    _safe_upsert(instance)


@receiver(post_delete, sender='core.Node')
def delete_node_from_weaviate(sender, instance, **kwargs):
    """Delete Node from Weaviate on delete."""
    _safe_delete(sender, instance)


@receiver(post_save, sender='core.Release')
def sync_release_to_weaviate(sender, instance, created, **kwargs):
    """Sync Release to Weaviate on save."""
    _safe_upsert(instance)


@receiver(post_delete, sender='core.Release')
def delete_release_from_weaviate(sender, instance, **kwargs):
    """Delete Release from Weaviate on delete."""
    _safe_delete(sender, instance)


@receiver(post_save, sender='core.ExternalIssueMapping')
def sync_github_issue_to_weaviate(sender, instance, created, **kwargs):
    """Sync ExternalIssueMapping (GitHub issue/PR) to Weaviate on save."""
    _safe_upsert(instance)


@receiver(post_delete, sender='core.ExternalIssueMapping')
def delete_github_issue_from_weaviate(sender, instance, **kwargs):
    """Delete ExternalIssueMapping from Weaviate on delete."""
    _safe_delete(sender, instance)
