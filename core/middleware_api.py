"""
API Authentication Middleware for CustomGPT Actions API.

This middleware provides authentication for the CustomGPT Actions API
using a secret token passed in the x-api-secret header.
"""
import os
import logging
from django.http import JsonResponse

logger = logging.getLogger(__name__)


class CustomGPTAPIAuthMiddleware:
    """
    Middleware that enforces x-api-secret authentication for CustomGPT API endpoints.
    
    This middleware checks for the x-api-secret header and validates it against
    the CUSTOMGPT_API_SECRET environment variable.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.api_secret = os.environ.get('CUSTOMGPT_API_SECRET', '')
        
    def __call__(self, request):
        # Check if this is an API endpoint that requires authentication
        if self._is_api_endpoint(request.path):
            # Validate API secret
            provided_secret = request.META.get('HTTP_X_API_SECRET', '')
            
            if not self.api_secret:
                logger.error("CUSTOMGPT_API_SECRET not configured in environment")
                return JsonResponse(
                    {'error': 'API authentication not configured'},
                    status=500
                )
            
            if not provided_secret or provided_secret != self.api_secret:
                # Never log the secret values
                logger.warning(
                    f"Unauthorized API request to {request.path} from {request.META.get('REMOTE_ADDR', 'unknown')}"
                )
                return JsonResponse(
                    {'error': 'Unauthorized. Invalid or missing x-api-secret header.'},
                    status=401
                )
        
        response = self.get_response(request)
        return response
    
    def _is_api_endpoint(self, path):
        """
        Check if the path is a CustomGPT API endpoint that requires authentication.
        
        Args:
            path: Request path
            
        Returns:
            True if this is an API endpoint, False otherwise
        """
        # All endpoints under /api/customgpt/ require authentication
        return path.startswith('/api/customgpt/')
