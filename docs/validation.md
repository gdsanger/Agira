# Agira Model Validation Documentation

## Overview

This document describes all validation rules and constraints implemented in the Agira data model. Validations are implemented at multiple levels:

1. **Database Constraints** - Enforced by the database itself
2. **Model-level Validation** - Enforced in `clean()` methods
3. **Field-level Validation** - Enforced by Django field validators

## Database Constraints

### Unique Constraints

#### UserOrganisation
```python
models.UniqueConstraint(fields=['user', 'organisation'], name='unique_user_organisation')
```
- **Purpose**: Prevents duplicate user-organisation relationships
- **Impact**: A user can only be associated with an organisation once

#### UserOrganisation (Partial Unique)
```python
models.UniqueConstraint(
    fields=['user'],
    condition=models.Q(is_primary=True),
    name='unique_primary_organisation_per_user'
)
```
- **Purpose**: Ensures only one primary organisation per user
- **Impact**: A user can mark only one organisation as primary
- **Type**: Partial unique index (only applies when is_primary=True)

#### ChangeApproval
```python
models.UniqueConstraint(fields=['change', 'approver'], name='unique_change_approver')
```
- **Purpose**: Prevents duplicate approvals
- **Impact**: Each user can only approve a change once

#### ItemRelation
```python
models.UniqueConstraint(
    fields=['from_item', 'to_item', 'relation_type'],
    name='unique_item_relation'
)
```
- **Purpose**: Prevents duplicate relationships between items
- **Impact**: The same relationship between two items can only exist once

#### AttachmentLink
```python
models.UniqueConstraint(
    fields=['attachment', 'target_content_type', 'target_object_id'],
    name='unique_attachment_target'
)
```
- **Purpose**: Prevents attaching the same file to the same target multiple times
- **Impact**: An attachment can only be linked once to each specific target

#### ExternalIssueMapping
```python
github_id = models.BigIntegerField(unique=True)
```
- **Purpose**: Ensures each GitHub issue/PR is mapped only once
- **Impact**: Cannot create duplicate mappings for the same GitHub issue

### Indexes

#### ItemRelation
```python
models.Index(fields=['from_item', 'to_item'])
```
- **Purpose**: Optimize queries for item relationships
- **Impact**: Faster lookups when finding related items

## Model-Level Validation

Model-level validations are implemented in the `clean()` method and called automatically before saving when using `full_clean()` or the admin interface.

### Change Model

#### Release Project Validation
```python
if self.release and self.release.project != self.project:
    raise ValidationError({
        'release': _('Release must belong to the same project as the change.')
    })
```
- **Purpose**: Ensures release and change are from the same project
- **Impact**: Cannot assign a change to a release from a different project

### Item Model

The Item model has the most comprehensive validation rules:

#### Parent Item Project Validation (REMOVED as of Feb 2026)
**Historical Note**: This validation was removed as per issue #306 to allow cross-project parent-child relationships.
The validation previously ensured parent items belonged to the same project, but was removed to provide
more flexibility when managing large numbers of items (200+).

Current behavior:
- Parent items can be from any project
- Only validation: Parent item status must not be "closed" and cannot be the item itself
- Validation enforced in view layer (`item_update_parent` in `views.py`)

#### Solution Release Project Validation
```python
if self.solution_release and self.solution_release.project != self.project:
    errors['solution_release'] = _('Solution release must belong to the same project.')
```
- **Purpose**: Ensures release and item are from the same project
- **Impact**: Cannot assign an item to a release from a different project

#### Organisation Client Validation
```python
if self.organisation:
    project_clients = list(self.project.clients.all())
    if project_clients and self.organisation not in project_clients:
        errors['organisation'] = _('Organisation must be one of the project clients.')
```
- **Purpose**: Enforces that if a project has clients, items can only be assigned to those clients
- **Impact**: 
  - If project.clients is empty, any organisation can be assigned
  - If project.clients is not empty, only those organisations can be assigned
- **Business Rule**: Ensures items are properly scoped to authorized clients

#### Requester Organisation Membership Validation
```python
if self.requester and self.organisation:
    if not UserOrganisation.objects.filter(
        user=self.requester,
        organisation=self.organisation
    ).exists():
        errors['requester'] = _(
            'Requester must be a member of the selected organisation.'
        )
```
- **Purpose**: Ensures requester actually belongs to the organisation
- **Impact**: Cannot assign a requester from outside the item's organisation
- **Business Rule**: Maintains data integrity for customer/requester relationships

#### Item Save Override
```python
def save(self, *args, **kwargs):
    self.full_clean()
    super().save(*args, **kwargs)
```
- **Purpose**: Ensures validation runs even when saving outside the admin
- **Impact**: All validation rules are enforced programmatically

## Many-to-Many Validation Notes

Some validations cannot be enforced in `clean()` for M2M relationships because M2M fields are saved after the object. These would need to be implemented using signals or admin form validation:

### Item.nodes Validation (Not Yet Implemented)
**Expected Rule**: All nodes must belong to the same project as the item
```python
# This would need to be implemented in a form or signal
for node in item.nodes.all():
    if node.project != item.project:
        raise ValidationError('Node must belong to the same project as the item')
```

