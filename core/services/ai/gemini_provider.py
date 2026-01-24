"""
Google Gemini provider implementation.
"""

from typing import List, Dict, Optional
import google.generativeai as genai
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
        
        # Configure Gemini
        genai.configure(api_key=self.api_key)
    
    @property
    def provider_type(self) -> str:
        """Return provider type."""
        return 'Gemini'
    
    def _convert_messages_to_gemini(self, messages: List[Dict[str, str]]) -> tuple:
        """
        Convert OpenAI-style messages to Gemini format.
        
        Gemini uses a different conversation format:
        - 'system' messages become part of the initial prompt
        - 'user' and 'assistant' (model) alternate in the history
        
        Args:
            messages: OpenAI-style messages
            
        Returns:
            Tuple of (system_instruction, history)
        """
        system_instruction = None
        history = []
        
        for msg in messages:
            role = msg.get('role', '')
            content = msg.get('content', '')
            
            if role == 'system':
                # System messages become system instruction
                if system_instruction is None:
                    system_instruction = content
                else:
                    # Multiple system messages - append
                    system_instruction += '\n\n' + content
            elif role == 'user':
                history.append({
                    'role': 'user',
                    'parts': [content]
                })
            elif role == 'assistant':
                history.append({
                    'role': 'model',
                    'parts': [content]
                })
        
        return system_instruction, history
    
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
            model_id: Gemini model ID (e.g., 'gemini-pro')
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional Gemini parameters
            
        Returns:
            ProviderResponse with completion text and token counts (if available)
        """
        # Convert messages to Gemini format
        system_instruction, history = self._convert_messages_to_gemini(messages)
        
        # Build generation config
        generation_config = {}
        if temperature is not None:
            generation_config['temperature'] = temperature
        if max_tokens is not None:
            generation_config['max_output_tokens'] = max_tokens
        
        # Create model instance with system instruction if provided
        model_kwargs = {}
        if system_instruction:
            model_kwargs['system_instruction'] = system_instruction
        
        model = genai.GenerativeModel(
            model_name=model_id,
            **model_kwargs
        )
        
        # Handle conversation
        if len(history) == 0:
            # No messages - shouldn't happen, but handle gracefully
            response = model.generate_content(
                "",
                generation_config=generation_config if generation_config else None
            )
        elif len(history) == 1 and history[0]['role'] == 'user':
            # Single user message - simple generation
            response = model.generate_content(
                history[0]['parts'][0],
                generation_config=generation_config if generation_config else None
            )
        else:
            # Multi-turn conversation - use chat
            # For chat, we need to separate the last user message from history
            chat_history = history[:-1] if history[-1]['role'] == 'user' else history
            last_message = history[-1]['parts'][0] if history[-1]['role'] == 'user' else ""
            
            chat = model.start_chat(history=chat_history if chat_history else [])
            response = chat.send_message(
                last_message,
                generation_config=generation_config if generation_config else None
            )
        
        # Extract text
        text = response.text if hasattr(response, 'text') else ""
        
        # Try to extract token counts (may not be available in all cases)
        input_tokens = None
        output_tokens = None
        
        if hasattr(response, 'usage_metadata'):
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
