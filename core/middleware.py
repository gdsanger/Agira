"""
Custom middleware for Agira.
"""
import os
from django.utils.deprecation import MiddlewareMixin


class EmbedFrameMiddleware(MiddlewareMixin):
    """
    Middleware to configure frame options for embed endpoints.
    
    This middleware allows embed endpoints to be displayed in iframes from 
    configured allowed origins while maintaining security for other endpoints.
    
    It uses Content-Security-Policy frame-ancestors directive which is the 
    modern replacement for X-Frame-Options ALLOW-FROM (which is deprecated).
    
    This must be placed BEFORE XFrameOptionsMiddleware in the MIDDLEWARE setting.
    Since middleware process_response methods run in reverse order, this ensures
    our middleware runs AFTER XFrameOptionsMiddleware sets the X-Frame-Options header,
    allowing us to remove it for embed endpoints.
    """
    
    def __init__(self, get_response=None):
        super().__init__(get_response)
        # Get allowed iframe origins from environment variable
        # Default includes the production embed domain
        allowed_origins = os.getenv(
            'EMBED_ALLOWED_ORIGINS', 
            'https://app.ebner-vermietung.de'
        )
        self.allowed_origins = [
            origin.strip() 
            for origin in allowed_origins.split(',') 
            if origin.strip()
        ]
    
    def process_response(self, request, response):
        """
        Process response after all other middleware.
        
        Since middleware process_response methods run in reverse order,
        and this middleware is placed before XFrameOptionsMiddleware in settings,
        this method runs after XFrameOptionsMiddleware has set the X-Frame-Options header.
        """
        # Check if this is an embed endpoint
        if request.path.startswith('/embed/'):
            # Remove the X-Frame-Options header set by XFrameOptionsMiddleware
            # This allows the embed to work in iframes
            if 'X-Frame-Options' in response:
                del response['X-Frame-Options']
            
            # Set Content-Security-Policy frame-ancestors to allow specific origins
            # This is the modern, standards-compliant way to control iframe embedding
            if self.allowed_origins:
                origins_str = ' '.join(self.allowed_origins)
                response['Content-Security-Policy'] = f"frame-ancestors {origins_str}"
            else:
                # If no origins configured, allow all (fallback)
                response['Content-Security-Policy'] = "frame-ancestors *"
        
        return response
