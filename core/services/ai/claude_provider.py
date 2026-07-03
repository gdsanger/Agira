"""
Anthropic Claude provider implementation.
"""

from typing import List, Dict, Optional
import anthropic
from .base_provider import BaseProvider
from .schemas import ProviderResponse


class ClaudeProvider(BaseProvider):
    """Anthropic Claude API provider implementation."""

    def __init__(self, api_key: str, **kwargs):
        """
        Initialize Claude provider.

        Args:
            api_key: Anthropic API key
            **kwargs: Additional config (currently unused)
        """
        super().__init__(api_key, **kwargs)
        self.client = anthropic.Anthropic(api_key=self.api_key)

    @property
    def provider_type(self) -> str:
        """Return provider type."""
        return 'Claude'

    def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> ProviderResponse:
        """
        Execute a Claude Messages API completion.

        Args:
            messages: List of message dicts with 'role' and 'content'.
                'system' role messages are extracted into the top-level
                `system` parameter, as required by the Messages API.
            model_id: Claude model ID (e.g., 'claude-haiku-4-5')
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate (required by the API;
                defaults to 1024 if not provided)
            **kwargs: Additional Anthropic Messages API parameters

        Returns:
            ProviderResponse with completion text and token counts
        """
        system_prompt = None
        claude_messages = []
        for message in messages:
            role = message.get('role', '')
            content = message.get('content', '')
            if role == 'system':
                system_prompt = content if system_prompt is None else f"{system_prompt}\n\n{content}"
            else:
                claude_messages.append({'role': role, 'content': content})

        request_params = {
            'model': model_id,
            'max_tokens': max_tokens or 1024,
            'messages': claude_messages,
        }

        if system_prompt:
            request_params['system'] = system_prompt

        if temperature is not None:
            request_params['temperature'] = temperature

        request_params.update(kwargs)

        response = self.client.messages.create(**request_params)

        text = next((block.text for block in response.content if block.type == 'text'), '')
        input_tokens = response.usage.input_tokens if response.usage else None
        output_tokens = response.usage.output_tokens if response.usage else None

        return ProviderResponse(
            text=text,
            raw=response,
            input_tokens=input_tokens,
            output_tokens=output_tokens
        )
