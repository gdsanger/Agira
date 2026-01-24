"""
Weaviate client management for Agira.

This module provides client initialization and connection management
for Weaviate vector database integration.
"""

import logging
from typing import Optional
import weaviate
from weaviate.classes.init import Auth

from core.services.config import get_weaviate_config
from core.services.exceptions import ServiceNotConfigured, ServiceDisabled

logger = logging.getLogger(__name__)


def get_client() -> weaviate.WeaviateClient:
    """
    Get a configured Weaviate client instance.
    
    This function loads configuration from the database singleton and
    creates a client with appropriate authentication and settings.
    
    Returns:
        Configured Weaviate client instance
        
    Raises:
        ServiceDisabled: If Weaviate is explicitly disabled
        ServiceNotConfigured: If Weaviate is enabled but URL is missing
        
    Example:
        >>> client = get_client()
        >>> # Use client for operations
        >>> client.close()
    """
    config = get_weaviate_config()
    
    # Check if service is disabled
    if config is None or not config.enabled:
        raise ServiceDisabled("Weaviate service is not enabled")
    
    # Check if URL is configured
    if not config.url:
        raise ServiceNotConfigured("Weaviate URL is not configured")
    
    logger.debug(f"Connecting to Weaviate at {config.url}")
    
    # Parse URL components
    from urllib.parse import urlparse
    parsed = urlparse(config.url)
    
    # Extract host and port
    http_secure = parsed.scheme == "https"
    http_host = parsed.hostname or parsed.netloc
    http_port = parsed.port or (443 if http_secure else 80)
    
    # Build client with optional authentication
    if config.api_key:
        client = weaviate.connect_to_custom(
            http_host=http_host,
            http_port=http_port,
            http_secure=http_secure,
            auth_credentials=Auth.api_key(config.api_key),
        )
    else:
        client = weaviate.connect_to_custom(
            http_host=http_host,
            http_port=http_port,
            http_secure=http_secure,
        )
    
    return client


def is_available() -> bool:
    """
    Check if Weaviate service is available and configured.
    
    This is a lightweight check that doesn't attempt to connect to Weaviate,
    it only checks if the configuration is valid.
    
    Returns:
        True if Weaviate is configured and enabled, False otherwise
        
    Example:
        >>> if is_available():
        ...     client = get_client()
        ...     # Use client
    """
    try:
        config = get_weaviate_config()
        return config is not None and config.enabled and bool(config.url)
    except Exception:
        return False
