"""
Service-layer exceptions for consistent error handling across Agira.

These exceptions provide a consistent way to handle service configuration
and availability issues throughout the application.
"""


class ServiceError(Exception):
    """Base exception for all service-related errors."""
    pass


class ServiceNotConfigured(ServiceError):
    """
    Raised when a service is enabled but its configuration is incomplete or missing.
    
    Example:
        If Graph API is enabled but client_id is not set, this exception is raised.
    """
    pass


class ServiceDisabled(ServiceError):
    """
    Raised when attempting to use a service that is explicitly disabled.

    Example:
        If Weaviate integration is disabled in the configuration.
    """
    pass


class AIResponseFormatError(ServiceError):
    """
    Raised when an AI agent's response cannot be turned into usable output,
    e.g. it is empty or the JSON is malformed/truncated.

    This represents an expected, recoverable upstream hiccup (bad or
    incomplete LLM output) rather than a bug in Agira itself, so callers
    should surface it as a clear, actionable message instead of a generic
    server error.
    """
    pass
