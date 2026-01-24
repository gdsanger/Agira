"""
Integration Base Package

Provides base classes and utilities for external service integrations.
"""

from .base import (
    IntegrationBase,
    IntegrationError,
    IntegrationDisabled,
    IntegrationNotConfigured,
    IntegrationAuthError,
    IntegrationRateLimitError,
    IntegrationNotFoundError,
    IntegrationValidationError,
)

__all__ = [
    'IntegrationBase',
    'IntegrationError',
    'IntegrationDisabled',
    'IntegrationNotConfigured',
    'IntegrationAuthError',
    'IntegrationRateLimitError',
    'IntegrationNotFoundError',
    'IntegrationValidationError',
]
