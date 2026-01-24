# Agira Data Model Documentation

## Overview

The Agira data model is designed to support project management, change management, and work tracking for software development teams. It follows a pragmatic approach with clear relationships and minimal complexity.

## Core Concepts

### Entity-Relationship Overview

The data model consists of several interconnected domains:

1. **User & Organization Management** - User authentication, roles, and organization membership
2. **Project Structure** - Projects, nodes (code structure), and releases
3. **Work Management** - Items (tasks, bugs, features), their relationships, and status tracking
4. **Change Management** - Changes, approvals, and deployment tracking
5. **Communication** - Comments, attachments, and activity tracking
6. **External Integrations** - GitHub issue mappings and configuration

## Model Descriptions

### User & Organization Domain

#### Organisation
Represents a company or organizational unit.
- **Fields**: `name`
- **Relationships**: Many-to-many with Users through UserOrganisation

#### User (Custom User Model)
Django authentication-based user model with role-based access.
- **Fields**: `username`, `email`, `name`, `role` (User/Agent/Approver), `active`
- **Special**: Extends Django's AbstractBaseUser and PermissionsMixin
- **Relationships**: 
  - Many-to-many with Organisation through UserOrganisation
  - Can be assigned to Items
  - Can request Items
  - Can approve Changes

#### UserOrganisation
Join table managing user-organization relationships with primary organization tracking.
- **Fields**: `organisation`, `user`, `is_primary`
- **Constraints**: 
  - Unique (user, organisation)
  - Max 1 primary organisation per user (partial unique index)

### Project Domain

#### Project
Represents a software project, typically mapped to a GitHub repository.
- **Fields**: `name`, `description`, `github_owner`, `github_repo`, `status`
- **Clients**: Many-to-many relationship with Organisations
- **Sentry Integration**: `sentry_dsn`, `sentry_project_slug`, `sentry_auth_token` (encrypted), `sentry_enable_auto_fetch`
- **Status**: New, Working, Canceled, Finished

#### Node
Represents structural elements within a project (views, entities, classes, etc.).
- **Fields**: `project`, `name`, `type`, `description`, `parent_node`
- **Types**: Project, View, Entity, Class, Action, Report, Other
- **Computed Property**: `matchkey` = "{type}:{name}"
- **Hierarchical**: Can have parent-child relationships

#### Release
Represents a version/release of a project.
- **Fields**: `project`, `name`, `version`, `status`, `risk`, `update_date`
- **Risk Management**: `risk_description`, `risk_mitigation`, `rescue_measure`
- **Status**: Planned, Working, Closed
- **Risk Levels**: Low, Normal, High, VeryHigh

### Work Management Domain

#### ItemType
Global item classification (Bug, Feature, Task, etc.).
- **Fields**: `key`, `name`, `is_active`
- **Global**: Not project-specific

#### Item
Central work unit in the system.
- **Fields**: `title`, `description`, `solution_description`, `status`
- **Relationships**:
  - Belongs to a `project` (required)
  - Can have a `parent` Item (hierarchical)
  - Has a `type` (ItemType)
  - Links to `nodes` (many-to-many)
  - Can be assigned to an `organisation`
  - Has a `requester` and can be `assigned_to` a User
  - Can be part of a `solution_release`
  - Can be linked to multiple `changes`
- **Status**: Inbox, Backlog, Working, Testing, ReadyForRelease, Closed
- **Timestamps**: `created_at`, `updated_at` (auto-managed)

#### ItemRelation
Defines relationships between Items.
- **Fields**: `from_item`, `to_item`, `relation_type`
- **Types**: DependOn, Similar, Related
- **Constraints**: Unique (from_item, to_item, relation_type)
- **Indexed**: On (from_item, to_item)

### Change Management Domain

#### Change
Represents a deployment or change event.
- **Fields**: `project`, `title`, `description`, `status`, `risk`
- **Timeline**: `planned_start`, `planned_end`, `executed_at`
- **Risk Management**: `risk_description`, `mitigation`, `rollback_plan`, `communication_plan`
- **Relationships**: 
  - Belongs to a `project`
  - Can be linked to a `release`
  - Has a `created_by` User
  - Links to multiple Items (many-to-many)
