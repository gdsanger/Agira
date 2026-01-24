# Agira Admin Interface Documentation

## Overview

The Agira admin interface is built using Django Admin with extensive customizations to provide a comprehensive management interface for all data models. The admin is designed for power users (agents, administrators) to manage the system effectively.

## Admin Configuration Philosophy

1. **Comprehensive Access**: All models are registered in the admin
2. **Smart Defaults**: Sensible list_display, list_filter, and search_fields for each model
3. **Autocomplete**: FK fields with potentially large datasets use autocomplete_fields
4. **Inline Editing**: Related models are edited inline where it makes sense
5. **Read-Only Fields**: Timestamps and computed fields are read-only
6. **Security**: Encrypted fields are masked in the admin interface

## Model Admin Classes

### User & Organization Management

#### OrganisationAdmin
- **List Display**: name
- **Search**: name
- **Inlines**: UserOrganisationInline
- **Purpose**: Manage organizations and view their user memberships

#### UserAdmin (Custom)
Extends Django's BaseUserAdmin with Agira-specific fields.
- **List Display**: username, name, email, role, active, is_staff
- **List Filters**: role, active, is_staff, is_superuser
- **Search**: username, name, email
- **Inlines**: UserOrganisationInline
- **Fieldsets**:
  - Authentication (username, password)
  - Personal info (name, email, role, active)
  - Permissions (is_staff, is_superuser, groups, user_permissions)
  - Important dates (last_login, date_joined)
- **Read-Only**: last_login, date_joined

#### UserOrganisationAdmin
- **List Display**: user, organisation, is_primary
- **List Filters**: is_primary, organisation
- **Search**: user__username, user__name, organisation__name
- **Autocomplete**: user, organisation

### Project Management

#### ProjectAdmin
- **List Display**: name, status, github_owner, github_repo, sentry_enable_auto_fetch
- **List Filters**: status, sentry_enable_auto_fetch
- **Search**: name, github_owner, github_repo
- **Filter Horizontal**: clients (M2M widget)
- **Fieldsets**:
  - Basic info (name, description, status, clients)
  - GitHub integration (github_owner, github_repo)
  - Sentry integration (collapsible section)

#### NodeAdmin
- **List Display**: project, type, name, parent_node, get_matchkey
- **List Filters**: project, type
- **Search**: name, description
- **Autocomplete**: project, parent_node
- **Computed Display**: get_matchkey shows the computed matchkey property

#### ReleaseAdmin
- **List Display**: project, version, name, status, risk, update_date
- **List Filters**: project, status, risk
- **Search**: name, version
- **Autocomplete**: project
- **Read-Only**: update_date
- **Fieldsets**: 
  - Basic info
  - Risk management section

### Work Management

#### ItemTypeAdmin
- **List Display**: name, key, is_active
- **List Filters**: is_active
- **Search**: name, key

#### ItemAdmin (Core Work Management)
The most complex admin with multiple inlines.
- **List Display**: title, project, status, type, assigned_to, requester, updated_at
- **List Filters**: project, status, type
- **Search**: title, description
- **Autocomplete**: project, parent, type, organisation, requester, assigned_to, solution_release
- **Read-Only**: created_at, updated_at
- **Inlines**:
  - ExternalIssueMappingInline (GitHub issues/PRs)
  - ItemCommentInline (read-only display)
- **Fieldsets**:
  - Basic (project, title, status, type)
  - Description (description, solution_description)
  - Relationships (parent, nodes, changes)
  - Assignment (organisation, requester, assigned_to, solution_release)
  - Metadata (created_at, updated_at) - collapsible
- **Filter Horizontal**: nodes, changes

#### ItemRelationAdmin
- **List Display**: from_item, relation_type, to_item
- **List Filters**: relation_type
- **Search**: from_item__title, to_item__title
- **Autocomplete**: from_item, to_item

### Change Management

#### ChangeAdmin
- **List Display**: title, project, status, risk, executed_at, created_by
- **List Filters**: project, status, risk
- **Search**: title, description
- **Autocomplete**: project, release, created_by
- **Read-Only**: created_at, updated_at
- **Inlines**: ChangeApprovalInline
- **Fieldsets**:
  - Basic (project, title, description, status, release)
  - Timeline (planned_start, planned_end, executed_at, created_by)
  - Risk management (risk, risk_description, mitigation, rollback_plan, communication_plan)
  - Metadata (created_at, updated_at) - collapsible

#### ChangeApprovalAdmin
Can be used standalone or inline in ChangeAdmin.
- **List Display**: change, approver, is_required, status, decision_at
- **List Filters**: status, is_required
- **Search**: change__title, approver__username
- **Autocomplete**: change, approver
- **Read-Only**: decision_at

#### ChangeApprovalInline
Tabular inline in ChangeAdmin.
- **Fields**: approver, is_required, status, decision_at, comment
- **Autocomplete**: approver
- **Read-Only**: decision_at

### Communication & Attachments

