"""
Tests for the AgentCacheService class.
"""

import hashlib
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, override_settings

from core.services.agents.cache import AgentCacheService, DEFAULT_TTL_SECONDS


class AgentCacheServiceTestCase(TestCase):
    """Test cases for AgentCacheService functionality."""
    
    @override_settings(REDIS_CACHE_ENABLED=False)
    def test_cache_disabled_when_redis_not_enabled(self):
        """Test that cache is disabled when REDIS_CACHE_ENABLED is False."""
        cache_service = AgentCacheService()
        
        self.assertFalse(cache_service._cache_enabled)
        self.assertIsNone(cache_service._redis_client)
    
    @override_settings(
        REDIS_CACHE_ENABLED=True,
        REDIS_CACHE_HOST='invalid-host',
        REDIS_CACHE_PORT=6379,
        REDIS_CACHE_DB=0,
        REDIS_CACHE_PASSWORD=None,
        REDIS_CACHE_SOCKET_TIMEOUT=1,
        REDIS_CACHE_SOCKET_CONNECT_TIMEOUT=1
    )
    def test_cache_disabled_on_redis_connection_failure(self):
        """Test that cache is disabled when Redis connection fails."""
        cache_service = AgentCacheService()
        
        # Should fail to connect and disable cache
        self.assertFalse(cache_service._cache_enabled)
        self.assertIsNone(cache_service._redis_client)
    
    def test_build_cache_key_format(self):
        """Test that cache key is built with correct format."""
        cache_service = AgentCacheService()
        
        agent_name = "test-agent"
        input_text = "Hello, world!"
        agent_version = 1
        
        cache_key = cache_service.build_cache_key(agent_name, input_text, agent_version)
        
        # Calculate expected hash
        expected_hash = hashlib.sha256(input_text.encode('utf-8')).hexdigest()
        expected_key = f"aiagent:{agent_name}:v{agent_version}:{expected_hash}"
        
        self.assertEqual(cache_key, expected_key)
    
    def test_build_cache_key_deterministic(self):
        """Test that same input produces same cache key."""
        cache_service = AgentCacheService()
        
        agent_name = "test-agent"
        input_text = "Test input text"
        agent_version = 1
        
        key1 = cache_service.build_cache_key(agent_name, input_text, agent_version)
        key2 = cache_service.build_cache_key(agent_name, input_text, agent_version)
        
        self.assertEqual(key1, key2)
    
    def test_build_cache_key_different_agents(self):
        """Test that same input with different agents produces different keys."""
        cache_service = AgentCacheService()
        
        input_text = "Same input"
        agent_version = 1
        
        key1 = cache_service.build_cache_key("agent-1", input_text, agent_version)
        key2 = cache_service.build_cache_key("agent-2", input_text, agent_version)
        
        self.assertNotEqual(key1, key2)
    
    def test_build_cache_key_different_versions(self):
        """Test that same input with different versions produces different keys."""
        cache_service = AgentCacheService()
        
        agent_name = "test-agent"
        input_text = "Same input"
        
        key1 = cache_service.build_cache_key(agent_name, input_text, agent_version=1)
        key2 = cache_service.build_cache_key(agent_name, input_text, agent_version=2)
        
        self.assertNotEqual(key1, key2)
    
    def test_build_cache_key_different_input(self):
        """Test that different input produces different keys."""
        cache_service = AgentCacheService()
        
        agent_name = "test-agent"
        agent_version = 1
        
        key1 = cache_service.build_cache_key(agent_name, "Input 1", agent_version)
        key2 = cache_service.build_cache_key(agent_name, "Input 2", agent_version)
        
        self.assertNotEqual(key1, key2)
    
    def test_parse_cache_config_with_full_config(self):
        """Test parsing cache config when all fields are present."""
        cache_service = AgentCacheService()
        
        agent_data = {
            'name': 'test-agent',
            'cache': {
                'enabled': True,
                'ttl_seconds': 3600,
                'key_strategy': 'content_hash',
                'agent_version': 2
            }
        }
        
        config = cache_service.parse_cache_config(agent_data)
        
        self.assertTrue(config['enabled'])
        self.assertEqual(config['ttl_seconds'], 3600)
        self.assertEqual(config['key_strategy'], 'content_hash')
        self.assertEqual(config['agent_version'], 2)
    
    def test_parse_cache_config_with_defaults(self):
        """Test parsing cache config applies defaults when fields are missing."""
        cache_service = AgentCacheService()
        
        # Agent with no cache block
        agent_data = {
            'name': 'test-agent'
        }
        
        config = cache_service.parse_cache_config(agent_data)
        
        self.assertFalse(config['enabled'])
        self.assertEqual(config['ttl_seconds'], DEFAULT_TTL_SECONDS)
        self.assertEqual(config['key_strategy'], 'content_hash')
        self.assertEqual(config['agent_version'], 1)
    
    def test_parse_cache_config_partial(self):
        """Test parsing cache config with partial configuration."""
        cache_service = AgentCacheService()
        
        agent_data = {
            'name': 'test-agent',
            'cache': {
                'enabled': True
                # Other fields missing
            }
        }
        
        config = cache_service.parse_cache_config(agent_data)
        
        self.assertTrue(config['enabled'])
        self.assertEqual(config['ttl_seconds'], DEFAULT_TTL_SECONDS)
        self.assertEqual(config['key_strategy'], 'content_hash')  # Default
        self.assertEqual(config['agent_version'], 1)  # Default
    
    def test_is_cache_enabled_no_redis(self):
        """Test is_cache_enabled returns False when Redis is not available."""
        cache_service = AgentCacheService()
        cache_service._cache_enabled = False
        cache_service._redis_client = None
        
        cache_config = {'enabled': True}
        
        self.assertFalse(cache_service.is_cache_enabled(cache_config))
    
    def test_is_cache_enabled_no_agent_config(self):
        """Test is_cache_enabled returns False when agent has no cache config."""
        cache_service = AgentCacheService()
        cache_service._cache_enabled = True
        cache_service._redis_client = Mock()
        
        self.assertFalse(cache_service.is_cache_enabled(None))
    
    def test_is_cache_enabled_agent_disabled(self):
        """Test is_cache_enabled returns False when agent has cache disabled."""
        cache_service = AgentCacheService()
        cache_service._cache_enabled = True
        cache_service._redis_client = Mock()
        
        cache_config = {'enabled': False}
        
        self.assertFalse(cache_service.is_cache_enabled(cache_config))
    
    @patch('redis.Redis')
    @override_settings(
        REDIS_CACHE_ENABLED=True,
        REDIS_CACHE_HOST='localhost',
        REDIS_CACHE_PORT=6379,
        REDIS_CACHE_DB=0,
        REDIS_CACHE_PASSWORD=None,
        REDIS_CACHE_SOCKET_TIMEOUT=5,
        REDIS_CACHE_SOCKET_CONNECT_TIMEOUT=5
    )
    def test_is_cache_enabled_fully_enabled(self, mock_redis):
        """Test is_cache_enabled returns True when everything is enabled."""
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_redis.return_value = mock_client
        
        cache_service = AgentCacheService()
        cache_config = {'enabled': True}
        
        self.assertTrue(cache_service.is_cache_enabled(cache_config))
    
    @patch('redis.Redis')
    @override_settings(
        REDIS_CACHE_ENABLED=True,
        REDIS_CACHE_HOST='localhost',
        REDIS_CACHE_PORT=6379,
        REDIS_CACHE_DB=0,
        REDIS_CACHE_PASSWORD=None,
        REDIS_CACHE_SOCKET_TIMEOUT=5,
        REDIS_CACHE_SOCKET_CONNECT_TIMEOUT=5
    )
    def test_get_returns_cached_value(self, mock_redis):
        """Test get method returns cached value when present."""
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_client.get.return_value = "Cached response"
        mock_redis.return_value = mock_client
        
        cache_service = AgentCacheService()
        result = cache_service.get("test-key")
        
        self.assertEqual(result, "Cached response")
        mock_client.get.assert_called_once_with("test-key")
    
    @patch('redis.Redis')
    @override_settings(
        REDIS_CACHE_ENABLED=True,
        REDIS_CACHE_HOST='localhost',
        REDIS_CACHE_PORT=6379,
        REDIS_CACHE_DB=0,
        REDIS_CACHE_PASSWORD=None,
        REDIS_CACHE_SOCKET_TIMEOUT=5,
        REDIS_CACHE_SOCKET_CONNECT_TIMEOUT=5
    )
    def test_get_returns_none_on_miss(self, mock_redis):
        """Test get method returns None when key not found."""
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_client.get.return_value = None
        mock_redis.return_value = mock_client
        
        cache_service = AgentCacheService()
        result = cache_service.get("nonexistent-key")
        
        self.assertIsNone(result)
    
    @patch('redis.Redis')
    @override_settings(
        REDIS_CACHE_ENABLED=True,
        REDIS_CACHE_HOST='localhost',
        REDIS_CACHE_PORT=6379,
        REDIS_CACHE_DB=0,
        REDIS_CACHE_PASSWORD=None,
        REDIS_CACHE_SOCKET_TIMEOUT=5,
        REDIS_CACHE_SOCKET_CONNECT_TIMEOUT=5
    )
    def test_get_returns_none_on_error(self, mock_redis):
        """Test get method returns None and logs warning on Redis error."""
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_client.get.side_effect = Exception("Redis error")
        mock_redis.return_value = mock_client
        
        cache_service = AgentCacheService()
        
        with self.assertLogs('core.services.agents.cache', level='WARNING') as logs:
            result = cache_service.get("test-key")
        
        self.assertIsNone(result)
        self.assertTrue(any('Redis GET error' in log for log in logs.output))
    
    @patch('redis.Redis')
    @override_settings(
        REDIS_CACHE_ENABLED=True,
        REDIS_CACHE_HOST='localhost',
        REDIS_CACHE_PORT=6379,
        REDIS_CACHE_DB=0,
        REDIS_CACHE_PASSWORD=None,
        REDIS_CACHE_SOCKET_TIMEOUT=5,
        REDIS_CACHE_SOCKET_CONNECT_TIMEOUT=5
    )
    def test_set_stores_value_with_ttl(self, mock_redis):
        """Test set method stores value with TTL."""
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_redis.return_value = mock_client
        
        cache_service = AgentCacheService()
        result = cache_service.set("test-key", "test-value", 3600)
        
        self.assertTrue(result)
        mock_client.setex.assert_called_once_with("test-key", 3600, "test-value")
    
    @patch('redis.Redis')
    @override_settings(
        REDIS_CACHE_ENABLED=True,
        REDIS_CACHE_HOST='localhost',
        REDIS_CACHE_PORT=6379,
        REDIS_CACHE_DB=0,
        REDIS_CACHE_PASSWORD=None,
        REDIS_CACHE_SOCKET_TIMEOUT=5,
        REDIS_CACHE_SOCKET_CONNECT_TIMEOUT=5
    )
    def test_set_returns_false_on_error(self, mock_redis):
        """Test set method returns False and logs warning on Redis error."""
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_client.setex.side_effect = Exception("Redis error")
        mock_redis.return_value = mock_client
        
        cache_service = AgentCacheService()
        
        with self.assertLogs('core.services.agents.cache', level='WARNING') as logs:
            result = cache_service.set("test-key", "test-value", 3600)
        
        self.assertFalse(result)
        self.assertTrue(any('Redis SET error' in log for log in logs.output))
    
    def test_get_cached_response_when_cache_disabled(self):
        """Test get_cached_response returns None when cache is disabled."""
        cache_service = AgentCacheService()
        cache_service._cache_enabled = False
        
        cache_config = {'enabled': False}
        result = cache_service.get_cached_response("agent", "input", cache_config)
        
        self.assertIsNone(result)
    
    @patch('redis.Redis')
    @override_settings(
        REDIS_CACHE_ENABLED=True,
        REDIS_CACHE_HOST='localhost',
        REDIS_CACHE_PORT=6379,
        REDIS_CACHE_DB=0,
        REDIS_CACHE_PASSWORD=None,
        REDIS_CACHE_SOCKET_TIMEOUT=5,
        REDIS_CACHE_SOCKET_CONNECT_TIMEOUT=5
    )
    def test_get_cached_response_builds_key_correctly(self, mock_redis):
        """Test get_cached_response builds cache key with correct parameters."""
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_client.get.return_value = "cached"
        mock_redis.return_value = mock_client
        
        cache_service = AgentCacheService()
        cache_config = {
            'enabled': True,
            'agent_version': 2
        }
        
        result = cache_service.get_cached_response("test-agent", "input", cache_config)
        
        # Verify the key was built with correct version
        expected_hash = hashlib.sha256("input".encode('utf-8')).hexdigest()
        expected_key = f"aiagent:test-agent:v2:{expected_hash}"
        
        mock_client.get.assert_called_once_with(expected_key)
        self.assertEqual(result, "cached")
    
    @patch('redis.Redis')
    @override_settings(
        REDIS_CACHE_ENABLED=True,
        REDIS_CACHE_HOST='localhost',
        REDIS_CACHE_PORT=6379,
        REDIS_CACHE_DB=0,
        REDIS_CACHE_PASSWORD=None,
        REDIS_CACHE_SOCKET_TIMEOUT=5,
        REDIS_CACHE_SOCKET_CONNECT_TIMEOUT=5
    )
    def test_cache_response_stores_with_correct_ttl(self, mock_redis):
        """Test cache_response stores response with correct TTL."""
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_redis.return_value = mock_client
        
        cache_service = AgentCacheService()
        cache_config = {
            'enabled': True,
            'agent_version': 1,
            'ttl_seconds': 7200
        }
        
        result = cache_service.cache_response(
            "test-agent",
            "input",
            "response",
            cache_config
        )
        
        self.assertTrue(result)
        
        # Verify setex was called with correct TTL
        expected_hash = hashlib.sha256("input".encode('utf-8')).hexdigest()
        expected_key = f"aiagent:test-agent:v1:{expected_hash}"
        
        mock_client.setex.assert_called_once_with(expected_key, 7200, "response")
    
    def test_cache_response_when_cache_disabled(self):
        """Test cache_response returns False when cache is disabled."""
        cache_service = AgentCacheService()
        cache_service._cache_enabled = False
        
        cache_config = {'enabled': False}
        result = cache_service.cache_response("agent", "input", "response", cache_config)
        
        self.assertFalse(result)
