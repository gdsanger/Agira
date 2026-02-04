"""
Redis-based cache service for AI Agent responses.

Provides caching functionality for AI agents to reduce costs and latency.
Includes resilient error handling to ensure Redis failures don't break agent execution.
"""

import logging
import hashlib
import json
from typing import Optional, Dict, Any
from django.conf import settings

# Module-level logger
logger = logging.getLogger(__name__)

# Default cache TTL (90 days in seconds)
DEFAULT_TTL_SECONDS = 7776000


class AgentCacheService:
    """
    Service for caching AI agent responses in Redis.
    
    Features:
    - Content-based cache key generation with SHA256
    - Agent-specific namespacing with version support
    - TTL-based expiration
    - Resilient error handling (failures don't break agent execution)
    """
    
    def __init__(self):
        """Initialize the cache service with Redis connection."""
        self._redis_client = None
        self._cache_enabled = settings.REDIS_CACHE_ENABLED
        
        if self._cache_enabled:
            try:
                import redis
                self._redis_client = redis.Redis(
                    host=settings.REDIS_CACHE_HOST,
                    port=settings.REDIS_CACHE_PORT,
                    db=settings.REDIS_CACHE_DB,
                    password=settings.REDIS_CACHE_PASSWORD,
                    socket_timeout=settings.REDIS_CACHE_SOCKET_TIMEOUT,
                    socket_connect_timeout=settings.REDIS_CACHE_SOCKET_CONNECT_TIMEOUT,
                    decode_responses=True  # Automatically decode responses to strings
                )
                # Test connection
                self._redis_client.ping()
                logger.info("Redis cache connection established successfully")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis cache: {e}. Cache will be disabled.")
                self._redis_client = None
                self._cache_enabled = False
    
    def is_cache_enabled(self, agent_cache_config: Optional[Dict[str, Any]] = None) -> bool:
        """
        Check if caching is enabled for this request.
        
        Args:
            agent_cache_config: Agent's cache configuration from YAML
            
        Returns:
            True if cache is enabled and operational, False otherwise
        """
        # Global cache must be enabled
        if not self._cache_enabled or not self._redis_client:
            return False
        
        # If agent doesn't have cache config, caching is disabled
        if not agent_cache_config:
            return False
        
        # Check if agent has cache enabled
        return agent_cache_config.get('enabled', False)
    
    def build_cache_key(
        self,
        agent_name: str,
        input_text: str,
        agent_version: int = 1
    ) -> str:
        """
        Build a deterministic cache key using content hash.
        
        Key format: aiagent:{agent_name}:v{agent_version}:{sha256(input_text)}
        
        Args:
            agent_name: Name of the agent
            input_text: Input text to hash
            agent_version: Version of the agent (default: 1)
            
        Returns:
            Cache key string
        """
        # Create SHA256 hash of input text
        input_hash = hashlib.sha256(input_text.encode('utf-8')).hexdigest()
        
        # Build key with agent name, version, and content hash
        cache_key = f"aiagent:{agent_name}:v{agent_version}:{input_hash}"
        
        return cache_key
    
    def get(self, cache_key: str) -> Optional[str]:
        """
        Retrieve a cached response from Redis.
        
        Args:
            cache_key: Cache key to look up
            
        Returns:
            Cached response text or None if not found/error
        """
        if not self._redis_client:
            return None
        
        try:
            cached_value = self._redis_client.get(cache_key)
            if cached_value:
                logger.debug(f"Cache HIT for key: {cache_key}")
                return cached_value
            else:
                logger.debug(f"Cache MISS for key: {cache_key}")
                return None
        except Exception as e:
            logger.warning(f"Redis GET error for key {cache_key}: {e}. Treating as cache miss.")
            return None
    
    def set(
        self,
        cache_key: str,
        value: str,
        ttl_seconds: int
    ) -> bool:
        """
        Store a response in Redis cache with TTL.
        
        Args:
            cache_key: Cache key
            value: Response text to cache
            ttl_seconds: Time-to-live in seconds
            
        Returns:
            True if successfully cached, False otherwise
        """
        if not self._redis_client:
            return False
        
        try:
            # Use SETEX to set value with expiration in one atomic operation
            self._redis_client.setex(cache_key, ttl_seconds, value)
            logger.debug(f"Cached response with key: {cache_key}, TTL: {ttl_seconds}s")
            return True
        except Exception as e:
            logger.warning(f"Redis SET error for key {cache_key}: {e}")
            return False
    
    def parse_cache_config(self, agent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Parse and validate cache configuration from agent YAML.
        
        Args:
            agent_data: Agent configuration dictionary from YAML
            
        Returns:
            Cache configuration with defaults applied:
            {
                'enabled': bool,
                'ttl_seconds': int,
                'key_strategy': str,
                'agent_version': int
            }
        """
        cache_config = agent_data.get('cache', {})
        
        # Apply defaults
        return {
            'enabled': cache_config.get('enabled', False),
            'ttl_seconds': cache_config.get('ttl_seconds', DEFAULT_TTL_SECONDS),
            'key_strategy': cache_config.get('key_strategy', 'content_hash'),
            'agent_version': cache_config.get('agent_version', 1)
        }
    
    def get_cached_response(
        self,
        agent_name: str,
        input_text: str,
        cache_config: Dict[str, Any]
    ) -> Optional[str]:
        """
        High-level method to get cached response if available.
        
        Args:
            agent_name: Name of the agent
            input_text: Input text
            cache_config: Cache configuration from agent YAML
            
        Returns:
            Cached response or None
        """
        if not self.is_cache_enabled(cache_config):
            return None
        
        agent_version = cache_config.get('agent_version', 1)
        cache_key = self.build_cache_key(agent_name, input_text, agent_version)
        
        return self.get(cache_key)
    
    def cache_response(
        self,
        agent_name: str,
        input_text: str,
        response_text: str,
        cache_config: Dict[str, Any]
    ) -> bool:
        """
        High-level method to cache a response.
        
        Args:
            agent_name: Name of the agent
            input_text: Input text
            response_text: Response to cache
            cache_config: Cache configuration from agent YAML
            
        Returns:
            True if successfully cached, False otherwise
        """
        if not self.is_cache_enabled(cache_config):
            return False
        
        agent_version = cache_config.get('agent_version', 1)
        ttl_seconds = cache_config.get('ttl_seconds', DEFAULT_TTL_SECONDS)
        
        cache_key = self.build_cache_key(agent_name, input_text, agent_version)
        
        return self.set(cache_key, response_text, ttl_seconds)
