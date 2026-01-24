"""
Activity Service

Central service for logging activities in Agira.
Used for audit trails, activity streams, change tracking, and AI context.

Verb Convention:
    Format: <domain>.<event>
    
    Examples:
        - project.created
        - project.status_changed
        - item.created
        - item.status_changed
        - item.assigned
        - github.issue_created
        - github.mapping_synced
        - graph.mail_sent
        - ai.job_completed
"""

import logging
from typing import Optional
from django.db.models import Model, Q, QuerySet
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from core.models import Activity, User, Project, Item

logger = logging.getLogger(__name__)


class ActivityService:
    """
    Service for logging and querying activities.
    
    This service provides a simple, consistent API for logging events
    throughout the Agira system. Activities can be attached to any model
    using GenericForeignKey.
    
    Example:
        >>> from core.services.activity import ActivityService
        >>> service = ActivityService()
        >>> 
        >>> # Log a simple activity
        >>> service.log(
        ...     verb='item.created',
        ...     target=my_item,
        ...     actor=current_user,
        ...     summary='Created new bug report'
        ... )
        >>> 
        >>> # Log status change
        >>> service.log_status_change(
        ...     item=my_item,
        ...     from_status='Inbox',
        ...     to_status='Working',
        ...     actor=current_user
        ... )
    """
    
    def log(
        self,
        verb: str,
        target: Optional[Model] = None,
        actor: Optional[User] = None,
        summary: Optional[str] = None,
    ) -> Activity:
        """
        Log an activity.
        
        Args:
            verb: Activity verb following <domain>.<event> convention
                  (e.g., 'item.created', 'github.issue_created')
            target: Optional target model instance (attached via GenericForeignKey)
            actor: Optional user who performed the action
            summary: Optional human-readable summary text
            
        Returns:
            Created Activity instance
            
        Example:
            >>> service.log(
            ...     verb='item.created',
            ...     target=item,
            ...     actor=user,
            ...     summary='Created new item'
            ... )
        """
        activity_data = {
            'verb': verb,
            'actor': actor,
            'summary': summary or '',
            'created_at': timezone.now(),
        }
        
        # Set target via GenericForeignKey if provided
        if target is not None:
            content_type = ContentType.objects.get_for_model(target)
            activity_data['target_content_type'] = content_type
            activity_data['target_object_id'] = target.pk
        else:
            # For global activities without a target, we still need to set the FK fields
            # Use a dummy content type (Activity itself) to satisfy the non-null constraint
            dummy_content_type = ContentType.objects.get_for_model(Activity)
            activity_data['target_content_type'] = dummy_content_type
            activity_data['target_object_id'] = 0
        
        try:
            activity = Activity.objects.create(**activity_data)
            logger.debug(f"Activity logged: {verb} by {actor or 'System'}")
            return activity
        except Exception as e:
            logger.error(f"Failed to log activity: {verb} - {e}")
            raise
    
    def log_status_change(
        self,
        item: Model,
        from_status: str,
        to_status: str,
        actor: Optional[User] = None,
    ) -> Activity:
        """
        Log a status change for an item.
        
        Args:
            item: The item whose status changed
            from_status: Previous status
            to_status: New status
            actor: Optional user who made the change
            
        Returns:
            Created Activity instance
            
        Example:
            >>> service.log_status_change(
            ...     item=my_item,
            ...     from_status='Inbox',
            ...     to_status='Working',
            ...     actor=current_user
            ... )
        """
        # Determine verb based on item type
        model_name = item.__class__.__name__.lower()
        verb = f"{model_name}.status_changed"
        
        summary = f"Status: {from_status} → {to_status}"
        
        return self.log(
            verb=verb,
            target=item,
            actor=actor,
            summary=summary,
        )
    
    def log_created(
        self,
        target: Model,
        actor: Optional[User] = None,
        summary: Optional[str] = None,
    ) -> Activity:
        """
        Log creation of a model instance.
        
        Args:
            target: The created model instance
            actor: Optional user who created it
            summary: Optional custom summary (defaults to "Created")
            
        Returns:
            Created Activity instance
            
        Example:
            >>> service.log_created(
            ...     target=new_project,
            ...     actor=current_user
            ... )
        """
        # Determine verb based on model type
        model_name = target.__class__.__name__.lower()
        verb = f"{model_name}.created"
        
        if summary is None:
            summary = "Created"
        
        return self.log(
            verb=verb,
            target=target,
            actor=actor,
            summary=summary,
        )
    
    def latest(
        self,
        limit: int = 50,
        *,
        project: Optional[Project] = None,
        item: Optional[Item] = None,
    ) -> QuerySet[Activity]:
        """
        Get latest activities with optional filtering.
        
        Args:
            limit: Maximum number of activities to return
            project: Optional project filter (shows activities for project and its items)
            item: Optional item filter (shows activities for specific item)
            
        Returns:
            QuerySet of Activity instances ordered by created_at descending
            
        Example:
            >>> # Get latest 50 activities
            >>> activities = service.latest()
            >>> 
            >>> # Get activities for a specific item
            >>> activities = service.latest(item=my_item)
            >>> 
            >>> # Get activities for a project
            >>> activities = service.latest(project=my_project, limit=100)
        """
        queryset = Activity.objects.all()
        
        # Filter by item if provided
        if item is not None:
            content_type = ContentType.objects.get_for_model(item)
            queryset = queryset.filter(
                target_content_type=content_type,
                target_object_id=item.pk,
            )
        
        # Filter by project if provided (and no item filter)
        elif project is not None:
            # Get activities where target is the project itself
            project_ct = ContentType.objects.get_for_model(Project)
            project_filter = Q(
                target_content_type=project_ct,
                target_object_id=project.pk,
            )
            
            # Also get activities for items in this project
            item_ct = ContentType.objects.get_for_model(Item)
            item_ids = list(project.items.values_list('id', flat=True))
            if item_ids:
                item_filter = Q(
                    target_content_type=item_ct,
                    target_object_id__in=item_ids,
                )
                queryset = queryset.filter(project_filter | item_filter)
            else:
                queryset = queryset.filter(project_filter)
        
        # Order by most recent first and apply limit
        queryset = queryset.select_related('actor', 'target_content_type')
        queryset = queryset.order_by('-created_at')[:limit]
        
        return queryset