- **Status**: Draft, Planned, InProgress, Deployed, RolledBack, Canceled
- **Timestamps**: `created_at`, `updated_at`

#### ChangeApproval
Tracks approvals for changes (audit-capable).
- **Fields**: `change`, `approver`, `is_required`, `status`, `decision_at`, `comment`
- **Status**: Pending, Approved, Rejected
- **Constraints**: Unique (change, approver)

### Communication Domain

#### ItemComment
Comments and communication on Items.
- **Fields**: `item`, `author`, `visibility`, `kind`, `subject`, `body`
- **Email Fields**: `external_from`, `external_to`, `message_id`, `in_reply_to`, `delivery_status`, `sent_at`
- **Visibility**: Public, Internal
- **Kind**: Note, Comment, EmailIn, EmailOut
- **Delivery Status**: Draft, Queued, Sent, Failed
- **HTML Support**: `body_html` for rendered content

#### Attachment
File attachments with metadata.
- **Fields**: `project`, `file`, `original_name`, `content_type`, `size`, `sha256`, `description`
- **Uploaded by**: User reference
- **Storage**: FileField with upload path pattern
- **Auto-computed**: SHA-256 hash on save

#### AttachmentLink
Generic link from Attachments to any model.
- **Generic FK**: `target_content_type`, `target_object_id`, `target`
- **Role**: ProjectFile, ItemFile, CommentAttachment
- **Constraints**: Unique (attachment, target_content_type, target_object_id)

#### Activity
Generic activity stream for tracking changes.
- **Generic FK**: `target_content_type`, `target_object_id`, `target`
- **Fields**: `verb`, `actor`, `summary`, `created_at`
- **Use Case**: Audit trail, dashboard, notifications

### Integration Domain

#### ExternalIssueMapping
Maps Items to external GitHub issues/PRs.
- **Fields**: `item`, `github_id`, `number`, `kind`, `state`, `html_url`
- **Kind**: Issue, PR
- **Constraints**: Unique `github_id`
- **Auto-updated**: `last_synced_at`

### Configuration Domain

All configuration models are **Singleton Models** (only one instance allowed).

#### GitHubConfiguration
- **Fields**: `app_id`, `installation_id`, `private_key` (encrypted), `webhook_secret` (encrypted), `enabled`

#### WeaviateConfiguration
- **Fields**: `url`, `api_key` (encrypted), `enabled`

#### GooglePSEConfiguration
- **Fields**: `api_key` (encrypted), `search_engine_id`, `enabled`

#### GraphAPIConfiguration
- **Fields**: `tenant_id`, `client_id`, `client_secret` (encrypted), `enabled`

#### ZammadConfiguration
- **Fields**: `url`, `api_token` (encrypted), `enabled`

## Key Design Patterns

### Encryption
All sensitive fields (API keys, tokens, secrets) use `EncryptedCharField` from `django-encrypted-model-fields`.

### Singleton Pattern
Configuration models use a custom `SingletonModel` base class that ensures only one instance exists (pk=1).

### Generic Foreign Keys
Used for `AttachmentLink` and `Activity` to allow flexible relationships with multiple model types.

### Hierarchical Structures
- Items can have parent-child relationships
- Nodes can have parent-child relationships

### Audit Trail
- Most models have `created_at`/`updated_at` timestamps
- ChangeApproval tracks who approved what and when
- Activity model provides a generic event log

## Model Validation

See [validation.md](validation.md) for detailed information on model-level validation rules and constraints.

## Database Constraints

- **Unique Constraints**: UserOrganisation (user, organisation), ChangeApproval (change, approver), ItemRelation (from_item, to_item, relation_type), AttachmentLink (attachment, target)
- **Partial Unique Constraints**: UserOrganisation (user) where is_primary=True
- **Indexes**: ItemRelation (from_item, to_item)
- **Foreign Key Cascades**: Mostly CASCADE on direct ownership, SET_NULL on references

## Notes

- All text fields support Markdown where appropriate (description, solution_description, etc.)
- The model is designed for PostgreSQL but works with SQLite for development
- No multi-tenancy - one installation per organization
- GitHub integration is optional but recommended
