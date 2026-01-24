# Integration Base

## Purpose

The Integration Base provides a consistent foundation for all external service integrations in Agira. It implements common patterns for configuration, error handling, HTTP communication, and retry logic.

**Design Principles:**
- **Thin, not thick**: 80% utility with 20% effort - no framework monster
- **No magic**: Explicit and straightforward
- **Consistent**: All integrations look and behave similarly
- **Secure**: Never log secrets or tokens

## Supported Integrations

The Integration Base is designed to support:
- GitHub API
- Weaviate vector database
- Microsoft Graph API
- AI providers (OpenAI, Gemini)
- Future integrations (Sentry, Zammad, etc.)

## Components

### 1. Exception Hierarchy (`errors.py`)

All integration errors inherit from `IntegrationError`, providing a unified exception hierarchy:

```
IntegrationError (base)
├── IntegrationDisabled - Integration is disabled in config
├── IntegrationNotConfigured - Integration enabled but config incomplete
├── IntegrationAuthError - Authentication failed (401/403)
├── IntegrationRateLimited - Rate limit exceeded (429)
├── IntegrationTemporaryError - Temporary failure, retry possible (5xx, timeouts)
└── IntegrationPermanentError - Permanent failure, don't retry (4xx)
```

#### Exception Details

**`IntegrationError`**
- Base exception for all integration errors
- Catch this to handle any integration error

**`IntegrationDisabled`**
- Raised when integration is disabled in configuration
- Not an error condition, just a state
- Example: GitHub integration disabled via admin panel

**`IntegrationNotConfigured`**
- Raised when integration is enabled but config is incomplete
- Missing API keys, endpoints, etc.
- Example: Weaviate enabled but URL not set

**`IntegrationAuthError`**
- Authentication/authorization failures
- HTTP 401/403 errors
- **Do not retry** - credentials need fixing
- Example: Invalid API token, expired credentials

**`IntegrationRateLimited`**
- Rate limit exceeded
- HTTP 429 errors
- **Can retry** after `retry_after` seconds
- Attributes:
  - `retry_after`: Optional seconds to wait (from Retry-After header)

**`IntegrationTemporaryError`**
- Temporary failures that may succeed on retry
- HTTP 5xx server errors, timeouts, connection errors
- **Should retry** with exponential backoff
- Example: Service temporarily unavailable, network timeout

**`IntegrationPermanentError`**
- Permanent failures that won't succeed on retry
- HTTP 4xx client errors (except 429)
- **Do not retry** - request is invalid
- Example: Validation error, malformed request, resource not found

#### Security: No Secrets in Exceptions

**Never include sensitive data in exception messages:**
- ❌ API keys, tokens, passwords
- ❌ Authorization headers
- ❌ Full URLs with embedded credentials
- ✅ HTTP status codes
- ✅ Truncated response bodies (max 500 chars)
- ✅ Error types and categories

### 2. BaseIntegration Class (`base.py`)

Base class for all integrations providing common functionality:

```python
from core.services.integrations import BaseIntegration
from core.models import GitHubConfiguration

class GitHubIntegration(BaseIntegration):
    """GitHub API integration."""
    
    name = "github"
    
    def _get_config_model(self):
        """Return the configuration model class."""
        return GitHubConfiguration
    
    def _is_config_complete(self, config):
        """Validate configuration completeness."""
        return bool(config.github_token)
    
    def get_issue(self, owner, repo, issue_number):
        """Get a GitHub issue."""
        # Check integration is available
        config = self.require_config()
        
        # Use the integration...
        # ...
```

#### BaseIntegration API

**Properties:**
- `name: str` - Integration name (e.g., "github", "weaviate")
- `logger: logging.Logger` - Logger with namespace `agira.integration.<name>`

**Methods:**

