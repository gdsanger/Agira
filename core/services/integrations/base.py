"""
Base classes and exceptions for external service integrations.
"""

from core.services.exceptions import ServiceError, ServiceNotConfigured, ServiceDisabled


# Integration-specific exceptions
class IntegrationError(ServiceError):
    """Base exception for all integration-related errors."""
    pass


class IntegrationDisabled(ServiceDisabled, IntegrationError):
    """Raised when attempting to use a disabled integration."""
    pass


class IntegrationNotConfigured(ServiceNotConfigured, IntegrationError):
    """Raised when integration is enabled but configuration is incomplete."""
    pass


class IntegrationAuthError(IntegrationError):
    """Raised when authentication with external service fails."""
    pass


class IntegrationRateLimitError(IntegrationError):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, message="Rate limit exceeded", retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


class IntegrationNotFoundError(IntegrationError):
    """Raised when requested resource is not found."""
    pass


class IntegrationValidationError(IntegrationError):
    """Raised when data validation fails."""
    pass


class IntegrationBase:
    """
    Abstract base class for external service integrations.
    
    Subclasses should:
    - Override is_enabled() and is_configured() methods
    - Call _check_availability() before making API calls
    - Use HTTP client from http.py for consistent error handling
    """
    
    def is_enabled(self) -> bool:
        """Check if the integration is enabled in configuration."""
        raise NotImplementedError("Subclasses must implement is_enabled()")
    
    def is_configured(self) -> bool:
        """Check if the integration has all required configuration."""
        raise NotImplementedError("Subclasses must implement is_configured()")
    
    def _check_availability(self):
        """
        Check if integration is available for use.
        
        Raises:
            IntegrationDisabled: If integration is disabled
            IntegrationNotConfigured: If integration is enabled but not configured
        """
        if not self.is_enabled():
            raise IntegrationDisabled(f"{self.__class__.__name__} is disabled")
        
        if not self.is_configured():
            raise IntegrationNotConfigured(
                f"{self.__class__.__name__} is enabled but not properly configured"
            )
