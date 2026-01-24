# GitHub Service

The GitHub Service provides integration between Agira and GitHub repositories, enabling:
- Creation of GitHub issues from Agira items
- Synchronization of GitHub issues and pull requests
- Mapping and tracking of external GitHub items within Agira

## Table of Contents

- [Configuration](#configuration)
- [Required GitHub Token Scopes](#required-github-token-scopes)
- [Architecture](#architecture)
- [Usage Examples](#usage-examples)
- [API Reference](#api-reference)
- [Mapping Rules](#mapping-rules)
- [Error Handling](#error-handling)

## Configuration

### Database Configuration

The GitHub service is configured through the `GitHub_Configuration` singleton model in the Django admin:

1. Navigate to **Django Admin → GitHub Configuration**
2. Configure the following fields:

#### Main Settings

- **Enable GitHub** (`enable_github`): Enable/disable the GitHub integration
- **GitHub Token** (`github_token`): Personal Access Token or App token for API authentication
- **GitHub API Base URL** (`github_api_base_url`): API endpoint (default: `https://api.github.com`)
- **Default GitHub Owner** (`default_github_owner`): Optional default organization/user
- **GitHub Copilot Username** (`github_copilot_username`): Username for attribution in automated actions

#### Legacy GitHub App Settings

These fields are for GitHub App integration (v1 focuses on token-based auth):
- `app_id`, `installation_id`, `private_key`, `webhook_secret`, `enabled`

### Project Configuration

Each Agira `Project` needs GitHub repository information:

- **GitHub Owner** (`github_owner`): Repository owner (user or organization)
- **GitHub Repo** (`github_repo`): Repository name

Example: For `https://github.com/acme/myapp`, set `github_owner=acme` and `github_repo=myapp`.

## Required GitHub Token Scopes

To use the GitHub Service, your Personal Access Token needs the following scopes:

### For Public Repositories

- `public_repo` - Access public repositories

### For Private Repositories

- `repo` - Full control of private repositories
  - Includes: `repo:status`, `repo_deployment`, `public_repo`, `repo:invite`

### Recommended Additional Scopes

- `read:org` - Read organization membership (if working with organization repos)
- `user:email` - Access user email addresses (for author attribution)

### Creating a Personal Access Token

1. Go to **GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)**
2. Click **Generate new token (classic)**
3. Give it a descriptive name (e.g., "Agira Integration")
4. Select the required scopes above
5. Click **Generate token**
6. Copy the token and paste it into Agira's GitHub Configuration

**Security Note:** Store the token securely. It's encrypted in Agira's database using `django-encrypted-model-fields`.

## Architecture

The GitHub service is organized in three layers:

### 1. Integration Base (`core/services/integrations/`)

Provides common functionality for all external integrations:

- **`base.py`**: Base classes and exceptions
  - `IntegrationBase`: Abstract base class
  - `IntegrationError` and subclasses
- **`http.py`**: HTTP client with retry logic, timeout, and error mapping

### 2. GitHub Client (`core/services/github/client.py`)

Low-level GitHub REST API v3 client:

- **Issue methods**: `get_issue()`, `create_issue()`, `close_issue()`, `list_issues()`
- **PR methods**: `get_pr()`, `list_prs()`
- Handles authentication headers and API versioning

### 3. GitHub Service (`core/services/github/service.py`)

High-level service integrating with Agira models:

- **`create_issue_for_item()`**: Create GitHub issue from Agira item
- **`sync_mapping()`**: Sync single ExternalIssueMapping with GitHub
- **`sync_item()`**: Sync all mappings for an item
- **`upsert_mapping_from_github()`**: Map existing GitHub issue/PR to item

## Usage Examples

### Initialize the Service

```python
from core.services.github import GitHubService

github = GitHubService()
```

### Create GitHub Issue from Agira Item

```python
from core.models import Item

item = Item.objects.get(id=123)

# Create issue with default title/body
mapping = github.create_issue_for_item(
    item=item,
    labels=['bug', 'priority:high'],
    actor=request.user,
)

print(f"Created issue #{mapping.number}: {mapping.html_url}")
```

### Create Issue with Custom Title/Body

```python
mapping = github.create_issue_for_item(
    item=item,
    title=f"[{item.type.name}] {item.title}",
    body=f"## Description\n\n{item.description}\n\n## Solution\n\n{item.solution_description}",
    labels=['enhancement'],
    actor=request.user,
)
```

### Sync Existing Mapping

```python
from core.models import ExternalIssueMapping

mapping = ExternalIssueMapping.objects.get(id=456)

# Fetch latest state from GitHub
updated_mapping = github.sync_mapping(mapping)

print(f"State: {updated_mapping.state}")
print(f"Last synced: {updated_mapping.last_synced_at}")
```

### Sync All Mappings for an Item

```python
item = Item.objects.get(id=123)

count = github.sync_item(item)
print(f"Synced {count} mappings")
```

### Map Existing GitHub Issue to Item

```python
# Map existing GitHub issue #42 to Agira item
mapping = github.upsert_mapping_from_github(
    item=item,
    number=42,
    kind='issue',
)

# Map existing GitHub PR #15
mapping = github.upsert_mapping_from_github(
    item=item,
    number=15,
    kind='pr',
)
```

### Error Handling

```python
from core.services.integrations.base import (
    IntegrationDisabled,
    IntegrationNotConfigured,
    IntegrationAuthError,
    IntegrationRateLimitError,
)

try:
    mapping = github.create_issue_for_item(item)
except IntegrationDisabled:
    print("GitHub integration is disabled")
except IntegrationNotConfigured:
    print("GitHub integration is enabled but not configured")
except IntegrationAuthError:
    print("GitHub authentication failed - check token")
except IntegrationRateLimitError as e:
    print(f"Rate limit exceeded. Retry after: {e.retry_after} seconds")
except ValueError as e:
    print(f"Invalid configuration: {e}")
```

## API Reference

### GitHubService

#### `create_issue_for_item(item, *, title=None, body=None, labels=None, actor=None)`

Create a GitHub issue for an Agira item.

**Parameters:**
- `item` (Item): Agira item to create issue for
- `title` (str, optional): Issue title (default: `item.title`)
- `body` (str, optional): Issue body in Markdown (default: auto-generated from item)
- `labels` (list[str], optional): List of label names
- `actor` (User, optional): User creating the issue (for activity logging)

**Returns:** `ExternalIssueMapping` - The created mapping

**Raises:**
- `IntegrationDisabled`: GitHub is disabled
- `IntegrationNotConfigured`: GitHub token not set
- `ValueError`: Project missing GitHub repo configuration

**Activity Logged:** `github.issue_created`

---

#### `sync_mapping(mapping)`

Synchronize an ExternalIssueMapping with GitHub.

**Parameters:**
- `mapping` (ExternalIssueMapping): Mapping to sync

**Returns:** `ExternalIssueMapping` - The updated mapping

**Updates:**
- `state` - Current state from GitHub
- `html_url` - Current URL
- `github_id` - GitHub internal ID
- `last_synced_at` - Timestamp of sync

**Activity Logged:** `github.issue_state_changed` or `github.pr_state_changed` (if state changed)

---

#### `sync_item(item)`

Synchronize all ExternalIssueMappings for an item.

**Parameters:**
- `item` (Item): Agira item to sync

**Returns:** `int` - Number of mappings successfully synced

**Note:** Continues on error, logs failures

---

#### `upsert_mapping_from_github(item, *, number, kind)`

Create or update mapping from existing GitHub issue/PR.

**Parameters:**
- `item` (Item): Agira item to map to
- `number` (int): GitHub issue/PR number
- `kind` (str): Either `'issue'` or `'pr'`

**Returns:** `ExternalIssueMapping` - Created or updated mapping

**Deduplication:**
1. Searches by `github_id` first (most reliable)
2. Falls back to `(item, kind, number)` combination
3. Creates new mapping if none found

## Mapping Rules

### ExternalIssueMapping Model

Each mapping represents a link between an Agira item and a GitHub issue/PR:

- **`item`** (FK to Item): The Agira item
- **`github_id`** (BigInt, unique): GitHub's internal ID for the issue/PR
- **`number`** (Int): Issue/PR number (e.g., #42)
- **`kind`** (Enum): Either `'issue'` or `'pr'`
- **`state`** (String): Current state
- **`html_url`** (URL): Link to GitHub
- **`last_synced_at`** (DateTime): Last sync timestamp

### State Mapping

#### Issues

GitHub issues have two states:
- `open` - Issue is open
- `closed` - Issue is closed

#### Pull Requests

PRs have three states in Agira:
- `open` - PR is open
- `closed` - PR is closed (not merged)
- `merged` - PR was merged (detected via `merged_at` field)

### Uniqueness Constraints

- **`github_id`** must be unique across all mappings
- An item can have multiple mappings (multiple issues/PRs)
- The same GitHub issue cannot be mapped to different items (enforced by `github_id` uniqueness)

### Repository Source

The repository information comes from the item's project:
- `item.project.github_owner`
- `item.project.github_repo`

This means mappings don't store repository info directly - it's always derived from the project.

## Error Handling

### Integration Base Exceptions

All exceptions inherit from `IntegrationError`:

#### `IntegrationDisabled`

Raised when GitHub integration is disabled in configuration.

**Solution:** Enable GitHub in Django Admin → GitHub Configuration → Enable GitHub

#### `IntegrationNotConfigured`

Raised when GitHub is enabled but `github_token` is not set.

**Solution:** Set GitHub token in Django Admin → GitHub Configuration → GitHub Token

#### `IntegrationAuthError`

Raised on HTTP 401/403 errors from GitHub API.

**Causes:**
- Invalid or expired token
- Insufficient token permissions
- Token revoked

**Solution:** Check and update GitHub token

#### `IntegrationRateLimitError`

Raised on HTTP 429 errors from GitHub API.

**Attributes:**
- `retry_after` (int, optional): Seconds to wait before retrying

**Solution:** Wait and retry. GitHub has rate limits:
- Authenticated requests: 5,000 per hour
- Unauthenticated: 60 per hour

#### `IntegrationNotFoundError`

Raised on HTTP 404 errors from GitHub API.

**Causes:**
- Issue/PR number doesn't exist
- Repository doesn't exist
- No access to private repository

#### `IntegrationValidationError`

Raised on HTTP 400/422 errors from GitHub API.

**Causes:**
- Invalid request data
- Missing required fields
- Validation constraints violated

### HTTP Client Retry Logic

The HTTP client automatically retries on transient errors:

- **Max retries:** 3 attempts
- **Backoff:** Exponential (1s, 2s, 4s)
- **Retried errors:** Timeouts, connection errors
- **Not retried:** Auth errors, not found, validation errors

## Activity Logging

The GitHub service logs activities when the Activity model is available:

### Activity Verbs

- **`github.issue_created`**: Issue created from Agira item
- **`github.issue_state_changed`**: Issue state changed (open ↔ closed)
- **`github.pr_state_changed`**: PR state changed (open ↔ closed ↔ merged)

### Activity Fields

- **`target`**: The Agira Item
- **`verb`**: Activity type (see above)
- **`actor`**: User who performed the action (if provided)
- **`summary`**: Human-readable description
- **`created_at`**: Timestamp

## Limitations (v1)

The current version has the following limitations:

1. **No bidirectional field sync**: Changes to GitHub issue titles/descriptions don't sync back to Agira items
2. **No commit tracking**: Commits and code changes are not tracked
3. **No webhooks**: Updates must be pulled manually via `sync_*` methods
4. **No comment sync**: Issue comments are not synced
5. **No assignee sync**: GitHub assignees are not reflected in Agira
6. **No milestone tracking**: GitHub milestones are not imported

These may be addressed in future versions.

## Testing

To test the GitHub service:

```python
# In Django shell
from core.services.github import GitHubService
from core.models import Item

github = GitHubService()

# Check configuration
print(f"Enabled: {github.is_enabled()}")
print(f"Configured: {github.is_configured()}")

# Test with an item
item = Item.objects.first()
if item and item.project.github_owner and item.project.github_repo:
    # Create issue (this will actually create it on GitHub!)
    # mapping = github.create_issue_for_item(item, labels=['test'])
    # print(f"Created: {mapping.html_url}")
    
    # Or map an existing issue
    mapping = github.upsert_mapping_from_github(
        item=item,
        number=1,  # Issue #1
        kind='issue',
    )
    print(f"Mapped: {mapping}")
```

## Security

- **Token encryption**: GitHub tokens are encrypted in the database using `django-encrypted-model-fields`
- **No token logging**: Tokens are never logged or exposed in error messages
- **HTTPS only**: All GitHub API requests use HTTPS
- **Scoped tokens**: Use tokens with minimal required scopes

## Troubleshooting

### "GitHub integration is disabled"

Enable it in Django Admin → GitHub Configuration → Enable GitHub

### "GitHub integration is enabled but not properly configured"

Set the GitHub Token in Django Admin → GitHub Configuration → GitHub Token

### "Project 'X' does not have GitHub repository configured"

Set `github_owner` and `github_repo` on the Project in Django Admin

### "Authentication failed"

Check that:
1. GitHub token is valid
2. Token has required scopes (`repo` or `public_repo`)
3. Token hasn't been revoked

### "Rate limit exceeded"

Wait for the rate limit to reset (check `X-RateLimit-Reset` header) or:
1. Use authenticated requests (higher limit)
2. Spread requests over time
3. Use conditional requests with `If-None-Match`

## Future Enhancements

Potential improvements for future versions:

- **Webhooks**: Automatic updates via GitHub webhooks
- **Bidirectional sync**: Sync issue changes back to items
- **Comment sync**: Sync issue comments to ItemComments
- **Assignee mapping**: Map GitHub assignees to Agira users
- **Label sync**: Auto-create and sync labels
- **Milestone integration**: Link GitHub milestones to Releases
- **GitHub Actions integration**: Trigger workflows
- **Pull request creation**: Create PRs from Agira
- **Commit tracking**: Track commits related to items