`get_config() -> Optional[Config]`
- Returns configuration object or None
- Uses config service with caching (from Issue #1)

`enabled() -> bool`
- Checks if integration is enabled
- Returns False if not configured

`require_enabled() -> None`
- Ensures integration is enabled
- Raises `IntegrationDisabled` if disabled

`require_config() -> Config`
- Ensures integration is enabled AND properly configured
- Returns configuration object
- Raises `IntegrationDisabled` if disabled
- Raises `IntegrationNotConfigured` if config incomplete

**Subclass Requirements:**

Must implement:
1. Set `name` property
2. Implement `_get_config_model()` - return Django model class
3. Implement `_is_config_complete(config)` - validate config

### 3. HTTP Client (`http.py`)

HTTP wrapper with consistent error handling, timeouts, and retry logic.

#### Basic Usage

```python
from core.services.integrations import HTTPClient

# Create client
client = HTTPClient(
    base_url="https://api.github.com",
    headers={"Authorization": f"Bearer {token}"},
    timeout=30.0,
    max_retries=3,
)

# Make requests
try:
    data = client.get("/repos/owner/repo")
    result = client.post("/repos/owner/repo/issues", json={"title": "Bug"})
except IntegrationAuthError:
    # Handle auth failure
    pass
except IntegrationRateLimited as e:
    # Handle rate limit
    wait_time = e.retry_after or 60
    time.sleep(wait_time)
except IntegrationTemporaryError:
    # Handle temporary failure
    pass
```

#### Available Methods

**Convenience methods (return JSON):**
- `get(path, headers=None, params=None) -> dict`
- `post(path, headers=None, json=None, data=None) -> dict`
- `patch(path, headers=None, json=None) -> dict`
- `put(path, headers=None, json=None) -> dict`
- `delete(path, headers=None) -> dict`

**Spec-compliant methods:**
- `request_json(method, url, *, headers, params, json, timeout) -> dict|None`
- `request_bytes(method, url, *, headers, params, json, timeout) -> bytes|None`

#### HTTP Error Mapping

The client automatically maps HTTP status codes to exceptions:

| Status Code | Exception | Retry? |
|-------------|-----------|--------|
| 401, 403 | `IntegrationAuthError` | No |
| 429 | `IntegrationRateLimited` | Yes (after retry_after) |
| 5xx | `IntegrationTemporaryError` | Yes |
| 4xx (other) | `IntegrationPermanentError` | No |
| Timeout | `IntegrationTemporaryError` | Yes |
| Connection Error | `IntegrationTemporaryError` | Yes |

## Retry Strategy

### Configuration

- **Default retries**: 3 attempts total (initial + 2 retries)
- **Backoff strategy**: Exponential - 0.5s, 1s, 2s
- **Retry-After support**: Respects `Retry-After` header for 429 errors

### Retry Rules

**Retry ON:**
- Network timeouts (`httpx.TimeoutException`)
- Connection errors (`httpx.ConnectError`)
- HTTP 429 (rate limits)
- HTTP 5xx (server errors)

**DO NOT Retry:**
- HTTP 4xx (except 429) - client errors, permanent
- HTTP 401/403 - authentication errors, need credential fix
- Validation errors - request is malformed

### Example Retry Flow

```
Attempt 1: Request → 503 Server Error
  ↓ Wait 0.5s
Attempt 2: Request → Timeout
  ↓ Wait 1s
Attempt 3: Request → 200 OK ✓
```

### Disabling Retry

Pass `max_retries=1` to disable retry:

```python
client = HTTPClient(
    base_url="https://api.example.com",
    max_retries=1,  # No retries
)
```

## Logging Guidelines

### What to Log

**✅ DO log:**
- HTTP method + host + path
- Status codes
- Error types and categories
- Truncated responses (max 500 chars)

**❌ DON'T log:**
- Authorization headers
- API keys or tokens
- Passwords or secrets
- Full URLs with embedded credentials
- Full response bodies (truncate)

### Example Logs

```
DEBUG agira.integration.github - GET https://api.github.com/repos/owner/repo
WARNING agira.integration.github - Request failed (attempt 1/3): IntegrationTemporaryError: Server error (HTTP 503). Retrying in 0.5s...
ERROR agira.integration.github - IntegrationAuthError: Authentication failed (HTTP 401): {"message": "Bad credentials"}
```

### Implementation

The HTTP client automatically:
1. Sanitizes headers before logging (replaces sensitive values with `***`)
2. Truncates response bodies to 500 characters
3. Logs at appropriate levels:
   - DEBUG: Successful requests
   - WARNING: Retries
   - ERROR: Final failures

## Configuration Integration

The Integration Base uses the Config Service from Issue #1:

```python
from core.services import config

# Config service provides:
config.get_singleton(GitHubConfiguration)  # With caching
config.get_github_config()                 # Convenience method
config.is_github_enabled()                 # Enabled check
```

Integration classes automatically use this via `BaseIntegration.get_config()`.

## Testing

### Testing Integrations

```python
from django.test import TestCase
from core.services.integrations import (
    IntegrationDisabled,
    IntegrationNotConfigured,
)

class MyIntegrationTest(TestCase):
    def test_disabled_raises_error(self):
        """Test that disabled integration raises error."""
        integration = MyIntegration()
        
        with self.assertRaises(IntegrationDisabled):
            integration.require_enabled()
    
    def test_incomplete_config_raises_error(self):
        """Test that incomplete config raises error."""
        # Create config with missing fields
        config = MyConfiguration.objects.create(
            enabled=True,
            api_key="",  # Missing!
        )
        
        integration = MyIntegration()
        
        with self.assertRaises(IntegrationNotConfigured):
            integration.require_config()
```

### Testing HTTP Errors

```python
import httpx
import respx
from core.services.integrations import (
    HTTPClient,
    IntegrationAuthError,
    IntegrationRateLimited,
    IntegrationTemporaryError,
)

@respx.mock
def test_auth_error():
    """Test that 401 raises IntegrationAuthError."""
    respx.get("https://api.example.com/test").mock(
        return_value=httpx.Response(401, json={"error": "Unauthorized"})
    )
    
    client = HTTPClient(base_url="https://api.example.com")
    
    with pytest.raises(IntegrationAuthError):
        client.get("/test")

@respx.mock
def test_retry_on_500():
    """Test that 500 errors are retried."""
    # First attempt fails, second succeeds
    respx.get("https://api.example.com/test").mock(
        side_effect=[
            httpx.Response(500, text="Server Error"),
            httpx.Response(200, json={"status": "ok"}),
        ]
    )
    
    client = HTTPClient(base_url="https://api.example.com", max_retries=2)
    result = client.get("/test")
    
    assert result == {"status": "ok"}
```

## Migration Guide

### Updating Existing Integrations

To migrate an existing integration to use the Integration Base:

1. **Update imports:**
```python
# Before
from core.services.exceptions import ServiceError

# After
from core.services.integrations import (
    BaseIntegration,
    IntegrationDisabled,
    IntegrationNotConfigured,
)
```

2. **Inherit from BaseIntegration:**
```python
# Before
class MyService:
    def __init__(self):
        self.config = MyConfiguration.load()

# After
class MyService(BaseIntegration):
    name = "myservice"
    
    def _get_config_model(self):
        return MyConfiguration
    
    def _is_config_complete(self, config):
        return bool(config.api_key and config.endpoint)
```

3. **Use HTTPClient for HTTP calls:**
```python
# Before
import requests
response = requests.get(url, headers=headers)

# After
from core.services.integrations import HTTPClient

client = HTTPClient(base_url=base_url, headers=default_headers)
data = client.get(path)
```

4. **Update exception handling:**
```python
# Before
try:
    make_request()
except ServiceNotConfigured:
    # Handle

# After
try:
    config = self.require_config()
    make_request()
except IntegrationNotConfigured:
    # Handle
except IntegrationAuthError:
    # Handle auth
except IntegrationTemporaryError:
    # Handle temporary
```

## Best Practices

1. **Always call `require_config()` before API calls** to ensure integration is available
2. **Use the logger** provided by `BaseIntegration` for consistent logging
3. **Handle specific exceptions** rather than catching broad `IntegrationError`
4. **Respect rate limits** - wait for `retry_after` when handling `IntegrationRateLimited`
5. **Don't retry permanent errors** - they won't succeed
6. **Keep secrets out of logs** - the framework helps, but validate your code
7. **Use HTTPClient** instead of direct requests/httpx for consistency

## Future Enhancements

Potential future improvements (not in v1):
- Metrics/observability hooks
- Circuit breaker pattern
- Request/response middleware
- Multi-tenant routing
- Background job integration with Celery
- Webhook handling patterns

## Related Documentation

- [Config Service](./config.md) - Configuration loading and caching
- [GitHub Service](./github.md) - Example integration implementation
- [Weaviate Service](./weaviate.md) - Vector database integration
- [Graph API Service](./graph-mail.md) - Microsoft Graph integration
