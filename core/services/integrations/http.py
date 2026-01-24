"""
HTTP client wrapper for integration services.

Provides consistent error handling, timeouts, and retry logic for HTTP requests.

Logging Guidelines:
- Logs method + host + path (no tokens/keys)
- On errors: status code + truncated response (max 500 chars)
- Never logs Authorization headers or API keys

Retry Strategy:
- Default: max 3 attempts
- Exponential backoff: 0.5s, 1s, 2s
- Retries on: timeouts, connection errors, 429, 5xx
- No retry on: 4xx (except 429), validation errors
"""

import logging
import time
from typing import Optional, Dict, Any, Union
from urllib.parse import urljoin, urlparse

import httpx

from .errors import (
    IntegrationError,
    IntegrationAuthError,
    IntegrationRateLimited,
    IntegrationTemporaryError,
    IntegrationPermanentError,
)

logger = logging.getLogger(__name__)

# Maximum response text length to include in error messages
MAX_ERROR_RESPONSE_LENGTH = 500


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
    
    def _sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        Remove sensitive headers for logging.
        
        Args:
            headers: Original headers
            
        Returns:
            Sanitized headers safe for logging
        """
        sensitive_keys = {'authorization', 'x-api-key', 'api-key', 'token'}
        return {
            k: '***' if k.lower() in sensitive_keys else v
            for k, v in headers.items()
        }
    
    def _truncate_response(self, text: str) -> str:
        """
        Truncate response text for error messages.
        
        Args:
            text: Response text
            
        Returns:
            Truncated text (max MAX_ERROR_RESPONSE_LENGTH chars)
        """
        if len(text) > MAX_ERROR_RESPONSE_LENGTH:
            return text[:MAX_ERROR_RESPONSE_LENGTH] + "..."
        return text
    
    def _build_url(self, path: str) -> str:
        """Build full URL from base URL and path."""
        return urljoin(self.base_url, path.lstrip('/'))
    
    def _handle_response_error(self, response: httpx.Response):
        """
        Map HTTP errors to integration exceptions.
        
        Maps according to spec:
        - 401/403 → IntegrationAuthError
        - 429 → IntegrationRateLimited (with retry_after)
        - 5xx → IntegrationTemporaryError (retryable)
        - 4xx → IntegrationPermanentError (not retryable)
        
        Args:
            response: HTTP response object
            
        Raises:
            IntegrationAuthError: For 401/403 errors
            IntegrationRateLimited: For 429 errors
            IntegrationTemporaryError: For 5xx errors
            IntegrationPermanentError: For other 4xx errors
        """
        status = response.status_code
        truncated_text = self._truncate_response(response.text)
        
        # Authentication errors (401/403)
        if status in (401, 403):
            raise IntegrationAuthError(
                f"Authentication failed (HTTP {status}): {truncated_text}"
            )
        
        # Rate limiting (429)
        if status == 429:
            retry_after = response.headers.get('Retry-After')
            try:
                retry_after = int(retry_after) if retry_after else None
            except (ValueError, TypeError):
                retry_after = None
            
            raise IntegrationRateLimited(
                f"Rate limit exceeded: {truncated_text}",
                retry_after=retry_after
            )
        
        # Server errors (5xx) - temporary, retryable
        if status >= 500:
            raise IntegrationTemporaryError(
                f"Server error (HTTP {status}): {truncated_text}"
            )
        
        # Client errors (4xx) - permanent, not retryable
        if status >= 400:
            raise IntegrationPermanentError(
                f"Client error (HTTP {status}): {truncated_text}"
            )
    
    def _should_retry(self, exception: Exception, attempt: int) -> bool:
        """
        Determine if a request should be retried.
        
        Retry on:
        - Timeouts and connection errors
        - 429 rate limits
        - 5xx server errors (IntegrationTemporaryError)
        
        Do not retry on:
        - 4xx client errors (IntegrationPermanentError)
        - Authentication errors
        
        Args:
            exception: The exception that occurred
            attempt: Current attempt number (0-indexed)
            
        Returns:
            True if should retry, False otherwise
        """
        # Already at max retries
        if attempt >= self.max_retries - 1:
            return False
        
        # Retry on network/timeout errors
        if isinstance(exception, (httpx.TimeoutException, httpx.ConnectError)):
            return True
        
        # Retry on temporary errors (5xx)
        if isinstance(exception, IntegrationTemporaryError):
            return True
        
        # Retry on rate limits (429)
        if isinstance(exception, IntegrationRateLimited):
            return True
        
        # Don't retry on other integration errors
        return False
    
    def _get_backoff_time(self, attempt: int, retry_after: Optional[int] = None) -> float:
        """
        Calculate backoff time for retry.
        
        Uses exponential backoff: 0.5s, 1s, 2s
        Respects Retry-After header if provided.
        
        Args:
            attempt: Current attempt number (0-indexed)
            retry_after: Optional Retry-After value in seconds
            
        Returns:
            Seconds to wait before retry
        """
        if retry_after is not None:
            return float(retry_after)
        
        # Exponential backoff: 0.5 * (2 ** attempt)
        # attempt 0: 0.5s, attempt 1: 1s, attempt 2: 2s
        return 0.5 * (2 ** attempt)
    
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
        parsed = urlparse(url)
        
        # Merge headers
        request_headers = {**self.default_headers}
        if headers:
            request_headers.update(headers)
        
        # Log request (without sensitive data)
        safe_headers = self._sanitize_headers(request_headers)
        logger.debug(
            f"{method} {parsed.scheme}://{parsed.netloc}{parsed.path}"
        )
        
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
                    
            except Exception as e:
                last_exception = e
                
                # Check if we should retry
                if self._should_retry(e, attempt):
                    # Get backoff time
                    retry_after = None
                    if isinstance(e, IntegrationRateLimited):
                        retry_after = e.retry_after
                    
                    wait_time = self._get_backoff_time(attempt, retry_after)
                    
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}/{self.max_retries}): "
                        f"{e.__class__.__name__}: {str(e)[:200]}. "
                        f"Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    # Don't retry, raise immediately
                    raise
        
        # All retries failed
        raise IntegrationTemporaryError(
            f"Request failed after {self.max_retries} attempts: {last_exception}"
        )
    
    def request_json(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Make HTTP request and return JSON response.
        
        Convenience method that follows the spec from the issue.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: URL path (relative to base_url)
            headers: Optional headers
            params: Optional query parameters
            json: Optional JSON body
            timeout: Optional timeout override
            
        Returns:
            Parsed JSON response or None if response is empty
        """
        # Temporarily override timeout if provided
        original_timeout = self.timeout
        if timeout is not None:
            self.timeout = timeout
        
        try:
            response = self._request(method, url, headers=headers, params=params, json=json)
            try:
                return response.json()
            except (ValueError, httpx.ResponseNotRead):
                return None
        finally:
            self.timeout = original_timeout
    
    def request_bytes(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Optional[bytes]:
        """
        Make HTTP request and return raw bytes.
        
        Useful for downloading files, images, etc.
        
        Args:
            method: HTTP method (GET, POST, etc.)
            url: URL path (relative to base_url)
            headers: Optional headers
            params: Optional query parameters
            json: Optional JSON body
            timeout: Optional timeout override
            
        Returns:
            Response content as bytes or None if empty
        """
        # Temporarily override timeout if provided
        original_timeout = self.timeout
        if timeout is not None:
            self.timeout = timeout
        
        try:
            response = self._request(method, url, headers=headers, params=params, json=json)
            return response.content if response.content else None
        finally:
            self.timeout = original_timeout
    
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
        except (ValueError, httpx.ResponseNotRead):
            # Empty response or non-JSON response is acceptable for DELETE
            return {}
