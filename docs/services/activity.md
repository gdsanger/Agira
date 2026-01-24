# Activity Service

The Activity Service provides centralized activity logging for audit trails, activity streams, change tracking, and AI context in Agira.

## Purpose

The Activity Service is designed to:
- **Log Events Centrally**: Maintain a single source of truth for all system activities
- **Support Audit Trails**: Track who did what and when for compliance and debugging
- **Enable Activity Streams**: Power dashboards and user-facing activity feeds
- **Provide AI Context**: Give AI systems visibility into what has happened in the system
- **Track Changes**: Monitor status changes and important events

## Core Concepts

### Activities
Each `Activity` record represents a single event in the system. Activities have:
- **verb**: A string following the `<domain>.<event>` convention (e.g., `item.created`)
- **target**: An optional reference to any model instance via GenericForeignKey
- **actor**: An optional reference to the User who performed the action
- **summary**: A human-readable description of what happened
- **created_at**: Timestamp when the activity was logged

### Verb Convention

Verbs follow a consistent `<domain>.<event>` pattern:

**Format**: `<domain>.<event>`

**Examples**:
- `project.created` - A new project was created
- `project.status_changed` - Project status changed
- `item.created` - A new item was created
- `item.status_changed` - Item status changed
- `item.assigned` - Item was assigned to someone
- `github.issue_created` - GitHub issue was created
- `github.mapping_synced` - GitHub mapping was synchronized
- `graph.mail_sent` - Email was sent via Microsoft Graph
- `ai.job_completed` - AI job finished processing

This convention keeps verbs organized and searchable while remaining flexible for future events.

## API Reference

### ActivityService.log()

Log a general activity.

```python
from core.services.activity import ActivityService

service = ActivityService()

# Log with all parameters
activity = service.log(
    verb='item.created',
    target=my_item,
    actor=current_user,
    summary='Created new bug report'
)

# Log without actor (system action)
activity = service.log(
    verb='ai.job_completed',
    target=my_item,
    summary='AI analysis completed'
)

# Log without target (global event)
activity = service.log(
    verb='system.maintenance',
    actor=admin_user,
    summary='System maintenance performed'
)
```

**Parameters**:
- `verb` (str, required): Activity verb following `<domain>.<event>` convention
- `target` (Model, optional): Target model instance
- `actor` (User, optional): User who performed the action
- `summary` (str, optional): Human-readable summary

**Returns**: Created `Activity` instance

### ActivityService.log_status_change()

Helper method for logging status changes.

```python
# Log item status change
activity = service.log_status_change(
    item=my_item,
    from_status='Inbox',
    to_status='Working',
    actor=current_user
)
```

**Parameters**:
- `item` (Model, required): The item whose status changed
- `from_status` (str, required): Previous status
- `to_status` (str, required): New status
- `actor` (User, optional): User who made the change

**Returns**: Created `Activity` instance

**Behavior**:
- Automatically determines verb based on model type (e.g., `item.status_changed`, `project.status_changed`)
- Formats summary as `Status: {from} → {to}`

### ActivityService.log_created()

Helper method for logging entity creation.

```python
# Log project creation
activity = service.log_created(
    target=new_project,
    actor=current_user
)

# Log with custom summary
activity = service.log_created(
    target=new_item,
    actor=current_user,
    summary='Created from GitHub issue #42'
)
```

**Parameters**:
- `target` (Model, required): The created model instance
- `actor` (User, optional): User who created it
- `summary` (str, optional): Custom summary (defaults to "Created")

**Returns**: Created `Activity` instance

**Behavior**:
- Automatically determines verb based on model type (e.g., `item.created`, `project.created`)
- Default summary is "Created" if not specified

### ActivityService.latest()

Query helper for retrieving recent activities.

```python
# Get latest 50 activities
activities = service.latest()

# Get latest 100 activities
activities = service.latest(limit=100)

# Get activities for a specific item
activities = service.latest(item=my_item)

# Get activities for a project (includes project and all its items)
activities = service.latest(project=my_project, limit=100)

# Iterate through results
for activity in activities:
    print(f"{activity.created_at}: {activity.verb} - {activity.summary}")
```

