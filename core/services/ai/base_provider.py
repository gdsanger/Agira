"""
Base provider interface for AI providers.
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from .schemas import ProviderResponse


class BaseProvider(ABC):
    """Abstract base class for AI providers."""
    
    def __init__(self, api_key: str, **kwargs):
        """
        Initialize the provider.
        
        Args:
            api_key: API key for the provider
            **kwargs: Additional provider-specific configuration
        """
        self.api_key = api_key
        self.config = kwargs
    
    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Return the provider type identifier."""
        pass
    
    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> ProviderResponse:
        """
        Execute a chat completion.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model_id: Model identifier
            temperature: Sampling temperature (0-1)
            max_tokens: Maximum tokens to generate
            **kwargs: Additional provider-specific parameters
            
        Returns:
            ProviderResponse with text, raw response, and token counts
        """
        pass
