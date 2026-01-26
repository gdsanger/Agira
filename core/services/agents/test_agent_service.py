"""
Tests for the AgentService class.
"""

import os
import tempfile
import shutil
import yaml
from pathlib import Path
from django.test import TestCase
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
