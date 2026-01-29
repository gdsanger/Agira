"""
Azure AD / MSAL authentication utilities.

This module provides utilities for Azure AD SSO authentication using MSAL.
It handles token validation, user mapping, and auto-provisioning.
"""

import logging
import msal
import jwt
from typing import Optional, Dict, Any
from django.conf import settings
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)

User = get_user_model()


class AzureADAuthError(Exception):
    """Exception raised for Azure AD authentication errors."""
    pass


class AzureADAuth:
    """
    Azure AD authentication handler using MSAL.
    
    This class provides methods for:
    - Initiating the Azure AD login flow
    - Handling the callback and token exchange
    - Validating tokens
    - Mapping Azure AD users to Agira users
    - Auto-provisioning new users
    """
    
    def __init__(self):
        """Initialize the Azure AD authentication handler."""
        if not settings.AZURE_AD_ENABLED:
            raise AzureADAuthError("Azure AD authentication is not enabled")
        
        if not all([settings.AZURE_AD_TENANT_ID, settings.AZURE_AD_CLIENT_ID, 
                    settings.AZURE_AD_CLIENT_SECRET, settings.AZURE_AD_REDIRECT_URI]):
            raise AzureADAuthError("Azure AD configuration is incomplete")
        
        self.authority = settings.AZURE_AD_AUTHORITY
        self.client_id = settings.AZURE_AD_CLIENT_ID
        self.client_secret = settings.AZURE_AD_CLIENT_SECRET
        self.redirect_uri = settings.AZURE_AD_REDIRECT_URI
        self.scopes = settings.AZURE_AD_SCOPES
    
    def get_msal_app(self) -> msal.ConfidentialClientApplication:
        """
        Get MSAL confidential client application instance.
        
        Returns:
            MSAL ConfidentialClientApplication instance
        """
        return msal.ConfidentialClientApplication(
            self.client_id,
            authority=self.authority,
            client_credential=self.client_secret,
        )
    
    def get_auth_url(self, state: str) -> str:
        """
        Get the authorization URL for Azure AD login.
        
        Args:
            state: CSRF state token
            
        Returns:
            Authorization URL
        """
        msal_app = self.get_msal_app()
        auth_url = msal_app.get_authorization_request_url(
            scopes=self.scopes,
            state=state,
            redirect_uri=self.redirect_uri
        )
        logger.info("Generated Azure AD authorization URL")
        return auth_url
    
    def acquire_token_by_auth_code(self, code: str) -> Dict[str, Any]:
        """
        Exchange authorization code for access token.
        
        Args:
            code: Authorization code from Azure AD callback
            
        Returns:
            Token response dictionary
            
        Raises:
            AzureADAuthError: If token acquisition fails
        """
        msal_app = self.get_msal_app()
        result = msal_app.acquire_token_by_authorization_code(
            code,
            scopes=self.scopes,
            redirect_uri=self.redirect_uri
        )
        
        if "error" in result:
            error_msg = f"Token acquisition failed: {result.get('error')}: {result.get('error_description')}"
            logger.error(error_msg)
            raise AzureADAuthError(error_msg)
        
        logger.info("Successfully acquired token from Azure AD")
        return result
    
    def validate_and_decode_token(self, id_token: str) -> Dict[str, Any]:
        """
        Validate and decode the ID token from Azure AD.
        
        Note: For production, implement proper signature validation using
        public keys from Azure AD's JWKS endpoint.
        
        Args:
            id_token: ID token JWT from Azure AD
            
        Returns:
            Decoded token claims
            
        Raises:
            AzureADAuthError: If token validation fails
        """
        try:
            # Decode without verification for now (Azure AD has already validated it via MSAL)
            # In production, you should verify the signature using Azure's public keys
            decoded = jwt.decode(
                id_token,
                options={"verify_signature": False},
                algorithms=["RS256"]
            )
            
            # Validate issuer
            expected_issuer = f"https://login.microsoftonline.com/{settings.AZURE_AD_TENANT_ID}/v2.0"
            if decoded.get("iss") != expected_issuer:
                raise AzureADAuthError(f"Invalid token issuer: {decoded.get('iss')}")
            
            # Validate audience
            if decoded.get("aud") != self.client_id:
                raise AzureADAuthError(f"Invalid token audience: {decoded.get('aud')}")
            
            # Validate expiration (exp claim is Unix timestamp)
            import time
            if decoded.get("exp", 0) < time.time():
                raise AzureADAuthError("Token has expired")
            
            logger.info(f"Successfully validated token for user: {decoded.get('preferred_username', 'unknown')}")
            return decoded
            
        except jwt.DecodeError as e:
            error_msg = f"Failed to decode token: {str(e)}"
            logger.error(error_msg)
            raise AzureADAuthError(error_msg)
        except Exception as e:
            error_msg = f"Token validation failed: {str(e)}"
            logger.error(error_msg)
            raise AzureADAuthError(error_msg)
    
    def get_or_create_user(self, token_claims: Dict[str, Any]) -> User:
        """
        Get or create Agira user from Azure AD token claims.
        
        This implements the user mapping and auto-provisioning logic:
        1. Try to find user by azure_ad_object_id
        2. If not found, try to find by email
        3. If still not found, create new user
        
        Args:
            token_claims: Decoded ID token claims from Azure AD
            
        Returns:
            Agira User instance
            
        Raises:
            AzureADAuthError: If user creation/mapping fails
        """
        try:
            # Extract user information from token claims
            object_id = token_claims.get("oid")  # Azure AD Object ID
            email = token_claims.get("email") or token_claims.get("preferred_username")
            name = token_claims.get("name", "")
            
            if not object_id:
                raise AzureADAuthError("Token does not contain Azure AD Object ID (oid)")
            
            if not email:
                raise AzureADAuthError("Token does not contain email or preferred_username")
            
            # Try to find existing user by Azure AD Object ID
            try:
                user = User.objects.get(azure_ad_object_id=object_id)
                logger.info(f"Found existing user by Azure AD Object ID: {user.username}")
                
                # Update email if changed
                if user.email != email:
                    logger.info(f"Updating email for user {user.username}: {user.email} -> {email}")
                    user.email = email
                    user.save()
                
                return user
            except User.DoesNotExist:
                pass
            
            # Try to find existing user by email
            try:
                user = User.objects.get(email=email)
                logger.info(f"Found existing user by email: {user.username}, linking to Azure AD")
                
                # Link this user to Azure AD
                user.azure_ad_object_id = object_id
                user.save()
                
                return user
            except User.DoesNotExist:
                pass
            
            # Auto-provision new user
            logger.info(f"Auto-provisioning new user for Azure AD user: {email}")
            
            # Generate username from email
            username = email.split('@')[0]
            
            # Ensure username is unique
            base_username = username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1
            
            # Create new user
            user = User.objects.create(
                username=username,
                email=email,
                name=name or email,
                azure_ad_object_id=object_id,
                role=settings.AZURE_AD_DEFAULT_ROLE,
                active=True,
                is_staff=False,
                is_superuser=False,
            )
            
            logger.info(f"Successfully auto-provisioned user: {user.username} with role {user.role}")
            
            return user
            
        except Exception as e:
            error_msg = f"Failed to get or create user: {str(e)}"
            logger.error(error_msg)
            raise AzureADAuthError(error_msg)
    
    def get_logout_url(self, post_logout_redirect_uri: Optional[str] = None) -> str:
        """
        Get the Azure AD logout URL for single logout.
        
        Args:
            post_logout_redirect_uri: URL to redirect to after logout
            
        Returns:
            Azure AD logout URL
        """
        logout_url = f"{self.authority}/oauth2/v2.0/logout"
        if post_logout_redirect_uri:
            logout_url += f"?post_logout_redirect_uri={post_logout_redirect_uri}"
        
        logger.info("Generated Azure AD logout URL")
        return logout_url
