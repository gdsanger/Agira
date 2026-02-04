"""
Tests for the AgentService class.
"""

import os
import tempfile
import shutil
import yaml
from pathlib import Path
from unittest.mock import Mock, patch
from django.test import TestCase, override_settings
from django.conf import settings

from core.services.agents.agent_service import AgentService


class AgentServiceTestCase(TestCase):
    """Test cases for AgentService functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary directory for test agents
        self.test_agents_dir = Path(tempfile.mkdtemp())
        
        # Create agent service instance
        self.agent_service = AgentService()
        # Override the agents directory for testing
        self.agent_service.agents_dir = self.test_agents_dir
    
    def tearDown(self):
        """Clean up after each test."""
        # Remove temporary directory
        if self.test_agents_dir.exists():
            shutil.rmtree(self.test_agents_dir)
    
    def test_save_new_agent_creates_file(self):
        """Test that saving a new agent creates the file when it doesn't exist."""
        filename = 'test-agent.yml'
        agent_data = {
            'name': 'Test Agent',
            'description': 'A test agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'role': 'Test role',
            'task': 'Test task'
        }
        
        # Verify file doesn't exist before saving
        file_path = self.test_agents_dir / filename
        self.assertFalse(file_path.exists(), "File should not exist before saving")
        
        # Save the agent
        self.agent_service.save_agent(filename, agent_data)
        
        # Verify file was created
        self.assertTrue(file_path.exists(), "File should exist after saving")
        
        # Verify content can be loaded
        loaded_agent = self.agent_service.get_agent(filename)
        self.assertIsNotNone(loaded_agent)
        self.assertEqual(loaded_agent['name'], 'Test Agent')
        self.assertEqual(loaded_agent['description'], 'A test agent')
        self.assertEqual(loaded_agent['provider'], 'openai')
        self.assertEqual(loaded_agent['model'], 'gpt-3.5-turbo')
    
    def test_save_agent_creates_directory_if_not_exists(self):
        """Test that saving an agent creates the agents directory if it doesn't exist."""
        # Remove the test agents directory
        shutil.rmtree(self.test_agents_dir)
        self.assertFalse(self.test_agents_dir.exists(), "Directory should not exist")
        
        filename = 'test-agent.yml'
        agent_data = {
            'name': 'Test Agent',
            'description': 'A test agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo'
        }
        
        # Save the agent - should create directory
        self.agent_service.save_agent(filename, agent_data)
        
        # Verify directory was created
        self.assertTrue(self.test_agents_dir.exists(), "Directory should be created")
        
        # Verify file was created
        file_path = self.test_agents_dir / filename
        self.assertTrue(file_path.exists(), "File should exist after saving")
    
    def test_save_agent_updates_existing_file(self):
        """Test that saving an agent updates an existing file."""
        filename = 'test-agent.yml'
        initial_data = {
            'name': 'Initial Agent',
            'description': 'Initial description',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo'
        }
        
        # Create initial agent
        self.agent_service.save_agent(filename, initial_data)
        
        # Update the agent
        updated_data = {
            'name': 'Updated Agent',
            'description': 'Updated description',
            'provider': 'gemini',
            'model': 'gemini-pro'
        }
        self.agent_service.save_agent(filename, updated_data)
        
        # Verify updated content
        loaded_agent = self.agent_service.get_agent(filename)
        self.assertEqual(loaded_agent['name'], 'Updated Agent')
        self.assertEqual(loaded_agent['description'], 'Updated description')
        self.assertEqual(loaded_agent['provider'], 'gemini')
        self.assertEqual(loaded_agent['model'], 'gemini-pro')
    
    def test_save_agent_with_parameters(self):
        """Test that saving an agent with parameters works correctly."""
        filename = 'test-agent-params.yml'
        agent_data = {
            'name': 'Test Agent with Params',
            'description': 'An agent with parameters',
            'provider': 'openai',
            'model': 'gpt-4',
            'role': 'Test role',
            'task': 'Test task',
            'parameters': {
                'temperature': {
                    'type': 'float',
                    'description': 'Temperature parameter',
                    'required': True
                },
                'max_tokens': {
                    'type': 'integer',
                    'description': 'Max tokens parameter',
                    'required': False
                }
            }
        }
        
        # Save the agent
        self.agent_service.save_agent(filename, agent_data)
        
        # Verify content
        loaded_agent = self.agent_service.get_agent(filename)
        self.assertIsNotNone(loaded_agent)
        self.assertIn('parameters', loaded_agent)
        self.assertIn('temperature', loaded_agent['parameters'])
        self.assertIn('max_tokens', loaded_agent['parameters'])
    
    def test_get_agent_returns_none_for_nonexistent_file(self):
        """Test that get_agent returns None for a non-existent agent file."""
        result = self.agent_service.get_agent('nonexistent-agent.yml')
        self.assertIsNone(result)
    
    def test_list_agents_returns_empty_for_empty_directory(self):
        """Test that list_agents returns an empty list when no agents exist."""
        agents = self.agent_service.list_agents()
        self.assertEqual(len(agents), 0)
    
    def test_list_agents_returns_all_agents(self):
        """Test that list_agents returns all agent files."""
        # Create multiple agents
        agent1_data = {'name': 'Agent 1', 'provider': 'openai', 'model': 'gpt-3.5-turbo'}
        agent2_data = {'name': 'Agent 2', 'provider': 'gemini', 'model': 'gemini-pro'}
        
        self.agent_service.save_agent('agent1.yml', agent1_data)
        self.agent_service.save_agent('agent2.yml', agent2_data)
        
        # List agents
        agents = self.agent_service.list_agents()
        
        # Verify both agents are listed
        self.assertEqual(len(agents), 2)
        agent_names = [a['name'] for a in agents]
        self.assertIn('Agent 1', agent_names)
        self.assertIn('Agent 2', agent_names)
    
    def test_delete_agent_removes_file(self):
        """Test that delete_agent removes the agent file."""
        filename = 'test-agent-delete.yml'
        agent_data = {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo'
        }
        
        # Create agent
        self.agent_service.save_agent(filename, agent_data)
        file_path = self.test_agents_dir / filename
        self.assertTrue(file_path.exists())
        
        # Delete agent
        result = self.agent_service.delete_agent(filename)
        
        # Verify deletion
        self.assertTrue(result)
        self.assertFalse(file_path.exists())
    
    def test_delete_nonexistent_agent_returns_false(self):
        """Test that deleting a non-existent agent returns False."""
        result = self.agent_service.delete_agent('nonexistent.yml')
        self.assertFalse(result)
    
    def test_save_agent_removes_filename_from_data(self):
        """Test that save_agent removes the 'filename' key from agent data."""
        filename = 'test-agent-no-filename.yml'
        agent_data = {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'filename': 'should-not-be-saved.yml'  # This should be removed
        }
        
        # Save agent
        self.agent_service.save_agent(filename, agent_data)
        
        # Load agent and verify 'filename' is not in the file
        # but is added when loading
        loaded_agent = self.agent_service.get_agent(filename)
        
        # The loaded agent should have 'filename' added by get_agent
        self.assertEqual(loaded_agent['filename'], filename)
        
        # Read the raw file to verify 'filename' was not saved
        file_path = self.test_agents_dir / filename
        with open(file_path, 'r', encoding='utf-8') as f:
            raw_data = yaml.safe_load(f)
        
        # Raw data should not contain 'filename'
        self.assertNotIn('filename', raw_data)


