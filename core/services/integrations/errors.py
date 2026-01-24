"""
Integration-specific exceptions for consistent error handling.

These exceptions provide a unified way to handle errors across all external
service integrations (GitHub, Weaviate, Graph API, AI providers, etc.).

Design principles:
- Never include secrets or tokens in exception messages
- Map HTTP status codes consistently
- Distinguish between temporary and permanent failures
- Support retry decisions
"""


class IntegrationError(Exception):
    """
    Base exception for all integration-related errors.
    
    All integration exceptions inherit from this class, allowing
    consumers to catch all integration errors with a single except clause.
    """
    pass


class IntegrationDisabled(IntegrationError):
    """
    Raised when attempting to use a disabled integration.
    
    This indicates the integration is explicitly disabled in configuration
    and should not be used. This is not an error condition but a
    configuration state.
    
    Example:
        If GitHub integration is disabled via admin panel.
    """
    pass


class IntegrationNotConfigured(IntegrationError):
    """
    Raised when integration is enabled but configuration is incomplete.
    
    This indicates the integration is enabled but lacks required
    configuration (API keys, endpoints, etc.).
    
    Example:
        If Weaviate is enabled but URL is not set.
    """
    pass


class IntegrationAuthError(IntegrationError):
    """
    Raised when authentication with external service fails.
    
    Typically corresponds to HTTP 401/403 errors.
    Do not retry automatically.
    
    Example:
        Invalid API token, expired credentials, insufficient permissions.
    """
    pass


class IntegrationRateLimited(IntegrationError):
    """
    Raised when rate limit is exceeded.
    
    Corresponds to HTTP 429 errors.
    Can be retried after waiting for retry_after seconds.
    
    Attributes:
        retry_after: Optional seconds to wait before retrying
    """
    
    def __init__(self, message="Rate limit exceeded", retry_after=None):
        """
        Initialize rate limit error.
        
        Args:
            message: Error message (no secrets!)
            retry_after: Optional seconds to wait before retrying
        """
        super().__init__(message)
        self.retry_after = retry_after


class IntegrationTemporaryError(IntegrationError):
    """
    Raised for temporary errors that may succeed on retry.
    
    Typically corresponds to:
    - HTTP 5xx server errors
    - Network timeouts
    - Connection errors
    
    These errors should be retried with exponential backoff.
    
    Example:
        Service temporarily unavailable, timeout, network error.
    """
    pass


class IntegrationPermanentError(IntegrationError):
    """
    Raised for permanent errors that should not be retried.
    
    Typically corresponds to HTTP 4xx client errors (except 429).
    These indicate invalid requests, validation failures, or
    resources that don't exist.
    
    Do not retry automatically.
    
    Example:
        Invalid request format, validation error, resource not found.
    """
    pass
