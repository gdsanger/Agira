"""
Microsoft Graph API client for Agira.

This module provides token handling and HTTP client functionality for
interacting with the Microsoft Graph API. Uses Client Credentials Flow
for app-only authentication.
"""

import logging
import time
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import msal
import requests

from core.services.config import get_graph_config
from core.services.exceptions import ServiceNotConfigured, ServiceDisabled, ServiceError

logger = logging.getLogger(__name__)


class GraphClient:
    """
    Microsoft Graph API client with token management and caching.
    
    This client handles authentication via Client Credentials Flow and
    provides a simple interface for making Graph API requests.
    """
    
    BASE_URL = "https://graph.microsoft.com/v1.0"
    TIMEOUT = 30  # seconds
    
    def __init__(self):
        """Initialize the Graph client with configuration from database."""
        self.config = get_graph_config()
        
        # Check if service is disabled
        if self.config is None or not self.config.enabled:
            raise ServiceDisabled("Graph API service is not enabled")
        
        # Check required configuration (treat empty strings as missing)
        if not self.config.tenant_id or not self.config.client_id or not self.config.client_secret:
            raise ServiceNotConfigured(
                "Graph API is enabled but missing required configuration "
                "(tenant_id, client_id, or client_secret)"
            )
        
        # Token caching
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        
        # MSAL app
        self._msal_app = None
        
        logger.debug("Graph API client initialized")
    
    def _get_msal_app(self) -> msal.ConfidentialClientApplication:
        """Get or create MSAL application instance."""
        if self._msal_app is None:
            authority = f"https://login.microsoftonline.com/{self.config.tenant_id}"
            self._msal_app = msal.ConfidentialClientApplication(
                client_id=self.config.client_id,
                client_credential=self.config.client_secret,
                authority=authority,
            )
        return self._msal_app
    
    def get_access_token(self) -> str:
        """
        Get a valid access token, using cache if available.
        
        Returns:
            Valid access token string
            
        Raises:
            ServiceError: If token acquisition fails
        """
        # Check if we have a cached token that's still valid
        if self._access_token and self._token_expiry:
            # Add a 5-minute buffer before expiry
            if datetime.now() < self._token_expiry - timedelta(minutes=5):
                logger.debug("Using cached access token")
                return self._access_token
        
        # Need to acquire a new token
        logger.debug("Acquiring new access token from Microsoft")
        
        try:
            app = self._get_msal_app()
            
            # Request token with Mail.Send scope
            scopes = ["https://graph.microsoft.com/.default"]
            result = app.acquire_token_for_client(scopes=scopes)
            
            if "access_token" in result:
                self._access_token = result["access_token"]
                
                # Calculate expiry time (expires_in is in seconds)
                expires_in = result.get("expires_in", 3600)
                self._token_expiry = datetime.now() + timedelta(seconds=expires_in)
                
                logger.info("Successfully acquired Graph API access token")
                return self._access_token
            else:
                error_msg = result.get("error_description", result.get("error", "Unknown error"))
                logger.error(f"Failed to acquire token: {error_msg}")
                raise ServiceError(f"Failed to acquire Graph API token: {error_msg}")
                
        except Exception as e:
            if isinstance(e, ServiceError):
                raise
            logger.error(f"Error acquiring Graph API token: {str(e)}")
            raise ServiceError(f"Error acquiring Graph API token: {str(e)}")
    
    def request(
        self,
        method: str,
        url: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Make an HTTP request to the Graph API.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL or path (if path, BASE_URL is prepended)
            json: Optional JSON payload
            headers: Optional additional headers
            
        Returns:
            Response JSON as dict, or None for 202/204 responses
            
        Raises:
            ServiceError: If the request fails
        """
        # Get access token
        token = self.get_access_token()
        
        # Prepare headers
        req_headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        if headers:
            req_headers.update(headers)
        
        # Construct full URL
        if not url.startswith("http"):
            url = f"{self.BASE_URL}{url}"
        
        # Make request
        try:
            logger.debug(f"Making {method} request to {url}")
            response = requests.request(
                method=method,
                url=url,
                json=json,
                headers=req_headers,
                timeout=self.TIMEOUT,
            )
            
            # Check for errors
            if response.status_code >= 400:
                error_detail = response.text
                try:
                    error_json = response.json()
                    error_detail = error_json.get("error", {}).get("message", error_detail)
                except (ValueError, KeyError):
                    pass
                
                logger.error(
                    f"Graph API request failed: {response.status_code} - {error_detail}"
                )
                raise ServiceError(
                    f"Graph API request failed ({response.status_code}): {error_detail}"
                )
            
            # Handle 202 Accepted, 204 No Content
            if response.status_code in [202, 204]:
                logger.debug(f"Request succeeded with status {response.status_code}")
                return None
            
            # Return JSON response
            return response.json()
            
        except requests.RequestException as e:
            logger.error(f"HTTP error making Graph API request: {str(e)}")
            raise ServiceError(f"HTTP error making Graph API request: {str(e)}")
    
    def send_mail(self, sender_upn: str, payload: Dict[str, Any]) -> None:
        """
        Send an email via Graph API.
        
        Args:
            sender_upn: User Principal Name of the sender (e.g., user@domain.com)
            payload: Email payload following Graph API sendMail schema
            
        Raises:
            ServiceError: If sending fails
        """
        url = f"/users/{sender_upn}/sendMail"
        
        logger.info(f"Sending email via Graph API from {sender_upn}")
        logger.debug(f"Email payload: subject='{payload.get('message', {}).get('subject')}'")
        
        # sendMail returns 202 Accepted with no body
        self.request("POST", url, json=payload)
        
        logger.info("Email sent successfully via Graph API")


def get_client() -> GraphClient:
    """
    Get a configured Graph API client instance.
    
    Returns:
        Configured GraphClient instance
        
    Raises:
        ServiceDisabled: If Graph API is not enabled
        ServiceNotConfigured: If Graph API is enabled but missing configuration
        
    Example:
        >>> client = get_client()
        >>> token = client.get_access_token()
    """
    return GraphClient()
