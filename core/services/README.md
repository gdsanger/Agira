# Core Services

This directory contains the core service layer for Agira, providing centralized infrastructure and utilities for accessing external services and configuration.

## Contents

### `exceptions.py`
Defines consistent exception classes for service-layer error handling:
- `ServiceError` - Base exception for all service errors
- `ServiceNotConfigured` - Raised when service is enabled but config is incomplete
- `ServiceDisabled` - Raised when attempting to use a disabled service

### `config.py`
Central configuration service providing:
- Singleton configuration loading with caching (60s TTL)
- Feature flag checks (`is_*_enabled()` functions)
- Configuration getters (`get_*_config()` functions)
- Cache invalidation for admin updates

Supported configurations:
- GitHub (GitHubConfiguration)
- Weaviate (WeaviateConfiguration)
- Google PSE (GooglePSEConfiguration)
- Graph API (GraphAPIConfiguration)
- Zammad (ZammadConfiguration)

### `test_config.py`
Comprehensive test suite for the configuration service (27 tests covering all APIs).

## Usage

```python
from core.services.config import is_github_enabled, get_github_config
from core.services.exceptions import ServiceDisabled, ServiceNotConfigured

# Check if a service is enabled
if is_github_enabled():
    config = get_github_config()
    # Use configuration
else:
    raise ServiceDisabled("GitHub integration is disabled")
```

## Documentation

For detailed documentation, see: [docs/services/config.md](/docs/services/config.md)

## Future Services

Additional services will be added to this directory as needed:
- AI Provider service
- Graph service (Microsoft Graph API client)
- Weaviate service (Vector database client)
- GitHub service (GitHub API client)
- Zammad service (Ticketing system client)
