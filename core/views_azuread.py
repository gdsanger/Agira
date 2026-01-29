"""
Azure AD authentication views.

This module provides views for Azure AD SSO authentication:
- Login initiation
- Callback handling
- Logout with single sign-out
"""

import logging
import secrets
from django.conf import settings
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from core.backends.azuread import AzureADAuth, AzureADAuthError

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def azuread_login(request):
    """
    Initiate Azure AD SSO login flow.
    
    This view:
    1. Checks if Azure AD is enabled
    2. Generates a CSRF state token
    3. Stores the state token in session
    4. Redirects to Azure AD authorization endpoint
    """
    if not settings.AZURE_AD_ENABLED:
        logger.warning("Azure AD login attempted but Azure AD is not enabled")
        return render(request, 'login.html', {
            'error': 'Azure AD Login ist nicht verfügbar.',
            'azure_ad_enabled': settings.AZURE_AD_ENABLED
        })
    
    try:
        # Get Azure AD auth handler
        azure_ad = AzureADAuth()
        
        # Generate CSRF state token
        state = secrets.token_urlsafe(32)
        
        # Initiate auth code flow
        flow = azure_ad.initiate_auth_code_flow(state)
        
        # Store flow in session for validation in callback
        request.session['azure_ad_flow'] = flow
        
        # Store next URL if provided (validate it's safe)
        next_url = request.GET.get('next', '')
        if next_url:
            # Validate that next URL is safe (internal to this site)
            allowed_hosts = {request.get_host()}
            if url_has_allowed_host_and_scheme(next_url, allowed_hosts=allowed_hosts):
                request.session['azure_ad_next'] = next_url
            else:
                logger.warning(f"Rejected unsafe next URL: {next_url}")
        
        # Get authorization URL from flow
        auth_url = flow.get('auth_uri')
        if not auth_url:
            raise AzureADAuthError("Flow does not contain auth_uri")
        
        logger.info("Redirecting to Azure AD for authentication")
        return redirect(auth_url)
        
    except AzureADAuthError as e:
        logger.error(f"Azure AD login failed: {str(e)}")
        return render(request, 'login.html', {
            'error': 'Azure AD Login fehlgeschlagen. Bitte erneut versuchen oder Administrator kontaktieren.',
            'azure_ad_enabled': settings.AZURE_AD_ENABLED
        })
    except Exception as e:
        logger.error(f"Unexpected error during Azure AD login: {str(e)}", exc_info=True)
        return render(request, 'login.html', {
            'error': 'Ein unerwarteter Fehler ist aufgetreten. Bitte erneut versuchen.',
            'azure_ad_enabled': settings.AZURE_AD_ENABLED
        })


