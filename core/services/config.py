"""
Core configuration service for Agira.

This module provides a centralized configuration layer that:
- Loads singleton configuration models with caching
- Provides consistent feature flag checking
- Handles secrets securely from the database
- Avoids database overhead through intelligent caching

All core services (Weaviate, AI, Graph, GitHub, Zammad, etc.) should use
this module to access their configuration.
"""

from typing import Optional, Type
from django.core.cache import cache
from django.db import models

from core.models import (
    GitHubConfiguration,
    WeaviateConfiguration,
    GooglePSEConfiguration,
    GraphAPIConfiguration,
    ZammadConfiguration,
)
from .exceptions import ServiceDisabled, ServiceNotConfigured


# Cache configuration
DEFAULT_CACHE_TTL = 60  # 60 seconds default TTL
CACHE_KEY_PREFIX = "agira_config"


def _get_cache_key(model_cls: Type[models.Model]) -> str:
    """Generate a cache key for a given model class."""
    return f"{CACHE_KEY_PREFIX}:{model_cls.__name__}"


def get_singleton(model_cls: Type[models.Model]) -> Optional[models.Model]:
    """
    Load a singleton configuration object with caching.
    
    This function retrieves the singleton instance for the given model class.
    Results are cached for DEFAULT_CACHE_TTL seconds to avoid excessive
    database queries.
    
    Args:
        model_cls: The Django model class to load (must be a singleton model)
        
    Returns:
        The singleton instance or None if not configured
        
    Example:
        >>> config = get_singleton(GitHubConfiguration)
        >>> if config:
        ...     print(config.app_id)
    """
    cache_key = _get_cache_key(model_cls)
    
    # Try to get from cache first
    cached_value = cache.get(cache_key)
    if cached_value is not None:
        return cached_value
    
    # Not in cache, fetch from database
    try:
        obj = model_cls.objects.first()
    except Exception:
        # Handle case where table doesn't exist yet (migrations)
        obj = None
    
    # Cache the result (even if None to avoid repeated DB queries)
    cache.set(cache_key, obj, DEFAULT_CACHE_TTL)
    
    return obj


def invalidate_singleton(model_cls: Type[models.Model]) -> None:
    """
    Invalidate the cache for a singleton configuration.
    
    This should be called when a configuration is updated (e.g., from Django admin).
    
    Args:
        model_cls: The Django model class to invalidate
        
    Example:
        >>> invalidate_singleton(GitHubConfiguration)
    """
    cache_key = _get_cache_key(model_cls)
    cache.delete(cache_key)


# GitHub Configuration
def get_github_config() -> Optional[GitHubConfiguration]:
    """
    Get the GitHub configuration.
    
    Returns:
        GitHubConfiguration instance or None if not configured
    """
    return get_singleton(GitHubConfiguration)


def is_github_enabled() -> bool:
    """
    Check if GitHub integration is enabled.
    
    Returns:
        True if GitHub is configured and enabled, False otherwise
    """
    config = get_github_config()
    return config is not None and config.enabled


# Weaviate Configuration
def get_weaviate_config() -> Optional[WeaviateConfiguration]:
    """
    Get the Weaviate configuration.
    
    Returns:
        WeaviateConfiguration instance or None if not configured
    """
    return get_singleton(WeaviateConfiguration)


def is_weaviate_enabled() -> bool:
    """
    Check if Weaviate integration is enabled.
    
    Returns:
        True if Weaviate is configured and enabled, False otherwise
    """
    config = get_weaviate_config()
    return config is not None and config.enabled


# Google PSE Configuration
def get_google_pse_config() -> Optional[GooglePSEConfiguration]:
    """
    Get the Google Programmable Search Engine configuration.
    
    Returns:
        GooglePSEConfiguration instance or None if not configured
    """
    return get_singleton(GooglePSEConfiguration)


def is_google_pse_enabled() -> bool:
    """
    Check if Google PSE integration is enabled.
    
    Returns:
        True if Google PSE is configured and enabled, False otherwise
    """
    config = get_google_pse_config()
    return config is not None and config.enabled


# Graph API Configuration
def get_graph_config() -> Optional[GraphAPIConfiguration]:
    """
    Get the Microsoft Graph API configuration.
    
    Returns:
        GraphAPIConfiguration instance or None if not configured
    """
    return get_singleton(GraphAPIConfiguration)


def is_graph_enabled() -> bool:
    """
    Check if Microsoft Graph API integration is enabled.
    
    Returns:
        True if Graph API is configured and enabled, False otherwise
    """
    config = get_graph_config()
    return config is not None and config.enabled


# Zammad Configuration
def get_zammad_config() -> Optional[ZammadConfiguration]:
    """
    Get the Zammad configuration.
    
    Returns:
        ZammadConfiguration instance or None if not configured
    """
    return get_singleton(ZammadConfiguration)


def is_zammad_enabled() -> bool:
    """
    Check if Zammad integration is enabled.
    
    Returns:
        True if Zammad is configured and enabled, False otherwise
    """
    config = get_zammad_config()
    return config is not None and config.enabled
