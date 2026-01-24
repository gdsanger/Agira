"""
Integration Base Package

Provides base classes and utilities for external service integrations.

This package serves as the foundation for all external service integrations
in Agira (GitHub, Weaviate, Graph API, AI providers, etc.).

Key Components:
- errors.py: Integration-specific exceptions
- base.py: BaseIntegration class with config/enabled checks
- http.py: HTTP client with retry and error mapping
"""

from .errors import (
    IntegrationError,
    IntegrationDisabled,
    IntegrationNotConfigured,
    IntegrationAuthError,
    IntegrationRateLimited,
    IntegrationRateLimitError,  # Backward compatibility
    IntegrationTemporaryError,
    IntegrationPermanentError,
)
from .base import BaseIntegration, IntegrationBase
from .http import HTTPClient

__all__ = [
    # Exceptions
    'IntegrationError',
    'IntegrationDisabled',
    'IntegrationNotConfigured',
    'IntegrationAuthError',
    'IntegrationRateLimited',
    'IntegrationRateLimitError',  # Backward compatibility
    'IntegrationTemporaryError',
    'IntegrationPermanentError',
    # Classes
    'BaseIntegration',
    'IntegrationBase',  # Backward compatibility
    'HTTPClient',
]