@csrf_exempt  # Azure AD callback doesn't include CSRF token
@require_http_methods(["GET", "POST"])
def azuread_callback(request):
    """
    Handle Azure AD callback after authentication.
    
    This view:
    1. Validates the state token (CSRF protection)
    2. Exchanges authorization code for tokens
    3. Validates the ID token
    4. Maps/creates the Agira user
    5. Logs the user in
    6. Redirects to the appropriate page
    """
    if not settings.AZURE_AD_ENABLED:
        logger.warning("Azure AD callback received but Azure AD is not enabled")
        return render(request, 'login.html', {
            'error': 'Azure AD Login ist nicht verfügbar.',
            'azure_ad_enabled': settings.AZURE_AD_ENABLED
        })
    
    try:
        # Get authorization code from callback
        code = request.GET.get('code')
        state = request.GET.get('state')
        error = request.GET.get('error')
        
        # Check for errors from Azure AD
        if error:
            error_description = request.GET.get('error_description', 'Unknown error')
            logger.error(f"Azure AD returned error: {error}: {error_description}")
            return render(request, 'login.html', {
                'error': 'Azure AD Login fehlgeschlagen. Bitte erneut versuchen oder Administrator kontaktieren.',
                'azure_ad_enabled': settings.AZURE_AD_ENABLED
            })
        
        # Validate required parameters
        if not code or not state:
            logger.error("Azure AD callback missing code or state parameter")
            return render(request, 'login.html', {
                'error': 'Ungültige Azure AD Antwort. Bitte erneut versuchen.',
                'azure_ad_enabled': settings.AZURE_AD_ENABLED
            })
        
        # Get flow from session
        flow = request.session.get('azure_ad_flow')
        if not flow:
            logger.error("Azure AD flow not found in session")
            return render(request, 'login.html', {
                'error': 'Sitzung abgelaufen. Bitte erneut versuchen.',
                'azure_ad_enabled': settings.AZURE_AD_ENABLED
            })
        
        # Validate state token (CSRF protection)
        flow_state = flow.get('state')
        if not flow_state or flow_state != state:
            logger.error("Azure AD state token mismatch (CSRF attack?)")
            return render(request, 'login.html', {
                'error': 'Sicherheitsvalidierung fehlgeschlagen. Bitte erneut versuchen.',
                'azure_ad_enabled': settings.AZURE_AD_ENABLED
            })
        
        # Clean up flow from session
        del request.session['azure_ad_flow']
        
        # Get Azure AD auth handler
        azure_ad = AzureADAuth()
        
        # Exchange authorization code for tokens
        logger.info("Exchanging authorization code for tokens")
        token_result = azure_ad.acquire_token_by_auth_code(code, state, flow)
        
        # Get ID token
        id_token = token_result.get('id_token')
        if not id_token:
            raise AzureADAuthError("Token response does not contain id_token")
        
        # Validate and decode ID token
        logger.info("Validating ID token")
        token_claims = azure_ad.validate_and_decode_token(id_token)
        
        # Get or create Agira user
        logger.info("Mapping Azure AD user to Agira user")
        user = azure_ad.get_or_create_user(token_claims)
        
        # Check if user is active
        if not user.active:
            logger.warning(f"Azure AD login attempted for inactive user: {user.username}")
            return render(request, 'login.html', {
                'error': 'Ihr Konto ist deaktiviert. Bitte kontaktieren Sie den Administrator.',
                'azure_ad_enabled': settings.AZURE_AD_ENABLED
            })
        
        # Log the user in
        auth_login(request, user, backend='django.contrib.auth.backends.ModelBackend')
        logger.info(f"Successfully logged in user via Azure AD: {user.username}")
        
        # Get next URL from session or default to dashboard
        next_url = request.session.pop('azure_ad_next', None)
        
        # Validate next URL is safe before redirecting
        if next_url:
            allowed_hosts = {request.get_host()}
            if not url_has_allowed_host_and_scheme(next_url, allowed_hosts=allowed_hosts):
                logger.warning(f"Rejected unsafe next URL from session: {next_url}")
                next_url = 'dashboard'
        else:
            next_url = 'dashboard'
        
        return redirect(next_url)
        
    except AzureADAuthError as e:
        logger.error(f"Azure AD authentication failed: {str(e)}")
        return render(request, 'login.html', {
            'error': 'Azure AD Login fehlgeschlagen. Bitte erneut versuchen oder Administrator kontaktieren.',
            'azure_ad_enabled': settings.AZURE_AD_ENABLED
        })
    except Exception as e:
        logger.error(f"Unexpected error during Azure AD callback: {str(e)}", exc_info=True)
        return render(request, 'login.html', {
            'error': 'Ein unerwarteter Fehler ist aufgetreten. Bitte erneut versuchen.',
            'azure_ad_enabled': settings.AZURE_AD_ENABLED
        })


@require_http_methods(["POST", "GET"])
def azuread_logout(request):
    """
    Handle logout with Azure AD single sign-out.
    
    This view:
    1. Logs out the user from Agira
    2. Redirects to Azure AD logout endpoint for single sign-out (if configured)
    """
    # Log out from Agira
    auth_logout(request)
    logger.info("User logged out")
    
    # If Azure AD is enabled and user wants single sign-out, redirect to Azure AD logout
    if settings.AZURE_AD_ENABLED and request.GET.get('azure_logout') == 'true':
        try:
            azure_ad = AzureADAuth()
            
            # Build post-logout redirect URI (back to login page)
            post_logout_uri = request.build_absolute_uri(reverse('login'))
            
            # Get Azure AD logout URL
            logout_url = azure_ad.get_logout_url(post_logout_uri)
            
            logger.info("Redirecting to Azure AD for single sign-out")
            return redirect(logout_url)
            
        except AzureADAuthError as e:
            logger.warning(f"Azure AD logout failed: {str(e)}")
            # Continue with local logout even if Azure AD logout fails
        except Exception as e:
            logger.error(f"Unexpected error during Azure AD logout: {str(e)}", exc_info=True)
            # Continue with local logout even if Azure AD logout fails
    
    # Default: redirect to logged out page
    return render(request, 'logged_out.html')