class AgentServiceCacheIntegrationTestCase(TestCase):
    """Integration tests for AgentService with cache functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary directory for test agents
        self.test_agents_dir = Path(tempfile.mkdtemp())
        
        # Create agent service instance
        self.agent_service = AgentService()
        # Override the agents directory for testing
        self.agent_service.agents_dir = self.test_agents_dir
    
    def tearDown(self):
        """Clean up after each test."""
        # Remove temporary directory
        if self.test_agents_dir.exists():
            shutil.rmtree(self.test_agents_dir)
    
    def test_agent_without_cache_config_uses_no_cache(self):
        """Test that agent without cache config doesn't use cache."""
        # Create agent without cache config
        agent_data = {
            'name': 'No Cache Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'role': 'Test',
            'task': 'Test task'
        }
        
        filename = 'no-cache-agent.yml'
        self.agent_service.save_agent(filename, agent_data)
        
        # Load the agent to verify cache config
        loaded_agent = self.agent_service.get_agent(filename)
        cache_config = self.agent_service.cache_service.parse_cache_config(loaded_agent)
        
        # Should have cache disabled by default
        self.assertFalse(cache_config['enabled'])
        self.assertFalse(
            self.agent_service.cache_service.is_cache_enabled(cache_config)
        )
    
    def test_agent_with_cache_disabled_uses_no_cache(self):
        """Test that agent with cache explicitly disabled doesn't use cache."""
        agent_data = {
            'name': 'Cache Disabled Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'cache': {
                'enabled': False,
                'ttl_seconds': 3600,
                'key_strategy': 'content_hash',
                'agent_version': 1
            }
        }
        
        filename = 'cache-disabled-agent.yml'
        self.agent_service.save_agent(filename, agent_data)
        
        # Load and check cache config
        loaded_agent = self.agent_service.get_agent(filename)
        cache_config = self.agent_service.cache_service.parse_cache_config(loaded_agent)
        
        self.assertFalse(cache_config['enabled'])
        self.assertFalse(
            self.agent_service.cache_service.is_cache_enabled(cache_config)
        )
    
    def test_agent_with_cache_enabled_config(self):
        """Test that agent with cache enabled has correct configuration."""
        agent_data = {
            'name': 'Cache Enabled Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'cache': {
                'enabled': True,
                'ttl_seconds': 7200,
                'key_strategy': 'content_hash',
                'agent_version': 2
            }
        }
        
        filename = 'cache-enabled-agent.yml'
        self.agent_service.save_agent(filename, agent_data)
        
        # Load and check cache config
        loaded_agent = self.agent_service.get_agent(filename)
        cache_config = self.agent_service.cache_service.parse_cache_config(loaded_agent)
        
        self.assertTrue(cache_config['enabled'])
        self.assertEqual(cache_config['ttl_seconds'], 7200)
        self.assertEqual(cache_config['key_strategy'], 'content_hash')
        self.assertEqual(cache_config['agent_version'], 2)
    
    def test_cache_config_defaults_applied(self):
        """Test that default values are applied when cache config is partial."""
        agent_data = {
            'name': 'Partial Cache Config Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'cache': {
                'enabled': True
                # Other fields missing
            }
        }
        
        filename = 'partial-cache-agent.yml'
        self.agent_service.save_agent(filename, agent_data)
        
        # Load and check cache config with defaults
        loaded_agent = self.agent_service.get_agent(filename)
        cache_config = self.agent_service.cache_service.parse_cache_config(loaded_agent)
        
        self.assertTrue(cache_config['enabled'])
        self.assertEqual(cache_config['ttl_seconds'], 7776000)  # 90 days default
        self.assertEqual(cache_config['key_strategy'], 'content_hash')
        self.assertEqual(cache_config['agent_version'], 1)  # Default version
    
    @override_settings(REDIS_CACHE_ENABLED=False)
    @patch('core.services.ai.router.AIRouter.generate')
    def test_execute_agent_without_cache(self, mock_generate):
        """Test execute_agent works without cache (normal flow)."""
        # Mock AI response
        mock_response = Mock()
        mock_response.text = "AI generated response"
        mock_generate.return_value = mock_response
        
        # Create agent without cache
        agent_data = {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'role': 'Test role',
            'task': 'Test task'
        }
        
        filename = 'test-agent.yml'
        self.agent_service.save_agent(filename, agent_data)
        
        # Execute agent
        result = self.agent_service.execute_agent(
            filename=filename,
            input_text="Test input"
        )
        
        # Should get AI response
        self.assertEqual(result, "AI generated response")
        mock_generate.assert_called_once()
    
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
    @patch('core.services.ai.router.AIRouter.generate')
    def test_execute_agent_cache_miss(self, mock_generate, mock_redis):
        """Test execute_agent with cache miss calls AI and caches response."""
        # Setup Redis mock
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_client.get.return_value = None  # Cache miss
        mock_redis.return_value = mock_client
        
        # Mock AI response
        mock_response = Mock()
        mock_response.text = "Fresh AI response"
        mock_generate.return_value = mock_response
        
        # Create agent with cache enabled
        agent_data = {
            'name': 'Cached Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'role': 'Test',
            'task': 'Test',
            'cache': {
                'enabled': True,
                'ttl_seconds': 3600,
                'agent_version': 1
            }
        }
        
        filename = 'cached-agent.yml'
        
        # Need to reinitialize service to pick up Redis mock
        self.agent_service = AgentService()
        self.agent_service.agents_dir = self.test_agents_dir
        self.agent_service.save_agent(filename, agent_data)
        
        # Execute agent
        result = self.agent_service.execute_agent(
            filename=filename,
            input_text="Test input"
        )
        
        # Should get AI response
        self.assertEqual(result, "Fresh AI response")
        
        # AI should have been called
        mock_generate.assert_called_once()
        
        # Response should have been cached
        mock_client.setex.assert_called_once()
        # Verify TTL was set correctly
        call_args = mock_client.setex.call_args
        self.assertEqual(call_args[0][1], 3600)  # TTL
        self.assertEqual(call_args[0][2], "Fresh AI response")  # Value
    
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
    @patch('core.services.ai.router.AIRouter.generate')
    def test_execute_agent_cache_hit(self, mock_generate, mock_redis):
        """Test execute_agent with cache hit returns cached response without AI call."""
        # Setup Redis mock
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_client.get.return_value = "Cached response from Redis"  # Cache hit
        mock_redis.return_value = mock_client
        
        # Create agent with cache enabled
        agent_data = {
            'name': 'Cached Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'cache': {
                'enabled': True,
                'ttl_seconds': 3600,
                'agent_version': 1
            }
        }
        
        filename = 'cached-agent.yml'
        
        # Need to reinitialize service to pick up Redis mock
        self.agent_service = AgentService()
        self.agent_service.agents_dir = self.test_agents_dir
        self.agent_service.save_agent(filename, agent_data)
        
        # Execute agent
        result = self.agent_service.execute_agent(
            filename=filename,
            input_text="Test input"
        )
        
        # Should get cached response
        self.assertEqual(result, "Cached response from Redis")
        
        # AI should NOT have been called
        mock_generate.assert_not_called()
        
        # Redis GET should have been called
        mock_client.get.assert_called_once()
    
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
    @patch('core.services.ai.router.AIRouter.generate')
    def test_execute_agent_redis_error_fallback(self, mock_generate, mock_redis):
        """Test execute_agent falls back to AI when Redis fails."""
        # Setup Redis mock to fail
        mock_client = Mock()
        mock_client.ping.return_value = True
        mock_client.get.side_effect = Exception("Redis connection lost")
        mock_redis.return_value = mock_client
        
        # Mock AI response
        mock_response = Mock()
        mock_response.text = "AI response after Redis failure"
        mock_generate.return_value = mock_response
        
        # Create agent with cache enabled
        agent_data = {
            'name': 'Resilient Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'cache': {
                'enabled': True,
                'ttl_seconds': 3600
            }
        }
        
        filename = 'resilient-agent.yml'
        
        # Need to reinitialize service to pick up Redis mock
        self.agent_service = AgentService()
        self.agent_service.agents_dir = self.test_agents_dir
        self.agent_service.save_agent(filename, agent_data)
        
        # Execute agent - should not raise exception despite Redis error
        result = self.agent_service.execute_agent(
            filename=filename,
            input_text="Test input"
        )
        
        # Should get AI response (fallback)
        self.assertEqual(result, "AI response after Redis failure")
        
        # AI should have been called as fallback
        mock_generate.assert_called_once()

