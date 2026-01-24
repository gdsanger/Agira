"""
Google Gemini provider implementation.
"""

from typing import List, Dict, Optional
from google import genai
from google.genai.types import GenerateContentConfig, Content, Part
from .base_provider import BaseProvider
from .schemas import ProviderResponse


class GeminiProvider(BaseProvider):
    """Google Gemini API provider implementation."""
    
    def __init__(self, api_key: str, **kwargs):
        """
        Initialize Gemini provider.
        
        Args:
            api_key: Google API key
            **kwargs: Additional configuration
        """
        super().__init__(api_key, **kwargs)
        
        # Initialize Gemini client
        self.client = genai.Client(api_key=self.api_key)
    
    @property
    def provider_type(self) -> str:
        """Return provider type."""
        return 'Gemini'
    
    def _convert_messages_to_gemini(self, messages: List[Dict[str, str]]) -> tuple:
        """
        Convert OpenAI-style messages to Gemini format.
        
        Gemini uses a different conversation format:
        - 'system' messages become system_instruction
        - 'user' and 'assistant' (model) alternate in the contents
        
        Args:
            messages: OpenAI-style messages
            
        Returns:
            Tuple of (system_instruction, contents)
        """
        system_instruction = None
        contents = []
        
        for msg in messages:
            role = msg.get('role', '')
            content_text = msg.get('content', '')
            
            if role == 'system':
                # System messages become system instruction
                if system_instruction is None:
                    system_instruction = content_text
                else:
                    # Multiple system messages - append
                    system_instruction += '\n\n' + content_text
            elif role == 'user':
                contents.append(Content(
                    role='user',
                    parts=[Part(text=content_text)]
                ))
            elif role == 'assistant':
                contents.append(Content(
                    role='model',
                    parts=[Part(text=content_text)]
                ))
        
        return system_instruction, contents
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> ProviderResponse:
        """
        Execute Gemini chat completion.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model_id: Gemini model ID (e.g., 'gemini-2.0-flash-exp')
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional Gemini parameters
            
        Returns:
            ProviderResponse with completion text and token counts (if available)
        """
        # Convert messages to Gemini format
        system_instruction, contents = self._convert_messages_to_gemini(messages)
        
        # Build generation config
        config_kwargs = {}
        if temperature is not None:
            config_kwargs['temperature'] = temperature
        if max_tokens is not None:
            config_kwargs['max_output_tokens'] = max_tokens
        
        config = GenerateContentConfig(**config_kwargs) if config_kwargs else None
        
        # Make API call
        response = self.client.models.generate_content(
            model=model_id,
            contents=contents,
            config=config
        )
        
        # Extract text
        text = response.text if hasattr(response, 'text') and response.text else ""
        
        # Try to extract token counts (may not be available in all cases)
        input_tokens = None
        output_tokens = None
        
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            usage = response.usage_metadata
            if hasattr(usage, 'prompt_token_count'):
                input_tokens = usage.prompt_token_count
            if hasattr(usage, 'candidates_token_count'):
                output_tokens = usage.candidates_token_count
        
        return ProviderResponse(
            text=text,
            raw=response,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )
