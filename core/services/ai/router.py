"""
AI Router - Main entry point for AI services in Agira.
"""

import time
from typing import List, Dict, Optional
from django.utils import timezone

from core.models import AIProvider, AIModel, AIJobsHistory, User
from core.services.exceptions import ServiceNotConfigured
from .base_provider import BaseProvider
from .openai_provider import OpenAIProvider
from .gemini_provider import GeminiProvider
from .schemas import AIResponse
from .pricing import calculate_cost


class AIRouter:
    """
    AI Router for managing multiple AI providers.
    
    Provides a unified interface for chat/generate operations across
    OpenAI, Gemini, and other providers with automatic logging and cost tracking.
    """
    
    # Provider class mapping
    PROVIDER_CLASSES = {
        'OpenAI': OpenAIProvider,
        'Gemini': GeminiProvider,
        # Claude can be added later
    }
    
    def __init__(self):
        """Initialize the AI Router."""
        pass
    
    def _get_provider_instance(self, provider: AIProvider) -> BaseProvider:
        """
        Create a provider instance from database configuration.
        
        Args:
            provider: AIProvider model instance
            
        Returns:
            Initialized provider instance
            
        Raises:
            ServiceNotConfigured: If provider type is not supported
        """
        provider_class = self.PROVIDER_CLASSES.get(provider.provider_type)
        
        if not provider_class:
            raise ServiceNotConfigured(
                f"Provider type '{provider.provider_type}' is not supported"
            )
        
        # Build provider kwargs
        kwargs = {}
        if provider.organization_id:
            kwargs['organization_id'] = provider.organization_id
        
        return provider_class(api_key=provider.api_key, **kwargs)
    
    def _select_model(
        self,
        provider_type: Optional[str] = None,
        model_id: Optional[str] = None
    ) -> tuple[AIProvider, AIModel]:
        """
        Select provider and model based on parameters or defaults.
        
        Selection logic:
        1. If provider_type + model_id specified: use exact match
        2. If only provider_type specified: use first active model or default
        3. If nothing specified: use default (prioritize OpenAI, then Gemini)
        
        Args:
            provider_type: Optional provider type filter
            model_id: Optional model ID filter
            
        Returns:
            Tuple of (AIProvider, AIModel)
            
        Raises:
            ServiceNotConfigured: If no active model is found
        """
        # Case 1: Both provider_type and model_id specified
        if provider_type and model_id:
            try:
                model = AIModel.objects.select_related('provider').get(
                    provider__provider_type=provider_type,
                    model_id=model_id,
                    active=True,
                    provider__active=True
                )
                return model.provider, model
            except AIModel.DoesNotExist:
                raise ServiceNotConfigured(
                    f"No active model found for provider '{provider_type}' with model_id '{model_id}'"
                )
        
        # Case 2: Only provider_type specified
        if provider_type:
            # Try to get default model for this provider
            model = AIModel.objects.select_related('provider').filter(
                provider__provider_type=provider_type,
                active=True,
                provider__active=True,
                is_default=True
            ).first()
            
            if not model:
                # No default, get first active model
                model = AIModel.objects.select_related('provider').filter(
                    provider__provider_type=provider_type,
                    active=True,
                    provider__active=True
                ).first()
            
            if not model:
                raise ServiceNotConfigured(
                    f"No active model found for provider '{provider_type}'"
                )
            
            return model.provider, model
        
        # Case 3: Nothing specified - use default
        # Priority: OpenAI default, then Gemini default, then any active
        for ptype in ['OpenAI', 'Gemini']:
            model = AIModel.objects.select_related('provider').filter(
                provider__provider_type=ptype,
                active=True,
                provider__active=True,
                is_default=True
            ).first()
            
            if model:
                return model.provider, model
        
        # No default found, try any active model (OpenAI first, then Gemini)
        for ptype in ['OpenAI', 'Gemini']:
            model = AIModel.objects.select_related('provider').filter(
                provider__provider_type=ptype,
                active=True,
                provider__active=True
            ).first()
            
            if model:
                return model.provider, model
        
        # No active models at all
        raise ServiceNotConfigured("No active AI model configured")
    
    def _create_job(
        self,
        provider: AIProvider,
        model: AIModel,
        user: Optional[User],
        client_ip: Optional[str],
        agent: str
    ) -> AIJobsHistory:
        """
        Create a new AI job history entry.
        
        Args:
            provider: AIProvider instance
            model: AIModel instance
            user: Optional user
            client_ip: Optional client IP
            agent: Agent name
            
        Returns:
            Created AIJobsHistory instance
        """
        job = AIJobsHistory.objects.create(
            agent=agent,
            user=user,
            provider=provider,
            model=model,
            client_ip=client_ip,
            status='Pending',
            timestamp=timezone.now()
        )
        return job
    
    def _complete_job(
        self,
        job: AIJobsHistory,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        duration_ms: int,
        error_message: str = ""
    ) -> None:
        """
        Update job with completion data.
        
        Args:
            job: AIJobsHistory instance
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            duration_ms: Duration in milliseconds
            error_message: Optional error message
        """
        job.input_tokens = input_tokens
        job.output_tokens = output_tokens
        job.duration_ms = duration_ms
        
        if error_message:
            job.status = 'Error'
            job.error_message = error_message
        else:
            job.status = 'Completed'
        
        # Calculate cost if we have all required data
        if job.model:
            cost = calculate_cost(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_price_per_1m=job.model.input_price_per_1m_tokens,
                output_price_per_1m=job.model.output_price_per_1m_tokens
            )
            job.costs = cost
        
        job.save()
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model_id: Optional[str] = None,
        provider_type: Optional[str] = None,
        user: Optional[User] = None,
        client_ip: Optional[str] = None,
        agent: str = "core.ai",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AIResponse:
        """
        Execute a chat completion with automatic logging and cost tracking.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model_id: Optional specific model ID
            provider_type: Optional provider type filter
            user: Optional user making the request
            client_ip: Optional client IP address
            agent: Agent name (default: 'core.ai')
            temperature: Optional temperature parameter
            max_tokens: Optional max tokens parameter
            **kwargs: Additional provider-specific parameters
            
        Returns:
            AIResponse with text, raw response, token counts, and metadata
            
        Raises:
            ServiceNotConfigured: If no active model is available
        """
        # Select provider and model
        provider, model = self._select_model(provider_type, model_id)
        
        # Create job entry
        job = self._create_job(provider, model, user, client_ip, agent)
        
        # Start timing
        start_time = time.time()
        
        try:
            # Get provider instance
            provider_instance = self._get_provider_instance(provider)
            
            # Execute chat
            response = provider_instance.chat(
                messages=messages,
                model_id=model.model_id,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )
            
            # Calculate duration
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Update job with success
            self._complete_job(
                job,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                duration_ms=duration_ms
            )
            
            # Build and return response
            return AIResponse(
                text=response.text,
                raw=response.raw,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                model=model.model_id,
                provider=provider.provider_type
            )
            
        except Exception as e:
            # Calculate duration even on error
            duration_ms = int((time.time() - start_time) * 1000)
            
            # Update job with error
            self._complete_job(
                job,
                input_tokens=None,
                output_tokens=None,
                duration_ms=duration_ms,
                error_message=str(e)
            )
            
            # Re-raise exception
            raise
    
    def generate(
        self,
        prompt: str,
        model_id: Optional[str] = None,
        provider_type: Optional[str] = None,
        user: Optional[User] = None,
        client_ip: Optional[str] = None,
        agent: str = "core.ai",
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> AIResponse:
        """
        Simple text generation (shortcut for single-prompt chat).
        
        Args:
            prompt: Input prompt text
            model_id: Optional specific model ID
            provider_type: Optional provider type filter
            user: Optional user making the request
            client_ip: Optional client IP address
            agent: Agent name (default: 'core.ai')
            temperature: Optional temperature parameter
            max_tokens: Optional max tokens parameter
            **kwargs: Additional provider-specific parameters
            
        Returns:
            AIResponse with generated text and metadata
        """
        messages = [{'role': 'user', 'content': prompt}]
        
        return self.chat(
            messages=messages,
            model_id=model_id,
            provider_type=provider_type,
            user=user,
            client_ip=client_ip,
            agent=agent,
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs
        )
