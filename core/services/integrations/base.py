"""
Base class for external service integrations.

Provides consistent patterns for:
- Configuration loading
- Enabled/disabled checks
- Configuration validation
- Logging
"""

import logging
from typing import Optional, Any

from core.services import config as config_service
from .errors import (
    IntegrationError,
    IntegrationDisabled,
    IntegrationNotConfigured,
    IntegrationAuthError,
    IntegrationRateLimited,
    IntegrationTemporaryError,
    IntegrationPermanentError,
)


class BaseIntegration:
    """
    Base class for external service integrations.
    
    Provides common functionality for all integrations:
    - Configuration loading via config service
    - Enabled/disabled checks
    - Configuration validation
    - Logging with proper namespace
    
    Subclasses should:
    - Set the `name` property
    - Implement `_get_config_model()` to return the config model class
    - Implement `_is_config_complete(config)` to validate configuration
    - Call `require_enabled()` or `require_config()` before API calls
    
    Example:
        class GitHubIntegration(BaseIntegration):
            name = "github"
            
            def _get_config_model(self):
                return GitHubConfiguration
            
            def _is_config_complete(self, config):
                return bool(config.github_token)
    """
    
    # Subclasses should set this
    name: str = None
    
    def __init__(self):
        """Initialize the integration."""
        if self.name is None:
            raise NotImplementedError(
                f"{self.__class__.__name__} must set 'name' property"
            )
        
        # Set up logger with namespace agira.integration.<name>
        self._logger = logging.getLogger(f"agira.integration.{self.name}")
        self._config_cache = None
    
    @property
    def logger(self) -> logging.Logger:
        """
        Get logger for this integration.
        
        Logger uses namespace: agira.integration.<name>
        
        Returns:
            Logger instance
        """
        return self._logger
    
    def _get_config_model(self):
        """
        Get the Django model class for this integration's configuration.
        
        Subclasses must implement this.
        
        Returns:
            Django model class
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _get_config_model()"
        )
    
    def _is_config_complete(self, config: Any) -> bool:
        """
        Check if configuration has all required fields.
        
        Subclasses must implement this to validate their specific
        configuration requirements.
        
        Args:
            config: Configuration object
            
        Returns:
            True if config is complete, False otherwise
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement _is_config_complete()"
        )
    
    def get_config(self) -> Optional[Any]:
        """
        Get configuration object for this integration.
        
        Uses the config service singleton loader with caching.
        
        Returns:
            Configuration object or None if not configured
        """
        if self._config_cache is None:
            model_class = self._get_config_model()
            self._config_cache = config_service.get_singleton(model_class)
        return self._config_cache
    
    def enabled(self) -> bool:
        """
        Check if this integration is enabled.
        
        Returns:
            True if integration is enabled, False otherwise
        """
        config = self.get_config()
        if config is None:
            return False
        return getattr(config, 'enabled', False)
    
    def require_enabled(self) -> None:
        """
        Ensure integration is enabled.
        
        Raises:
            IntegrationDisabled: If integration is disabled or not configured
        """
        if not self.enabled():
            raise IntegrationDisabled(
                f"{self.name} integration is disabled or not configured"
            )
    
    def require_config(self) -> Any:
        """
        Ensure integration is enabled and properly configured.
        
        Returns:
            Configuration object
            
        Raises:
            IntegrationDisabled: If integration is disabled
            IntegrationNotConfigured: If configuration is incomplete
        """
        self.require_enabled()
        
        config = self.get_config()
        if config is None or not self._is_config_complete(config):
            raise IntegrationNotConfigured(
                f"{self.name} integration is enabled but not properly configured"
            )
        
        return config
