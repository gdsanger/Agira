"""
Data schemas for AI service requests and responses.
"""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class AIResponse:
    """Response from AI provider."""
    text: str
    raw: Any
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    model: str
    provider: str


@dataclass
class ProviderResponse:
    """Internal response from provider implementation."""
    text: str
    raw: Any
    input_tokens: Optional[int]
    output_tokens: Optional[int]