#### ItemCommentAdmin
- **List Display**: item, author, kind, visibility, created_at, delivery_status
- **List Filters**: kind, visibility, delivery_status
- **Search**: item__title, subject, body
- **Autocomplete**: item, author
- **Read-Only**: created_at, sent_at
- **Fieldsets**:
  - Basic (item, author, kind, visibility)
  - Content (subject, body, body_html)
  - Email-specific fields (external_from, external_to, message_id, in_reply_to, delivery_status, sent_at)
  - Metadata

#### ItemCommentInline
Tabular inline in ItemAdmin (read-only).
- **Fields**: author, kind, visibility, subject, body, created_at
- **Read-Only**: created_at, sent_at
- **Cannot Delete**: True (preserves audit trail)

#### AttachmentAdmin
- **List Display**: original_name, project, content_type, get_file_size, uploaded_at, uploaded_by
- **List Filters**: project, content_type
- **Search**: original_name, description
- **Autocomplete**: project, uploaded_by
- **Read-Only**: uploaded_at, sha256, get_file_size
- **Custom Method**: get_file_size formats bytes to human-readable format (B, KB, MB, GB, TB)

#### AttachmentLinkAdmin
- **List Display**: attachment, role, target_content_type, target_object_id
- **List Filters**: role, target_content_type
- **Search**: attachment__original_name
- **Autocomplete**: attachment

### Integration

#### ExternalIssueMappingAdmin
- **List Display**: item, kind, number, state, github_id, last_synced_at
- **List Filters**: kind, state
- **Search**: item__title, number, github_id
- **Autocomplete**: item
- **Read-Only**: last_synced_at

#### ExternalIssueMappingInline
Tabular inline in ItemAdmin.
- **Fields**: github_id, number, kind, state, html_url, last_synced_at
- **Read-Only**: last_synced_at
- **Extra**: 0 (no empty rows by default)

### Activity

#### ActivityAdmin
- **List Display**: verb, actor, created_at, target_content_type, target_object_id
- **List Filters**: verb, actor, created_at
- **Search**: verb, summary
- **Autocomplete**: actor
- **Read-Only**: created_at

### Configuration

All configuration admin classes extend `ConfigurationAdmin` base class.

#### ConfigurationAdmin (Base Class)
- **has_add_permission**: Only allows adding if no instance exists (singleton)
- **has_delete_permission**: Prevents deletion of configuration
- **Encrypted Field Masking**: Overrides get_form to display placeholders (••••••••) for encrypted fields

#### GitHubConfigurationAdmin
- **Fieldsets**:
  - Enabled flag
  - GitHub App settings (app_id, installation_id, private_key, webhook_secret)
- **Masked Fields**: private_key, webhook_secret

#### WeaviateConfigurationAdmin
- **Fieldsets**:
  - Enabled flag
  - Weaviate settings (url, api_key)
- **Masked Fields**: api_key

#### GooglePSEConfigurationAdmin
- **Fieldsets**:
  - Enabled flag
  - Google PSE settings (api_key, search_engine_id)
- **Masked Fields**: api_key

#### GraphAPIConfigurationAdmin
- **Fieldsets**:
  - Enabled flag
  - Graph API settings (tenant_id, client_id, client_secret)
- **Masked Fields**: client_secret

#### ZammadConfigurationAdmin
- **Fieldsets**:
  - Enabled flag
  - Zammad settings (url, api_token)
- **Masked Fields**: api_token

## Admin Features

### Autocomplete Fields
Used for foreign keys that can have many instances to improve performance and UX:
- User selections
- Organisation selections
- Project selections
- Item selections (for parent, relations)
- Type selections
- Release selections

### Filter Horizontal
Used for many-to-many fields to provide a better selection interface:
- Project.clients
- Item.nodes
- Item.changes

### Inline Editing
Allows editing related objects without leaving the parent object's page:
- UserOrganisation inline in User and Organisation
- ChangeApproval inline in Change
- ExternalIssueMapping inline in Item
- ItemComment inline in Item (read-only)

### Custom Display Methods
- `get_matchkey` in NodeAdmin: Shows computed matchkey property
- `get_file_size` in AttachmentAdmin: Formats file size in human-readable units

### Security Features
- Encrypted fields are masked in the form (show ••••••••)
- Configuration models cannot be deleted
- Only one configuration instance allowed per type

## Best Practices

1. **Always use autocomplete_fields** for foreign keys with potentially many instances
2. **Keep inlines lightweight** - only include essential fields
3. **Mark computed/auto fields as read-only** to prevent confusion
4. **Group related fields** in fieldsets for better organization
5. **Use collapsible fieldsets** for advanced/optional sections
6. **Provide meaningful search_fields** to help users find records quickly
7. **Use list_filter** for fields that users commonly filter by

## Future Enhancements

Potential improvements to the admin interface:
- Custom admin actions (bulk status changes, exports)
- Custom list filters (e.g., "My Items", "Pending Approvals")
- Admin dashboard with statistics
- Integration status indicators
- Enhanced file preview for attachments
- Markdown preview for description fields
