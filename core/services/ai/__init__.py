"""
AI Core Service for Agira.

This package provides a unified AI service layer supporting multiple providers
(OpenAI, Gemini) with consistent API, job logging, and cost tracking.
"""

from .router import AIRouter
from .schemas import AIResponse

__all__ = ['AIRouter', 'AIResponse']
