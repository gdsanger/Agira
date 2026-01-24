"""
OpenAI provider implementation.
"""

from typing import List, Dict, Optional
import openai
from .base_provider import BaseProvider
from .schemas import ProviderResponse


class OpenAIProvider(BaseProvider):
    """OpenAI API provider implementation."""
    
    def __init__(self, api_key: str, **kwargs):
        """
        Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key
            **kwargs: Additional config (organization_id, etc.)
        """
        super().__init__(api_key, **kwargs)
        
        # Initialize OpenAI client
        client_kwargs = {'api_key': self.api_key}
        
        # Add organization if provided
        if 'organization_id' in self.config and self.config['organization_id']:
            client_kwargs['organization'] = self.config['organization_id']
        
        self.client = openai.OpenAI(**client_kwargs)
    
    @property
    def provider_type(self) -> str:
        """Return provider type."""
        return 'OpenAI'
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> ProviderResponse:
        """
        Execute OpenAI chat completion.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model_id: OpenAI model ID (e.g., 'gpt-4', 'gpt-3.5-turbo')
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional OpenAI parameters
            
        Returns:
            ProviderResponse with completion text and token counts
        """
        # Build request parameters
        request_params = {
            'model': model_id,
            'messages': messages,
        }
        
        if temperature is not None:
            request_params['temperature'] = temperature
        
        if max_tokens is not None:
            request_params['max_tokens'] = max_tokens
        
        # Add any additional kwargs
        request_params.update(kwargs)
        
        # Make API call
        response = self.client.chat.completions.create(**request_params)
        
        # Extract text and token counts
        text = response.choices[0].message.content
        input_tokens = response.usage.prompt_tokens if response.usage else None
        output_tokens = response.usage.completion_tokens if response.usage else None
        
        return ProviderResponse(
            text=text,
            raw=response,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )
