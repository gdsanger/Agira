# Activity Service - Quick Start Example

This example demonstrates how to use the Activity Service in practice.

## Basic Usage

```python
from core.services.activity import ActivityService

# Initialize the service
service = ActivityService()

# Log a simple activity
activity = service.log(
    verb='item.created',
    target=my_item,
    actor=current_user,
    summary='Created new bug report'
)
```

## Integration Example: Item Status Update

Here's a real-world example of integrating the Activity Service into an item update view:

```python
# In your service or view
from core.services.activity import ActivityService
from core.models import Item, ItemStatus

def update_item_status(item_id, new_status, user):
    """Update item status and log the activity."""
    item = Item.objects.get(pk=item_id)
    old_status = item.get_status_display()
    
    # Update the item
    item.status = new_status
    item.save()
    
    # Log the status change
    service = ActivityService()
    service.log_status_change(
        item=item,
        from_status=old_status,
        to_status=item.get_status_display(),
        actor=user,
    )
    
    return item
```

## Integration Example: GitHub Service

Here's how the Activity Service integrates with the GitHub service:

```python
# In core/services/github/service.py
from core.services.activity import ActivityService

class GitHubService:
    def create_issue_for_item(self, item, actor, title=None, body=None):
        # ... create GitHub issue ...
        
        # Log the activity
        ActivityService().log(
            verb='github.issue_created',
            target=item,
            actor=actor,
            summary=f'Created GitHub issue #{number}'
        )
        
        return mapping
    
    def sync_mapping(self, mapping):
        # ... sync with GitHub ...
        
        # Log the sync
        ActivityService().log(
            verb='github.mapping_synced',
            target=mapping.item,
            summary=f'Synced GitHub {mapping.kind} #{mapping.number}'
        )
        
        return mapping
```

## Dashboard Example

Display recent activities in a dashboard:

```python
from core.services.activity import ActivityService

def project_dashboard_view(request, project_id):
    project = Project.objects.get(pk=project_id)
    
    # Get recent activities for this project
    service = ActivityService()
    recent_activities = service.latest(project=project, limit=20)
    
    context = {
        'project': project,
        'activities': recent_activities,
    }
    return render(request, 'dashboard.html', context)
```

## Template Example

Display activities in a template:

```django
{% for activity in activities %}
<div class="activity-item">
    <span class="timestamp">{{ activity.created_at|timesince }} ago</span>
    <span class="actor">
        {% if activity.actor %}
            {{ activity.actor.name }}
        {% else %}
            System
        {% endif %}
    </span>
    <span class="verb">{{ activity.verb }}</span>
    <span class="summary">{{ activity.summary }}</span>
</div>
{% endfor %}
```

## Testing Example

Test your activity logging:

```python
from django.test import TestCase
from core.services.activity import ActivityService
from core.models import Activity

class MyServiceTestCase(TestCase):
    def test_create_item_logs_activity(self):
        """Test that creating an item logs an activity."""
        # Create an item
        item = create_test_item()
        
        # Verify activity was logged
        activities = Activity.objects.filter(
            verb='item.created',
            target_object_id=item.pk
        )
        self.assertEqual(activities.count(), 1)
        
        activity = activities.first()
        self.assertEqual(activity.summary, 'Created')
```

## Common Verbs

Use these consistent verb patterns:

- `project.created` - Project created
- `project.status_changed` - Project status changed
- `item.created` - Item created
- `item.status_changed` - Item status changed
- `item.assigned` - Item assigned to user
- `github.issue_created` - GitHub issue created
- `github.mapping_synced` - GitHub mapping synchronized
- `github.pr_merged` - GitHub PR merged
- `graph.mail_sent` - Email sent via Microsoft Graph
- `ai.job_completed` - AI job completed
- `ai.job_failed` - AI job failed

## Best Practices

1. **Log from Services, Not Views**: Keep activity logging in service layers
2. **Be Descriptive**: Use clear, actionable summaries
3. **Include Actor When Available**: Track who performed actions
4. **Use Consistent Verbs**: Follow the `<domain>.<event>` convention
5. **Don't Log Everything**: Focus on meaningful, auditable events
6. **Handle Errors Gracefully**: Decide if activity logging is critical for your use case

## Performance Tips

1. The `latest()` query helper uses `select_related()` for performance
2. Activities are indexed by `created_at` for efficient date-based queries
3. Consider archiving old activities if the table grows very large
4. Use `limit` parameter to control result size

## Admin Interface

View and filter activities at `/admin/core/activity/`:
- Filter by verb, actor, or date
- Search by summary or verb
- Browse by date hierarchy
- Read-only interface (activities are system-generated)
