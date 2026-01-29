"""
Microsoft Graph API client for Agira.

This module provides token handling and HTTP client functionality for
interacting with the Microsoft Graph API. Uses Client Credentials Flow
for app-only authentication.
"""

import logging
import time
from typing import Any, Dict, List, Optional
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
    
    def get_inbox_messages(
        self,
        user_upn: str,
        top: int = 10,
        filter_query: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get messages from a user's inbox.
        
        Args:
            user_upn: User Principal Name (e.g., user@domain.com)
            top: Maximum number of messages to retrieve (default: 10, max: 999)
            filter_query: Optional OData filter query
            
        Returns:
            List of message dictionaries
            
        Raises:
            ServiceError: If the request fails
            
        Example:
            >>> client = get_client()
            >>> messages = client.get_inbox_messages("support@company.com", top=50)
        """
        from urllib.parse import urlencode
        
        url = f"/users/{user_upn}/mailFolders/inbox/messages"
        
        # Build query parameters
        params = {
            "$top": str(min(top, 999)),  # Max 999 per request
            "$select": "id,subject,from,toRecipients,body,receivedDateTime,hasAttachments,isRead,categories",
            "$orderby": "receivedDateTime desc",
        }
        
        if filter_query:
            params["$filter"] = filter_query
        
        # Build URL with properly encoded query parameters
        query_string = urlencode(params, safe=':,')
        full_url = f"{url}?{query_string}"
        
        logger.info(f"Fetching inbox messages for {user_upn}")
        
        response = self.request("GET", full_url)
        
        if response and "value" in response:
            messages = response["value"]
            logger.info(f"Retrieved {len(messages)} messages from inbox")
            return messages
        
        return []
    
    def mark_message_as_read(self, user_upn: str, message_id: str) -> None:
        """
        Mark a message as read.
        
        Args:
            user_upn: User Principal Name
            message_id: Message ID
            
        Raises:
            ServiceError: If the request fails
        """
        url = f"/users/{user_upn}/messages/{message_id}"
        payload = {"isRead": True}
        
        logger.info(f"Marking message {message_id} as read")
        self.request("PATCH", url, json=payload)
        logger.debug("Message marked as read")
    
    def add_category_to_message(
        self,
        user_upn: str,
        message_id: str,
        category: str,
    ) -> None:
        """
        Add a category to a message.
        
        Args:
            user_upn: User Principal Name
            message_id: Message ID
            category: Category name to add
            
        Raises:
            ServiceError: If the request fails
        """
        # First, get current categories
        url = f"/users/{user_upn}/messages/{message_id}"
        response = self.request("GET", f"{url}?$select=categories")
        
        current_categories = response.get("categories", []) if response else []
        
        # Add new category if not already present
        if category not in current_categories:
            current_categories.append(category)
            
            # Update message with new categories
            payload = {"categories": current_categories}
            self.request("PATCH", url, json=payload)
            logger.info(f"Added category '{category}' to message {message_id}")
        else:
            logger.debug(f"Category '{category}' already exists on message {message_id}")
    
    def move_message(
        self,
        user_upn: str,
        message_id: str,
        destination_folder_id: str,
    ) -> None:
        """
        Move a message to a different folder.
        
        Args:
            user_upn: User Principal Name
            message_id: Message ID
            destination_folder_id: Destination folder ID (e.g., "deletedItems")
            
        Raises:
            ServiceError: If the request fails
        """
        url = f"/users/{user_upn}/messages/{message_id}/move"
        payload = {"destinationId": destination_folder_id}
        
        logger.info(f"Moving message {message_id} to folder {destination_folder_id}")
        self.request("POST", url, json=payload)
        logger.debug("Message moved successfully")


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
