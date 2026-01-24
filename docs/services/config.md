# Core Configuration Service

## Overview

The core configuration service provides a centralized, consistent way to access singleton configuration models throughout the Agira application. It handles caching, feature flags, and provides clean APIs for all core services (GitHub, Weaviate, Google PSE, Graph API, Zammad).

## Key Features

- **Singleton Configuration Loading**: Safely loads singleton config models from the database
- **Intelligent Caching**: Reduces database overhead with configurable TTL-based caching
- **Feature Flags**: Consistent `is_*_enabled()` checks across all services
- **Secure Secrets**: All secrets are stored encrypted in the database (no environment variables)
- **Error Handling**: Consistent exceptions for configuration issues

## Architecture

### Configuration Models

The following singleton configuration models are supported:

1. **GitHubConfiguration** - GitHub App integration settings
2. **WeaviateConfiguration** - Weaviate vector database settings
3. **GooglePSEConfiguration** - Google Programmable Search Engine settings
4. **GraphAPIConfiguration** - Microsoft Graph API settings
5. **ZammadConfiguration** - Zammad ticketing system settings

All configuration models:
- Inherit from `SingletonModel` base class
- Are limited to one instance per model (enforced at database level)
- Support encrypted fields for sensitive data (API keys, secrets, etc.)
- Have an `enabled` boolean field for feature toggling

### Singleton Pattern

Each configuration model uses the singleton pattern to ensure only one configuration exists:

```python
class GitHubConfiguration(SingletonModel):
    app_id = models.CharField(max_length=255, blank=True)
    installation_id = models.CharField(max_length=255, blank=True)
    private_key = EncryptedCharField(max_length=5000, blank=True)
    webhook_secret = EncryptedCharField(max_length=500, blank=True)
    enabled = models.BooleanField(default=False)
```

The `SingletonModel` base class:
- Forces `pk=1` for all instances
- Provides a `load()` class method for easy access
- Prevents deletion of the singleton instance

## API Reference

### Core Functions

#### `get_singleton(model_cls)`

Loads a singleton configuration object with caching.

**Parameters:**
- `model_cls` - The Django model class to load (must be a singleton model)

**Returns:**
- The singleton instance or `None` if not configured

**Example:**
```python
from core.services.config import get_singleton
from core.models import GitHubConfiguration

config = get_singleton(GitHubConfiguration)
if config:
    print(config.app_id)
```

#### `invalidate_singleton(model_cls)`

Invalidates the cache for a singleton configuration. Should be called when configuration is updated (e.g., from Django admin).

**Parameters:**
- `model_cls` - The Django model class to invalidate

**Example:**
```python
from core.services.config import invalidate_singleton
from core.models import GitHubConfiguration

# After updating config in admin
invalidate_singleton(GitHubConfiguration)
```

### Configuration Getters

Each configuration type has a dedicated getter function:

| Function | Returns | Description |
|----------|---------|-------------|
| `get_github_config()` | `GitHubConfiguration \| None` | Get GitHub configuration |
| `get_weaviate_config()` | `WeaviateConfiguration \| None` | Get Weaviate configuration |
| `get_google_pse_config()` | `GooglePSEConfiguration \| None` | Get Google PSE configuration |
| `get_graph_config()` | `GraphAPIConfiguration \| None` | Get Graph API configuration |
| `get_zammad_config()` | `ZammadConfiguration \| None` | Get Zammad configuration |

**Example:**
```python
from core.services.config import get_github_config

config = get_github_config()
if config and config.enabled:
    # Use GitHub API
    pass
```

### Feature Flag Checks

Each configuration type has a feature flag check function:

| Function | Returns | Description |
|----------|---------|-------------|
| `is_github_enabled()` | `bool` | Check if GitHub integration is enabled |
| `is_weaviate_enabled()` | `bool` | Check if Weaviate integration is enabled |
| `is_google_pse_enabled()` | `bool` | Check if Google PSE integration is enabled |
| `is_graph_enabled()` | `bool` | Check if Graph API integration is enabled |
| `is_zammad_enabled()` | `bool` | Check if Zammad integration is enabled |

A service is considered "enabled" if:
1. Configuration exists in the database
2. The `enabled` field is `True`

**Example:**
```python
from core.services.config import is_github_enabled

if is_github_enabled():
    # Initialize GitHub client
    pass
else:
    # Skip GitHub integration
    pass
```

## Caching

### Cache Mechanism

The configuration service uses Django's cache framework with the following settings:

- **Backend**: `django.core.cache.backends.locmem.LocMemCache` (in-memory)
- **TTL**: 60 seconds by default
- **Cache Keys**: `agira_config:{ModelClassName}`

### Cache Behavior

