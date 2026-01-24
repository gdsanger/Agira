"""
Item Workflow Guard

Manages state transitions for Items following workflow rules.
Ensures valid transitions and logs activities.
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
    
    Enforces valid state transitions and logs activities.
    Light implementation focusing on inbox classification.
    
    Example:
        >>> guard = ItemWorkflowGuard()
        >>> guard.classify_inbox(item, 'backlog', user)
    """
    
    # Define valid transitions from each status
    VALID_TRANSITIONS = {
        ItemStatus.INBOX: [ItemStatus.BACKLOG, ItemStatus.WORKING, ItemStatus.CLOSED],
        ItemStatus.BACKLOG: [ItemStatus.WORKING, ItemStatus.CLOSED],
        ItemStatus.WORKING: [ItemStatus.TESTING, ItemStatus.BACKLOG, ItemStatus.CLOSED],
        ItemStatus.TESTING: [ItemStatus.READY_FOR_RELEASE, ItemStatus.WORKING, ItemStatus.CLOSED],
        ItemStatus.READY_FOR_RELEASE: [ItemStatus.CLOSED, ItemStatus.TESTING],
        ItemStatus.CLOSED: [],  # Closed is final state
    }
    
    def __init__(self):
        self.activity_service = ActivityService()
    
    def transition(
        self,
        item: Item,
        to_status: str,
        actor: Optional[User] = None,
        skip_validation: bool = False
    ) -> Item:
        """
        Transition an item to a new status.
        
        Args:
            item: The item to transition
            to_status: Target status (must be valid ItemStatus choice)
            actor: User performing the transition
            skip_validation: If True, bypass transition validation (use with caution)
            
        Returns:
            Updated item instance
            
        Raises:
            ValidationError: If transition is not allowed
            
        Example:
            >>> guard.transition(item, ItemStatus.WORKING, user)
        """
        from_status = item.status
        
        # Validate target status is a valid choice
        if to_status not in dict(ItemStatus.choices):
            raise ValidationError(_(f"Invalid status: {to_status}"))
        
        # Check if already in target status
        if from_status == to_status:
            logger.info(f"Item {item.id} already in status {to_status}")
            return item
        
        # Validate transition is allowed (unless skipped)
        if not skip_validation:
            self._validate_transition(from_status, to_status)
        
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
            raise ValidationError(_(f"Invalid action: {action}. Must be one of: {', '.join(action_map.keys())}"))
        
        target_status = action_map[action]
        
        # Perform transition
        return self.transition(item, target_status, actor)
    
    def _validate_transition(self, from_status: str, to_status: str) -> None:
        """
        Validate that a transition is allowed.
        
        Args:
            from_status: Current status
            to_status: Target status
            
        Raises:
            ValidationError: If transition is not allowed
        """
        allowed_transitions = self.VALID_TRANSITIONS.get(from_status, [])
        
        if to_status not in allowed_transitions:
            raise ValidationError(
                _(f"Invalid transition: {from_status} → {to_status}. "
                  f"Allowed: {', '.join(allowed_transitions) or 'None'}")
            )
