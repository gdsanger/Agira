"""
Tests for agent cache configuration views and auto-increment functionality.
"""

import os
import tempfile
import shutil
from pathlib import Path
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.services.agents.agent_service import AgentService
from core.models import AIProvider, AIProviderType

User = get_user_model()


class AgentCacheConfigurationTestCase(TestCase):
    """Test cases for agent cache configuration in views."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create a temporary directory for test agents
        self.test_agents_dir = Path(tempfile.mkdtemp())
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        # Create test provider
        self.provider = AIProvider.objects.create(
            name='Test OpenAI',
            provider_type=AIProviderType.OPENAI,
            api_key='test-key',
            active=True
        )
        
        # Create agent service and override directory
        self.agent_service = AgentService()
        self.original_agents_dir = self.agent_service.agents_dir
        self.agent_service.agents_dir = self.test_agents_dir
        
        # Mock the AgentService in views
        import core.views
        self.original_agent_service = core.views.AgentService
        
        # Create a mock class that uses our test directory
        class TestAgentService(AgentService):
            def __init__(self):
                super().__init__()
                self.agents_dir = self.test_agents_dir
        
        core.views.AgentService = TestAgentService
        
        # Client for making requests
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def tearDown(self):
        """Clean up after each test."""
        # Restore original AgentService
        import core.views
        core.views.AgentService = self.original_agent_service
        
        # Remove temporary directory
        if self.test_agents_dir.exists():
            shutil.rmtree(self.test_agents_dir)
    
    def test_create_agent_with_cache_enabled(self):
        """Test creating a new agent with cache enabled."""
        response = self.client.post(
            reverse('agent-create-save'),
            {
                'name': 'Test Cache Agent',
                'description': 'Test description',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'role': 'Test role',
                'task': 'Test task',
                'cache_enabled': 'true',
                'cache_ttl_seconds': '604800',
                'cache_key_strategy': 'content_hash',
                'cache_agent_version': '1',
            }
        )
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Load the agent and verify cache config
        agent = self.agent_service.get_agent('test-cache-agent.yml')
        self.assertIsNotNone(agent)
        self.assertIn('cache', agent)
        self.assertTrue(agent['cache']['enabled'])
        self.assertEqual(agent['cache']['ttl_seconds'], 604800)
        self.assertEqual(agent['cache']['key_strategy'], 'content_hash')
        self.assertEqual(agent['cache']['agent_version'], 1)
    
    def test_create_agent_without_cache(self):
        """Test creating a new agent without cache enabled."""
        response = self.client.post(
            reverse('agent-create-save'),
            {
                'name': 'Test No Cache Agent',
                'description': 'Test description',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'role': 'Test role',
                'task': 'Test task',
                # cache_enabled not set (defaults to false)
            }
        )
        
        # Should redirect on success
        self.assertEqual(response.status_code, 302)
        
        # Load the agent and verify no cache config
        agent = self.agent_service.get_agent('test-no-cache-agent.yml')
        self.assertIsNotNone(agent)
        self.assertNotIn('cache', agent)
    
    def test_save_agent_with_cache_validation_ttl_required(self):
        """Test that TTL is required when cache is enabled."""
        # Create an initial agent
        self.agent_service.save_agent('test-agent.yml', {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
        })
        
        # Try to save with cache enabled but no TTL
        response = self.client.post(
            reverse('agent-save', kwargs={'filename': 'test-agent.yml'}),
            {
                'name': 'Test Agent',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'cache_enabled': 'true',
                # cache_ttl_seconds missing
                'cache_key_strategy': 'content_hash',
            }
        )
        
        # Should return error
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'TTL seconds is required', response.content)
    
    def test_save_agent_with_cache_validation_ttl_positive(self):
        """Test that TTL must be positive."""
        # Create an initial agent
        self.agent_service.save_agent('test-agent.yml', {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
        })
        
        # Try to save with negative TTL
        response = self.client.post(
            reverse('agent-save', kwargs={'filename': 'test-agent.yml'}),
            {
                'name': 'Test Agent',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'cache_enabled': 'true',
                'cache_ttl_seconds': '-100',
                'cache_key_strategy': 'content_hash',
            }
        )
        
        # Should return error
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'must be a positive integer', response.content)
    
    def test_save_agent_with_cache_validation_ttl_integer(self):
        """Test that TTL must be an integer."""
        # Create an initial agent
        self.agent_service.save_agent('test-agent.yml', {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
        })
        
        # Try to save with non-integer TTL
        response = self.client.post(
            reverse('agent-save', kwargs={'filename': 'test-agent.yml'}),
            {
                'name': 'Test Agent',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'cache_enabled': 'true',
                'cache_ttl_seconds': 'not-a-number',
                'cache_key_strategy': 'content_hash',
            }
        )
        
        # Should return error
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'must be a valid integer', response.content)
    
    def test_save_agent_with_invalid_key_strategy(self):
        """Test that only valid key strategies are accepted."""
        # Create an initial agent
        self.agent_service.save_agent('test-agent.yml', {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
        })
        
        # Try to save with invalid key strategy
        response = self.client.post(
            reverse('agent-save', kwargs={'filename': 'test-agent.yml'}),
            {
                'name': 'Test Agent',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'cache_enabled': 'true',
                'cache_ttl_seconds': '604800',
                'cache_key_strategy': 'invalid_strategy',
            }
        )
        
        # Should return error
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Invalid key strategy', response.content)
    
    def test_agent_version_increment_on_task_change(self):
        """Test that agent_version increments when task changes."""
        # Create an initial agent with cache
        self.agent_service.save_agent('test-agent.yml', {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'task': 'Original task',
            'cache': {
                'enabled': True,
                'ttl_seconds': 604800,
                'key_strategy': 'content_hash',
                'agent_version': 1,
            }
        })
        
        # Update agent with changed task
        response = self.client.post(
            reverse('agent-save', kwargs={'filename': 'test-agent.yml'}),
            {
                'name': 'Test Agent',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'task': 'Updated task',  # Changed
                'cache_enabled': 'true',
                'cache_ttl_seconds': '604800',
                'cache_key_strategy': 'content_hash',
                'cache_agent_version': '1',  # User sets this, but server should increment
            }
        )
        
        # Should succeed
        self.assertEqual(response.status_code, 302)
        
        # Load agent and verify version incremented
        agent = self.agent_service.get_agent('test-agent.yml')
        self.assertEqual(agent['cache']['agent_version'], 2)
    
    def test_agent_version_no_increment_on_same_task(self):
        """Test that agent_version does NOT increment when task is unchanged."""
        # Create an initial agent with cache
        self.agent_service.save_agent('test-agent.yml', {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'task': 'Same task',
            'cache': {
                'enabled': True,
                'ttl_seconds': 604800,
                'key_strategy': 'content_hash',
                'agent_version': 3,
            }
        })
        
        # Update agent without changing task
        response = self.client.post(
            reverse('agent-save', kwargs={'filename': 'test-agent.yml'}),
            {
                'name': 'Test Agent Updated',  # Changed name
                'description': 'New description',  # Added description
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'task': 'Same task',  # NOT changed
                'cache_enabled': 'true',
                'cache_ttl_seconds': '1209600',  # Changed TTL
                'cache_key_strategy': 'content_hash',
                'cache_agent_version': '3',
            }
        )
        
        # Should succeed
        self.assertEqual(response.status_code, 302)
        
        # Load agent and verify version NOT incremented
        agent = self.agent_service.get_agent('test-agent.yml')
        self.assertEqual(agent['cache']['agent_version'], 3)
    
    def test_agent_version_increment_even_when_cache_disabled(self):
        """Test that agent_version increments on task change even when cache is disabled."""
        # Create an initial agent with cache
        self.agent_service.save_agent('test-agent.yml', {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'task': 'Original task',
            'cache': {
                'enabled': True,
                'ttl_seconds': 604800,
                'key_strategy': 'content_hash',
                'agent_version': 5,
            }
        })
        
        # Update agent with changed task but disable cache
        response = self.client.post(
            reverse('agent-save', kwargs={'filename': 'test-agent.yml'}),
            {
                'name': 'Test Agent',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'task': 'Changed task',  # Changed
                # cache_enabled not set (disabled)
            }
        )
        
        # Should succeed
        self.assertEqual(response.status_code, 302)
        
        # Load agent and verify version incremented even though cache is disabled
        agent = self.agent_service.get_agent('test-agent.yml')
        self.assertIn('cache', agent)
        self.assertFalse(agent['cache']['enabled'])
        self.assertEqual(agent['cache']['agent_version'], 6)
    
    def test_multiple_task_changes_increment_version(self):
        """Test that multiple task changes increment version each time."""
        # Create initial agent
        self.agent_service.save_agent('test-agent.yml', {
            'name': 'Test Agent',
            'provider': 'openai',
            'model': 'gpt-3.5-turbo',
            'task': 'Task v1',
            'cache': {
                'enabled': True,
                'ttl_seconds': 604800,
                'key_strategy': 'content_hash',
                'agent_version': 1,
            }
        })
        
        # First update
        self.client.post(
            reverse('agent-save', kwargs={'filename': 'test-agent.yml'}),
            {
                'name': 'Test Agent',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'task': 'Task v2',
                'cache_enabled': 'true',
                'cache_ttl_seconds': '604800',
                'cache_key_strategy': 'content_hash',
            }
        )
        
        agent = self.agent_service.get_agent('test-agent.yml')
        self.assertEqual(agent['cache']['agent_version'], 2)
        
        # Second update
        self.client.post(
            reverse('agent-save', kwargs={'filename': 'test-agent.yml'}),
            {
                'name': 'Test Agent',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'task': 'Task v3',
                'cache_enabled': 'true',
                'cache_ttl_seconds': '604800',
                'cache_key_strategy': 'content_hash',
            }
        )
        
        agent = self.agent_service.get_agent('test-agent.yml')
        self.assertEqual(agent['cache']['agent_version'], 3)
        
        # Third update
        self.client.post(
            reverse('agent-save', kwargs={'filename': 'test-agent.yml'}),
            {
                'name': 'Test Agent',
                'provider': 'OpenAI',
                'model': 'gpt-3.5-turbo',
                'task': 'Task v4',
                'cache_enabled': 'true',
                'cache_ttl_seconds': '604800',
                'cache_key_strategy': 'content_hash',
            }
        )
        
        agent = self.agent_service.get_agent('test-agent.yml')
        self.assertEqual(agent['cache']['agent_version'], 4)
