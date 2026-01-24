"""
Service for managing and executing AI agents from YAML configuration files.
"""

import os
import yaml
from typing import Dict, List, Optional, Any
from pathlib import Path
from django.conf import settings

from core.models import User
from core.services.ai.router import AIRouter
from core.services.exceptions import ServiceNotConfigured


class AgentService:
    """
    Service for loading, managing, and executing AI agents.
    """
    
    def __init__(self):
        """Initialize the agent service."""
        self.agents_dir = Path(settings.BASE_DIR) / 'agents'
        self.ai_router = AIRouter()
    
    def list_agents(self) -> List[Dict[str, Any]]:
        """
        List all available agents from the agents directory.
        
        Returns:
            List of agent dictionaries with name, description, provider, model
        """
        agents = []
        
        if not self.agents_dir.exists():
            return agents
        
        for file_path in self.agents_dir.glob('*.yml'):
            try:
                agent_data = self._load_agent_file(file_path)
                if agent_data:
                    agent_data['filename'] = file_path.name
                    agents.append(agent_data)
            except Exception as e:
                # Log error but continue processing other agents
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Error loading agent {file_path}: {e}")
                continue
        
        # Sort by name
        agents.sort(key=lambda x: x.get('name', ''))
        return agents
    
    def get_agent(self, filename: str) -> Optional[Dict[str, Any]]:
        """
        Load a specific agent by filename.
        
        Args:
            filename: Agent YAML filename
            
        Returns:
            Agent configuration dictionary or None if not found
        """
        file_path = self.agents_dir / filename
        
        if not file_path.exists():
            return None
        
        try:
            agent_data = self._load_agent_file(file_path)
            if agent_data:
                agent_data['filename'] = filename
            return agent_data
        except Exception as e:
            raise ValueError(f"Error loading agent {filename}: {e}")
    
    def save_agent(self, filename: str, agent_data: Dict[str, Any]) -> None:
        """
        Save an agent configuration to a YAML file.
        
        Args:
            filename: Agent YAML filename
            agent_data: Agent configuration dictionary
        """
        file_path = self.agents_dir / filename
        
        # Ensure agents directory exists
        self.agents_dir.mkdir(exist_ok=True)
        
        # Remove filename from data if present
        save_data = {k: v for k, v in agent_data.items() if k != 'filename'}
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                yaml.dump(save_data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        except Exception as e:
            raise ValueError(f"Error saving agent {filename}: {e}")
    
    def delete_agent(self, filename: str) -> bool:
        """
        Delete an agent configuration file.
        
        Args:
            filename: Agent YAML filename
            
        Returns:
            True if deleted successfully, False if file not found
        """
        file_path = self.agents_dir / filename
        
        if not file_path.exists():
            return False
        
        try:
            file_path.unlink()
            return True
        except Exception as e:
            raise ValueError(f"Error deleting agent {filename}: {e}")
    
    def execute_agent(
        self,
        filename: str,
        input_text: str,
        user: Optional[User] = None,
        client_ip: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Execute an agent with the given input text.
        
        Args:
            filename: Agent YAML filename
            input_text: Input text to process
            user: Optional user making the request
            client_ip: Optional client IP address
            parameters: Optional parameters to pass to the agent
            
        Returns:
            Plain text response from the AI
            
        Raises:
            ValueError: If agent not found or misconfigured
            ServiceNotConfigured: If AI provider not available
        """
        # Load agent configuration
        agent = self.get_agent(filename)
        if not agent:
            raise ValueError(f"Agent '{filename}' not found")
        
        # Extract agent configuration
        agent_name = agent.get('name', filename)
        provider = agent.get('provider', 'openai')  # Default to OpenAI
        model = agent.get('model', 'gpt-3.5-turbo')
        role = agent.get('role', '')
        task = agent.get('task', '')
        agent_params = agent.get('parameters', {})
        
        # Build the prompt from role and task
        prompt_parts = []
        if role:
            prompt_parts.append(f"Role: {role}")
        if task:
            prompt_parts.append(f"\nTask: {task}")
        
        # Add parameters to prompt if provided
        if parameters:
            prompt_parts.append("\nParameters:")
            for key, value in parameters.items():
                prompt_parts.append(f"- {key}: {value}")
        
        # Add input text
        prompt_parts.append(f"\nInput:\n{input_text}")
        
        full_prompt = "\n".join(prompt_parts)
        
        # Map provider name to provider type
        provider_type_map = {
            'openai': 'OpenAI',
            'gemini': 'Gemini',
            'claude': 'Claude',
        }
        provider_type = provider_type_map.get(provider.lower(), 'OpenAI')
        
        # Execute using AI router
        try:
            response = self.ai_router.generate(
                prompt=full_prompt,
                model_id=model,
                provider_type=provider_type,
                user=user,
                client_ip=client_ip,
                agent=agent_name
            )
            
            return response.text
            
        except Exception as e:
            raise ServiceNotConfigured(f"Error executing agent: {e}")
    
    def _load_agent_file(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        Load and parse a YAML agent file.
        
        Args:
            file_path: Path to the YAML file
            
        Returns:
            Parsed agent configuration or None
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
                
                # Ensure it's a dictionary
                if not isinstance(data, dict):
                    return None
                
                return data
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error parsing {file_path}: {e}")
            return None