### Change.items Validation (Not Yet Implemented)
**Expected Rule**: All items must belong to the same project as the change
```python
# This would need to be implemented in a form or signal
for item in change.items.all():
    if item.project != change.project:
        raise ValidationError('All items must belong to the same project as the change')
```

## Field-Level Validation

### Required Fields

All models have certain required fields enforced by Django:

- **blank=False** (default): Field must be provided in forms
- **null=False** (default): Field cannot be NULL in database

### Email Validation

Email fields use Django's EmailField validation:
- `User.email`
- `ItemComment.external_from`
- `ItemComment.external_to`

### URL Validation

URL fields use Django's URLField validation:
- `ExternalIssueMapping.html_url`
- `WeaviateConfiguration.url`
- `ZammadConfiguration.url`

### Choice Validation

All fields using TextChoices are automatically validated to ensure only valid choices are selected:
- `User.role` (User, Agent, Approver)
- `Project.status` (New, Working, Canceled, Finished)
- `Node.type` (Project, View, Entity, Class, Action, Report, Other)
- `Release.status` (Planned, Working, Closed)
- `Release.risk` (Low, Normal, High, VeryHigh)
- `Change.status` (Draft, Planned, InProgress, Deployed, RolledBack, Canceled)
- `Change.risk` (Low, Normal, High, VeryHigh)
- `ChangeApproval.status` (Pending, Approved, Rejected)
- `Item.status` (Inbox, Backlog, Working, Testing, ReadyForRelease, Closed)
- `ItemRelation.relation_type` (DependOn, Similar, Related)
- `ExternalIssueMapping.kind` (Issue, PR)
- `ItemComment.visibility` (Public, Internal)
- `ItemComment.kind` (Note, Comment, EmailIn, EmailOut)
- `ItemComment.delivery_status` (Draft, Queued, Sent, Failed)
- `AttachmentLink.role` (ProjectFile, ItemFile, CommentAttachment)

## Singleton Model Validation

Configuration models enforce singleton behavior:

```python
def save(self, *args, **kwargs):
    self.pk = 1
    super().save(*args, **kwargs)

def delete(self, *args, **kwargs):
    pass  # Prevents deletion
```

- **Purpose**: Ensures only one configuration instance exists per type
- **Impact**: 
  - All saves update the same record (pk=1)
  - Cannot delete configuration records

## User Manager Validation

### Create User
```python
if not username:
    raise ValueError(_('The Username must be set'))
if not email:
    raise ValueError(_('The Email must be set'))
```

### Create Superuser
```python
extra_fields.setdefault('is_staff', True)
extra_fields.setdefault('is_superuser', True)
extra_fields.setdefault('active', True)

if extra_fields.get('is_staff') is not True:
    raise ValueError(_('Superuser must have is_staff=True.'))
if extra_fields.get('is_superuser') is not True:
    raise ValueError(_('Superuser must have is_superuser=True.'))
```

## Auto-Computed Fields

### Attachment.sha256
```python
def save(self, *args, **kwargs):
    if self.file and not self.sha256:
        self.file.seek(0)
        file_hash = hashlib.sha256()
        for chunk in self.file.chunks():
            file_hash.update(chunk)
        self.sha256 = file_hash.hexdigest()
    super().save(*args, **kwargs)
```
- **Purpose**: Automatically computes SHA-256 hash of uploaded files
- **Impact**: File integrity can be verified

### Node.matchkey
```python
@property
def matchkey(self):
    return f"{self.type}:{self.name}"
```
- **Purpose**: Provides a computed identifier combining type and name
- **Impact**: Cannot be directly set, always reflects current type and name

## Future Enhancements

Validations that should be considered for future implementation:

1. **Cycle Detection** for ItemRelation when relation_type is "DependOn"
   - Prevent circular dependencies

2. **M2M Validation** for Item.nodes and Change.items
   - Enforce same-project constraint

3. **Date Range Validation** for Change
   - Ensure planned_start <= planned_end
   - Ensure executed_at is within reasonable bounds

4. **Approval Requirement Validation**
   - Ensure required approvals are obtained before deploying a change

5. **File Size Limits** for Attachment
   - Prevent extremely large file uploads

6. **GitHub Integration Validation**
   - Verify GitHub repository exists when set
   - Validate GitHub webhook configuration

## Status Transition (Removed)

**Note**: As of January 2026, status transition validation has been removed from the Item model. 
Items can now transition between any valid status values without restriction. The ItemWorkflowGuard 
still logs status changes but no longer enforces transition rules.

Previously, there was a VALID_TRANSITIONS matrix that restricted which status changes were allowed 
(e.g., preventing direct transitions from INBOX to TESTING). This restriction has been removed to 
provide more flexibility in workflow management.

## Testing Validation Rules

To test validation rules:

1. Use Django Admin to trigger form validation
2. Use Django shell to test programmatic validation:
```python
from core.models import Item, Project
project = Project.objects.first()
item = Item(project=project, title="Test")
item.full_clean()  # Triggers all validation
```

3. Write unit tests for complex validation scenarios
4. Test database constraints by attempting to create invalid data

## Validation Error Messages

All validation errors use Django's translation framework (`gettext_lazy`) to support internationalization. Error messages are clear and indicate:
- Which field has the error
- What the constraint is
- How to fix it

Example:
```
ValidationError: {
    'release': 'Release must belong to the same project as the change.'
}
```
