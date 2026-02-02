"""
Custom middleware for Agira.
"""
from django.utils.deprecation import MiddlewareMixin


class EmbedFrameMiddleware(MiddlewareMixin):
    """
    Middleware to configure frame options for embed endpoints.
    
    This middleware allows embed endpoints to be displayed in iframes from 
    configured allowed origins while maintaining security for other endpoints.
    
    It uses Content-Security-Policy frame-ancestors directive which is the 
    modern replacement for X-Frame-Options ALLOW-FROM (which is deprecated).
    
    Allowed origins are configured per OrganisationEmbedProject in the database,
    providing dynamic, organization-specific control over iframe embedding.
    
    This must be placed BEFORE XFrameOptionsMiddleware in the MIDDLEWARE setting.
    Since middleware process_response methods run in reverse order, this ensures
    our middleware runs AFTER XFrameOptionsMiddleware sets the X-Frame-Options header,
    allowing us to remove it for embed endpoints.
    """
    
    def _get_embed_token_from_request(self, request):
        """
        Extract the embed token from the request.
        
        Args:
            request: The Django request object
            
        Returns:
            str or None: The embed token if found, None otherwise
        """
        # Token can be in GET or POST parameters
        return request.GET.get('token') or request.POST.get('token')
    
    def _get_allowed_origins(self, token):
        """
        Get allowed origins from the database based on the embed token.
        
        Args:
            token: The embed token
            
        Returns:
            list: List of allowed origin strings, or empty list if token is invalid/disabled
        """
        if not token:
            return []
        
        try:
            from core.models import OrganisationEmbedProject
            embed_access = OrganisationEmbedProject.objects.only(
                'allowed_origins', 'is_enabled'
            ).get(embed_token=token)
            
            if not embed_access.is_enabled:
                # Access is disabled, deny all origins
                return []
            
            # Get the parsed list of allowed origins
            return embed_access.get_allowed_origins()
        except OrganisationEmbedProject.DoesNotExist:
            # Invalid token, deny all origins
            return []
        except Exception:
            # Any other error (e.g., database connection), fail closed
            return []
    
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
            
            # Get the embed token from the request
            token = self._get_embed_token_from_request(request)
            
            # Get allowed origins from the database
            allowed_origins = self._get_allowed_origins(token)
            
            # Set Content-Security-Policy frame-ancestors to allow specific origins
            # Fail-closed: if no allowed origins, deny all iframe embedding
            if allowed_origins:
                origins_str = ' '.join(allowed_origins)
                frame_ancestors = f"frame-ancestors {origins_str}"
            else:
                # No allowed origins configured or invalid token - deny iframe embedding
                frame_ancestors = "frame-ancestors 'none'"
            
            # Check if CSP header already exists and append to it
            existing_csp = response.get('Content-Security-Policy', '')
            if existing_csp:
                # Append frame-ancestors to existing CSP
                # Remove any existing frame-ancestors directive first
                csp_parts = [part.strip() for part in existing_csp.split(';') if part.strip()]
                csp_parts = [part for part in csp_parts if not part.startswith('frame-ancestors')]
                csp_parts.append(frame_ancestors)
                response['Content-Security-Policy'] = '; '.join(csp_parts)
            else:
                # No existing CSP, just set frame-ancestors
                response['Content-Security-Policy'] = frame_ancestors
        
        return response