1. **First Access**: Queries database and stores result in cache
2. **Subsequent Accesses**: Returns cached value (within TTL window)
3. **Cache Miss**: Re-queries database and updates cache
4. **Null Results**: Even `None` results are cached to avoid repeated queries

### Cache Invalidation

Cache is automatically invalidated:
- After TTL expires (60 seconds)
- Manually via `invalidate_singleton(model_cls)`

**Best Practice**: Call `invalidate_singleton()` from Django admin save hooks:

```python
from django.contrib import admin
from core.models import GitHubConfiguration
from core.services.config import invalidate_singleton

@admin.register(GitHubConfiguration)
class GitHubConfigurationAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        invalidate_singleton(GitHubConfiguration)
```

## Error Handling

The service layer provides consistent exceptions for error handling:

### Exception Hierarchy

```
Exception
  └── ServiceError
       ├── ServiceNotConfigured
       └── ServiceDisabled
```

### Exception Classes

#### `ServiceError`

Base exception for all service-related errors.

**Example:**
```python
from core.services.exceptions import ServiceError

try:
    # Service operation
    pass
except ServiceError as e:
    logger.error(f"Service error: {e}")
```

#### `ServiceNotConfigured`

Raised when a service is enabled but configuration is incomplete or missing.

**Example:**
```python
from core.services.exceptions import ServiceNotConfigured
from core.services.config import get_graph_config

config = get_graph_config()
if not config:
    raise ServiceNotConfigured("Graph API configuration not found")

if not config.client_id:
    raise ServiceNotConfigured("Graph API client_id is required")
```

#### `ServiceDisabled`

Raised when attempting to use a service that is explicitly disabled.

**Example:**
```python
from core.services.exceptions import ServiceDisabled
from core.services.config import is_weaviate_enabled

if not is_weaviate_enabled():
    raise ServiceDisabled("Weaviate integration is disabled")
```

## Usage Patterns

### Pattern 1: Simple Feature Check

```python
from core.services.config import is_github_enabled

def sync_issues():
    if not is_github_enabled():
        return  # Skip if disabled
    
    # Perform GitHub sync
    pass
```

### Pattern 2: Get Configuration with Validation

```python
from core.services.config import get_weaviate_config
from core.services.exceptions import ServiceNotConfigured, ServiceDisabled

def init_weaviate_client():
    config = get_weaviate_config()
    
    if not config:
        raise ServiceNotConfigured("Weaviate not configured")
    
    if not config.enabled:
        raise ServiceDisabled("Weaviate is disabled")
    
    if not config.url:
        raise ServiceNotConfigured("Weaviate URL is required")
    
    # Initialize client with config
    return WeaviateClient(url=config.url, api_key=config.api_key)
```

### Pattern 3: Graceful Degradation

```python
from core.services.config import is_google_pse_enabled, get_google_pse_config

def search(query):
    if is_google_pse_enabled():
        config = get_google_pse_config()
        # Use Google PSE for search
        return google_pse_search(query, config)
    else:
        # Fall back to local search
        return local_search(query)
```

## Production Considerations

### Security

- All secrets (API keys, tokens, private keys) are stored using `EncryptedCharField`
- Encryption key is managed via `FIELD_ENCRYPTION_KEY` setting
- **Never** commit encryption keys to version control
- Rotate encryption keys periodically in production

### Performance

- Cache TTL is set to 60 seconds by default
- Consider using Redis or Memcached in production for multi-server deployments
- Monitor cache hit rates to optimize TTL
- Configuration changes may take up to 60 seconds to propagate

### Scaling

For production deployments with multiple application servers:

1. **Update Cache Backend** in `settings.py`:
   ```python
   CACHES = {
       'default': {
           'BACKEND': 'django.core.cache.backends.redis.RedisCache',
           'LOCATION': 'redis://127.0.0.1:6379/1',
       }
   }
   ```

2. **Install Redis**:
   ```bash
   pip install redis django-redis
   ```

3. **Configure Cache Invalidation** to broadcast across all servers

## Testing

The configuration service includes comprehensive test coverage:

- Unit tests for all public APIs
- Cache behavior tests
- Feature flag tests
- Exception tests

Run tests with:
```bash
python manage.py test core.services.test_config
```

## Future Enhancements

Planned improvements:

1. **Signal-Based Cache Invalidation**: Automatically invalidate cache on model save
2. **Configuration Versioning**: Track configuration changes over time
3. **Configuration Validation**: Add validation rules for required fields
4. **Admin UI Improvements**: Better feedback when configurations are incomplete
5. **Monitoring**: Add metrics for configuration access patterns

## References

- Django Cache Framework: https://docs.djangoproject.com/en/stable/topics/cache/
- Django Singleton Pattern: https://steelkiwi.com/blog/practical-application-singleton-design-pattern/
- Encrypted Model Fields: https://pypi.org/project/django-encrypted-model-fields/
