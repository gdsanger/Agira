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
    IntegrationRateLimitError,  # Backward compatibility
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
        # Make name check optional for backward compatibility
        # Subclasses that don't call super().__init__() won't trigger this
        if self.name is None and not hasattr(self, '_config'):
            # Only raise if this looks like a new-style integration
            # (no _config attribute means not using old pattern)
            pass  # Allow it for backward compatibility
        
        # Set up logger with namespace agira.integration.<name>
        # Only if name is set
        if self.name is not None:
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
        # Backward compatibility: create logger on demand if not initialized
        if not hasattr(self, '_logger'):
            if self.name is not None:
                self._logger = logging.getLogger(f"agira.integration.{self.name}")
            else:
                # Fallback to class name
                self._logger = logging.getLogger(f"agira.integration.{self.__class__.__name__}")
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
        # Initialize _config_cache if not present (backward compatibility)
        if not hasattr(self, '_config_cache'):
            self._config_cache = None
        
        if self._config_cache is None:
            # Check if subclass implements _get_config_model (new style)
            try:
                model_class = self._get_config_model()
                self._config_cache = config_service.get_singleton(model_class)
            except NotImplementedError:
                # Old style: subclass might have its own _get_config method
                # In that case, just return None and let the subclass handle it
                return None
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
    
    # Backward compatibility methods
    # These are for old-style integrations that override them
    def is_enabled(self) -> bool:
        """
        Check if integration is enabled (backward compatibility).
        
        Old-style integrations should override this method.
        New-style integrations should use enabled() instead.
        
        Default implementation delegates to enabled() for new-style integrations.
        """
        # If this method wasn't overridden by subclass, use new-style enabled()
        # Check if the method on self.__class__ is different from BaseIntegration
        if self.__class__.is_enabled is BaseIntegration.is_enabled:
            # Not overridden, use new style
            return self.enabled()
        # This shouldn't be reached if subclass properly overrides
        return False
    
    def is_configured(self) -> bool:
        """
        Check if integration is configured (backward compatibility).
        
        Old-style integrations should override this method.
        New-style integrations don't need this.
        
        Default implementation works with new-style integrations.
        """
        # If this method wasn't overridden by subclass, try new-style
        if self.__class__.is_configured is BaseIntegration.is_configured:
            config = self.get_config()
            if config is None:
                return False
            try:
                return self._is_config_complete(config)
            except NotImplementedError:
                return True
        # This shouldn't be reached if subclass properly overrides
        return False
    
    def _check_availability(self) -> None:
        """
        Check availability (backward compatibility).
        
        Uses the subclass's is_enabled() and is_configured() methods,
        which old-style integrations override.
        """
        if not self.is_enabled():
            raise IntegrationDisabled(
                f"{self.__class__.__name__} integration is disabled"
            )
        
        if not self.is_configured():
            raise IntegrationNotConfigured(
                f"{self.__class__.__name__} integration is enabled but not properly configured"
            )


# Backward compatibility alias
IntegrationBase = BaseIntegration
