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
