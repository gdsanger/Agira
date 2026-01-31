"""
Item Workflow Guard

Manages state transitions for Items.
Logs status changes as activities.
"""

import logging
from typing import Optional
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from core.models import Item, ItemStatus, User
from core.services.activity import ActivityService

logger = logging.getLogger(__name__)


class ItemWorkflowGuard:
    """
    Workflow guard for Item state transitions.
    
    Logs status change activities.
    Light implementation focusing on inbox classification.
    
    Example:
        >>> guard = ItemWorkflowGuard()
        >>> guard.classify_inbox(item, 'backlog', user)
    """
    
    def __init__(self):
        self.activity_service = ActivityService()
    
    def transition(
        self,
        item: Item,
        to_status: str,
        actor: Optional[User] = None
    ) -> Item:
        """
        Transition an item to a new status.
        
        Args:
            item: The item to transition
            to_status: Target status (must be valid ItemStatus choice)
            actor: User performing the transition
            
        Returns:
            Updated item instance
            
        Raises:
            ValidationError: If status is not a valid choice
            
        Example:
            >>> guard.transition(item, ItemStatus.WORKING, user)
        """
        from_status = item.status
        
        # Validate target status is a valid choice
        if to_status not in dict(ItemStatus.choices):
            raise ValidationError(_("Invalid status: %(status)s") % {'status': to_status})
        
        # Check if already in target status
        if from_status == to_status:
            logger.info(f"Item {item.id} already in status {to_status}")
            return item
        
        # Update status
        old_status = from_status
        item.status = to_status
        item.save()
        
        # Log activity
        self.activity_service.log_status_change(
            item=item,
            from_status=old_status,
            to_status=to_status,
            actor=actor,
        )
        
        logger.info(f"Item {item.id} transitioned: {old_status} → {to_status}")
        return item
    
    def classify_inbox(
        self,
        item: Item,
        action: str,
        actor: Optional[User] = None
    ) -> Item:
        """
        Classify an inbox item using quick actions.
        
        Quick actions for inbox triage:
        - 'backlog': Move to backlog for later work
        - 'start': Start working immediately
        - 'close': Close/reject the item
        
        Args:
            item: The inbox item to classify
            action: Quick action ('backlog', 'start', 'close')
            actor: User performing the classification
            
        Returns:
            Updated item instance
            
        Raises:
            ValidationError: If item is not in Inbox or action is invalid
            
        Example:
            >>> guard.classify_inbox(item, 'backlog', user)
            >>> guard.classify_inbox(item, 'start', user)
        """
        # Verify item is in inbox
        if item.status != ItemStatus.INBOX:
            raise ValidationError(_("Item must be in Inbox status to classify"))
        
        # Map action to target status
        action_map = {
            'backlog': ItemStatus.BACKLOG,
            'start': ItemStatus.WORKING,
            'close': ItemStatus.CLOSED,
        }
        
        if action not in action_map:
            raise ValidationError(
                _("Invalid action: %(action)s. Must be one of: %(valid_actions)s") % {
                    'action': action,
                    'valid_actions': ', '.join(action_map.keys())
                }
            )
        
        target_status = action_map[action]
        
        # Perform transition
        return self.transition(item, target_status, actor)