**Parameters**:
- `limit` (int, optional): Maximum number of activities to return (default: 50)
- `project` (Project, optional): Filter to activities for this project and its items
- `item` (Item, optional): Filter to activities for this specific item

**Returns**: Django QuerySet of `Activity` instances ordered by `created_at` descending

## Usage Examples

### Example 1: Item Status Change

When an item's status changes:

```python
from core.services.activity import ActivityService

def update_item_status(item, new_status, user):
    old_status = item.status
    item.status = new_status
    item.save()
    
    # Log the status change
    service = ActivityService()
    service.log_status_change(
        item=item,
        from_status=old_status,
        to_status=new_status,
        actor=user
    )
```

### Example 2: GitHub Synchronization

When syncing with GitHub:

```python
from core.services.activity import ActivityService

def sync_github_issue(item, github_issue, user):
    # ... sync logic ...
    
    # Log the sync
    service = ActivityService()
    service.log(
        verb='github.mapping_synced',
        target=item,
        actor=user,
        summary=f'Synced with GitHub issue #{github_issue.number}'
    )
```

### Example 3: Creating Items from Services

When a service creates an item:

```python
from core.services.activity import ActivityService

def create_item_from_github(project, github_issue, user):
    item = Item.objects.create(
        project=project,
        title=github_issue.title,
        description=github_issue.body,
        type=item_type,
    )
    
    # Log both creation and GitHub association
    service = ActivityService()
    
    # Log item creation
    service.log_created(
        target=item,
        actor=user,
        summary=f'Created from GitHub issue #{github_issue.number}'
    )
    
    # Log GitHub mapping
    service.log(
        verb='github.issue_created',
        target=item,
        actor=user,
        summary=f'Created GitHub issue #{github_issue.number}'
    )
    
    return item
```

### Example 4: Dashboard Activity Feed

Display recent project activities:

```python
from core.services.activity import ActivityService

def get_project_activity_feed(project):
    service = ActivityService()
    recent_activities = service.latest(project=project, limit=20)
    
    return [
        {
            'timestamp': act.created_at,
            'actor': act.actor.name if act.actor else 'System',
            'verb': act.verb,
            'summary': act.summary,
        }
        for act in recent_activities
    ]
```

## Integration Guidelines

### Services Should Log, UI Should Not

**DO** call ActivityService from service layers:
```python
# In core/services/github/service.py
from core.services.activity import ActivityService

def create_issue_for_item(self, item, actor):
    # ... create GitHub issue ...
    
    ActivityService().log(
        verb='github.issue_created',
        target=item,
        actor=actor,
        summary=f'Created GitHub issue #{number}'
    )
```

**DON'T** call ActivityService directly from views or templates:
```python
# ❌ Avoid this
def item_view(request, item_id):
    item = get_object_or_404(Item, pk=item_id)
    ActivityService().log(...)  # Don't do this in views
```

### When to Log Activities

**DO log**:
- Entity creation (items, projects, etc.)
- Status changes
- External integrations (GitHub, email, etc.)
- Important system events
- AI/automated actions

**DON'T log**:
- User logins/logouts (use Django's auth logging)
- Every single database read
- Trivial UI interactions
- Temporary/draft changes

### Error Handling

The service will raise exceptions if logging fails. Decide if you want to:

1. **Let it fail** (recommended for critical events):
```python
activity = service.log(verb='item.created', target=item)  # Will raise on error
```

2. **Catch and log** (for non-critical events):
```python
try:
    service.log(verb='github.sync_attempted', target=item)
except Exception as e:
    logger.warning(f"Failed to log activity: {e}")
```

## Admin Interface

Activities can be viewed in the Django Admin interface at `/admin/core/activity/`.

Features:
- **List View**: Shows created_at, verb, actor, summary, target type and ID
- **Filtering**: Filter by verb, actor, or date
- **Search**: Search by summary or verb
- **Date Hierarchy**: Browse by date
- **Read-Only**: Activities cannot be manually created or edited (system-generated only)

## Future Enhancements

Future versions may include:
- Event streaming via Django signals
- Webhook notifications for activities
- Activity aggregation and statistics
- Real-time activity feeds via WebSocket
- Activity retention policies

For now, the service is intentionally simple and explicit to maintain clarity and reliability.
