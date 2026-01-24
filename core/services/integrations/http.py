"""
HTTP client wrapper for integration services.

Provides consistent error handling, timeouts, and retry logic for HTTP requests.
"""

import logging
import time
from typing import Optional, Dict, Any
from urllib.parse import urljoin

import httpx

from .base import (
    IntegrationError,
    IntegrationAuthError,
    IntegrationRateLimitError,
    IntegrationNotFoundError,
    IntegrationValidationError,
)

logger = logging.getLogger(__name__)


class HTTPClient:
    """
    HTTP client with consistent error handling for integrations.
    
    Features:
    - Automatic retry with exponential backoff
    - Timeout configuration
    - Error mapping to integration-specific exceptions
    - Request/response logging
    """
    
    def __init__(
        self,
        base_url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 30.0,
        max_retries: int = 3,
    ):
        """
        Initialize HTTP client.
        
        Args:
            base_url: Base URL for all requests
            headers: Default headers to include in all requests
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
        """
        self.base_url = base_url
        self.default_headers = headers or {}
        self.timeout = timeout
        self.max_retries = max_retries
    
    def _build_url(self, path: str) -> str:
        """Build full URL from base URL and path."""
        return urljoin(self.base_url, path.lstrip('/'))
    
    def _handle_response_error(self, response: httpx.Response):
        """
        Map HTTP errors to integration exceptions.
        
        Args:
            response: HTTP response object
            
        Raises:
            IntegrationAuthError: For 401/403 errors
            IntegrationNotFoundError: For 404 errors
            IntegrationRateLimitError: For 429 errors
            IntegrationValidationError: For 400/422 errors
            IntegrationError: For other errors
        """
        status = response.status_code
        
        if status == 401 or status == 403:
            raise IntegrationAuthError(
                f"Authentication failed: {response.text}"
            )
        
        if status == 404:
            raise IntegrationNotFoundError(
                f"Resource not found: {response.text}"
            )
        
        if status == 429:
            retry_after = response.headers.get('Retry-After')
            try:
                retry_after = int(retry_after) if retry_after else None
            except (ValueError, TypeError):
                retry_after = None
            
            raise IntegrationRateLimitError(
                f"Rate limit exceeded: {response.text}",
                retry_after=retry_after
            )
        
        if status == 400 or status == 422:
            raise IntegrationValidationError(
                f"Validation error: {response.text}"
            )
        
        if status >= 400:
            raise IntegrationError(
                f"HTTP {status} error: {response.text}"
            )
    
    def _request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> httpx.Response:
        """
        Make HTTP request with retry logic.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            path: URL path (relative to base_url)
            headers: Additional headers for this request
            params: Query parameters
            json: JSON body
            data: Form data
            
        Returns:
            HTTP response object
            
        Raises:
            IntegrationError: On HTTP errors or connection issues
        """
        url = self._build_url(path)
        
        # Merge headers
        request_headers = {**self.default_headers}
        if headers:
            request_headers.update(headers)
        
        # Retry logic
        last_exception = None
        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    response = client.request(
                        method=method,
                        url=url,
                        headers=request_headers,
                        params=params,
                        json=json,
                        data=data,
                    )
                    
                    # Check for HTTP errors
                    if response.status_code >= 400:
                        self._handle_response_error(response)
                    
                    return response
                    
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                last_exception = e
                if attempt < self.max_retries - 1:
                    wait_time = 2 ** attempt  # Exponential backoff
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{self.max_retries}): {e}. "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                continue
            
            except IntegrationError:
                # Don't retry on integration-specific errors
                raise
        
        # All retries failed
        raise IntegrationError(
            f"Request failed after {self.max_retries} attempts: {last_exception}"
        )
    
    def get(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make GET request and return JSON response."""
        response = self._request('GET', path, headers=headers, params=params)
        return response.json()
    
    def post(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        json: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make POST request and return JSON response."""
        response = self._request('POST', path, headers=headers, json=json, data=data)
        return response.json()
    
    def patch(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make PATCH request and return JSON response."""
        response = self._request('PATCH', path, headers=headers, json=json)
        return response.json()
    
    def put(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make PUT request and return JSON response."""
        response = self._request('PUT', path, headers=headers, json=json)
        return response.json()
    
    def delete(
        self,
        path: str,
        headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """Make DELETE request and return JSON response."""
        response = self._request('DELETE', path, headers=headers)
        # DELETE might return empty response
        try:
            return response.json()
        except Exception:
            return {}
