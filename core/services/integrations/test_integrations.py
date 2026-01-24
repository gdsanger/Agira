"""
Tests for the integration base classes and utilities.
"""

from unittest.mock import Mock, patch
from django.test import TestCase
import httpx
import respx

from core.services.integrations import (
    # Exceptions
    IntegrationError,
    IntegrationDisabled,
    IntegrationNotConfigured,
    IntegrationAuthError,
    IntegrationRateLimited,
    IntegrationTemporaryError,
    IntegrationPermanentError,
    # Classes
    BaseIntegration,
    HTTPClient,
)
from core.models import GitHubConfiguration


class IntegrationExceptionsTestCase(TestCase):
    """Test cases for integration exceptions."""
    
    def test_integration_error_is_base(self):
        """Test that IntegrationError is the base for all integration errors."""
        error = IntegrationError("test")
        self.assertIsInstance(error, Exception)
    
    def test_all_exceptions_inherit_from_integration_error(self):
        """Test that all integration exceptions inherit from IntegrationError."""
        exceptions = [
            IntegrationDisabled("test"),
            IntegrationNotConfigured("test"),
            IntegrationAuthError("test"),
            IntegrationRateLimited("test"),
            IntegrationTemporaryError("test"),
            IntegrationPermanentError("test"),
        ]
        
        for exc in exceptions:
            with self.subTest(exc=exc):
                self.assertIsInstance(exc, IntegrationError)
    
    def test_rate_limited_has_retry_after(self):
        """Test that IntegrationRateLimited can store retry_after."""
        error = IntegrationRateLimited("Rate limited", retry_after=60)
        self.assertEqual(error.retry_after, 60)
    
    def test_rate_limited_retry_after_optional(self):
        """Test that retry_after is optional for IntegrationRateLimited."""
        error = IntegrationRateLimited("Rate limited")
        self.assertIsNone(error.retry_after)


class TestIntegration(BaseIntegration):
    """Test integration for testing BaseIntegration."""
    
    name = "test"
    
    def __init__(self, config_model=None, is_complete=True):
        self._config_model = config_model or GitHubConfiguration
        self._is_complete = is_complete
        super().__init__()
    
    def _get_config_model(self):
        return self._config_model
    
    def _is_config_complete(self, config):
        return self._is_complete


class BaseIntegrationTestCase(TestCase):
    """Test cases for BaseIntegration class."""
    
    def setUp(self):
        """Clear cache before each test."""
        from django.core.cache import cache
        cache.clear()
    
    def tearDown(self):
        """Clear cache after each test."""
        from django.core.cache import cache
        cache.clear()
    
    def test_name_property_required(self):
        """Test that name property must be set."""
        class BadIntegration(BaseIntegration):
            pass
        
        with self.assertRaises(NotImplementedError):
            BadIntegration()
    
    def test_logger_has_correct_namespace(self):
        """Test that logger uses agira.integration.<name> namespace."""
        integration = TestIntegration()
        self.assertEqual(integration.logger.name, "agira.integration.test")
    
    def test_get_config_returns_none_when_not_configured(self):
        """Test that get_config returns None when no config exists."""
        integration = TestIntegration()
        config = integration.get_config()
        self.assertIsNone(config)
    
    def test_get_config_returns_config_when_configured(self):
        """Test that get_config returns config object."""
        GitHubConfiguration.objects.create(
            app_id='test-app',
            enabled=True
        )
        
        integration = TestIntegration()
        config = integration.get_config()
        
        self.assertIsNotNone(config)
        self.assertEqual(config.app_id, 'test-app')
    
    def test_enabled_returns_false_when_not_configured(self):
        """Test that enabled() returns False when no config."""
        integration = TestIntegration()
        self.assertFalse(integration.enabled())
    
    def test_enabled_returns_false_when_disabled(self):
        """Test that enabled() returns False when config disabled."""
        GitHubConfiguration.objects.create(
            app_id='test-app',
            enabled=False
        )
        
        integration = TestIntegration()
        self.assertFalse(integration.enabled())
    
    def test_enabled_returns_true_when_enabled(self):
        """Test that enabled() returns True when config enabled."""
        GitHubConfiguration.objects.create(
            app_id='test-app',
            enabled=True
        )
        
        integration = TestIntegration()
        self.assertTrue(integration.enabled())
    
    def test_require_enabled_raises_when_disabled(self):
        """Test that require_enabled raises when integration disabled."""
        integration = TestIntegration()
        
        with self.assertRaises(IntegrationDisabled) as cm:
            integration.require_enabled()
        
        self.assertIn("test", str(cm.exception))
    
    def test_require_enabled_succeeds_when_enabled(self):
        """Test that require_enabled succeeds when enabled."""
        GitHubConfiguration.objects.create(
            app_id='test-app',
            enabled=True
        )
        
        integration = TestIntegration()
        # Should not raise
        integration.require_enabled()
    
    def test_require_config_raises_when_disabled(self):
        """Test that require_config raises when disabled."""
        integration = TestIntegration()
        
        with self.assertRaises(IntegrationDisabled):
            integration.require_config()
    
    def test_require_config_raises_when_config_incomplete(self):
        """Test that require_config raises when config incomplete."""
        GitHubConfiguration.objects.create(
            app_id='test-app',
            enabled=True
        )
        
        integration = TestIntegration(is_complete=False)
        
        with self.assertRaises(IntegrationNotConfigured) as cm:
            integration.require_config()
        
        self.assertIn("test", str(cm.exception))
    
    def test_require_config_returns_config_when_complete(self):
        """Test that require_config returns config when complete."""
        config = GitHubConfiguration.objects.create(
            app_id='test-app',
            enabled=True
        )
        
        integration = TestIntegration(is_complete=True)
        result = integration.require_config()
        
        self.assertEqual(result.pk, config.pk)


@respx.mock
class HTTPClientTestCase(TestCase):
    """Test cases for HTTPClient class."""
    
    def setUp(self):
        """Set up test client."""
        self.base_url = "https://api.example.com"
        self.client = HTTPClient(
            base_url=self.base_url,
            timeout=10.0,
            max_retries=3
        )
    
    def test_successful_get_request(self):
        """Test successful GET request."""
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        
        result = self.client.get("/test")
        self.assertEqual(result, {"status": "ok"})
    
    def test_successful_post_request(self):
        """Test successful POST request."""
        respx.post(f"{self.base_url}/test").mock(
            return_value=httpx.Response(201, json={"id": 123})
        )
        
        result = self.client.post("/test", json={"name": "test"})
        self.assertEqual(result, {"id": 123})
    
    def test_401_raises_auth_error(self):
        """Test that 401 raises IntegrationAuthError."""
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(401, json={"error": "Unauthorized"})
        )
        
        with self.assertRaises(IntegrationAuthError) as cm:
            self.client.get("/test")
        
        self.assertIn("401", str(cm.exception))
    
    def test_403_raises_auth_error(self):
        """Test that 403 raises IntegrationAuthError."""
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(403, json={"error": "Forbidden"})
        )
        
        with self.assertRaises(IntegrationAuthError) as cm:
            self.client.get("/test")
        
        self.assertIn("403", str(cm.exception))
    
    def test_429_raises_rate_limited(self):
        """Test that 429 raises IntegrationRateLimited."""
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(
                429,
                headers={"Retry-After": "60"},
                json={"error": "Rate limited"}
            )
        )
        
        with self.assertRaises(IntegrationRateLimited) as cm:
            self.client.get("/test")
        
        self.assertEqual(cm.exception.retry_after, 60)
    
    def test_500_raises_temporary_error(self):
        """Test that 500 raises IntegrationTemporaryError."""
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(500, text="Internal Server Error")
        )
        
        with self.assertRaises(IntegrationTemporaryError) as cm:
            self.client.get("/test")
        
        self.assertIn("500", str(cm.exception))
    
    def test_503_raises_temporary_error(self):
        """Test that 503 raises IntegrationTemporaryError."""
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(503, text="Service Unavailable")
        )
        
        with self.assertRaises(IntegrationTemporaryError) as cm:
            self.client.get("/test")
        
        self.assertIn("503", str(cm.exception))
    
    def test_400_raises_permanent_error(self):
        """Test that 400 raises IntegrationPermanentError."""
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(400, json={"error": "Bad Request"})
        )
        
        with self.assertRaises(IntegrationPermanentError) as cm:
            self.client.get("/test")
        
        self.assertIn("400", str(cm.exception))
    
    def test_404_raises_permanent_error(self):
        """Test that 404 raises IntegrationPermanentError."""
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(404, json={"error": "Not Found"})
        )
        
        with self.assertRaises(IntegrationPermanentError) as cm:
            self.client.get("/test")
        
        self.assertIn("404", str(cm.exception))
    
    def test_retry_on_500_error(self):
        """Test that 500 errors are retried."""
        # First request fails with 500, second succeeds
        route = respx.get(f"{self.base_url}/test")
        route.side_effect = [
            httpx.Response(500, text="Server Error"),
            httpx.Response(200, json={"status": "ok"}),
        ]
        
        result = self.client.get("/test")
        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(route.call_count, 2)
    
    def test_retry_on_timeout(self):
        """Test that timeout errors are retried."""
        route = respx.get(f"{self.base_url}/test")
        route.side_effect = [
            httpx.TimeoutException("Timeout"),
            httpx.Response(200, json={"status": "ok"}),
        ]
        
        result = self.client.get("/test")
        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(route.call_count, 2)
    
    def test_no_retry_on_auth_error(self):
        """Test that auth errors are not retried."""
        route = respx.get(f"{self.base_url}/test")
        route.mock(return_value=httpx.Response(401, text="Unauthorized"))
        
        with self.assertRaises(IntegrationAuthError):
            self.client.get("/test")
        
        # Should only be called once (no retry)
        self.assertEqual(route.call_count, 1)
    
    def test_no_retry_on_permanent_error(self):
        """Test that permanent errors are not retried."""
        route = respx.get(f"{self.base_url}/test")
        route.mock(return_value=httpx.Response(400, text="Bad Request"))
        
        with self.assertRaises(IntegrationPermanentError):
            self.client.get("/test")
        
        # Should only be called once (no retry)
        self.assertEqual(route.call_count, 1)
    
    def test_max_retries_reached(self):
        """Test that retry stops after max_retries."""
        route = respx.get(f"{self.base_url}/test")
        route.mock(return_value=httpx.Response(500, text="Server Error"))
        
        with self.assertRaises(IntegrationTemporaryError):
            self.client.get("/test")
        
        # Should be called max_retries times
        self.assertEqual(route.call_count, 3)
    
    def test_request_json_method(self):
        """Test request_json convenience method."""
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(200, json={"data": "value"})
        )
        
        result = self.client.request_json("GET", "/test")
        self.assertEqual(result, {"data": "value"})
    
    def test_request_bytes_method(self):
        """Test request_bytes convenience method."""
        content = b"binary data"
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(200, content=content)
        )
        
        result = self.client.request_bytes("GET", "/test")
        self.assertEqual(result, content)
    
    def test_truncate_long_response_in_error(self):
        """Test that long responses are truncated in error messages."""
        long_text = "x" * 1000
        respx.get(f"{self.base_url}/test").mock(
            return_value=httpx.Response(400, text=long_text)
        )
        
        with self.assertRaises(IntegrationPermanentError) as cm:
            self.client.get("/test")
        
        # Error message should be truncated to 500 chars + "..."
        error_msg = str(cm.exception)
        self.assertLess(len(error_msg), 600)  # Should be around 500 + some metadata
        self.assertIn("...", error_msg)
    
    def test_exponential_backoff(self):
        """Test exponential backoff timing."""
        import time
        
        route = respx.get(f"{self.base_url}/test")
        route.side_effect = [
            httpx.Response(500, text="Error"),
            httpx.Response(500, text="Error"),
            httpx.Response(200, json={"status": "ok"}),
        ]
        
        start = time.time()
        result = self.client.get("/test")
        elapsed = time.time() - start
        
        # Should have waited: 0.5s + 1s = 1.5s (approximately)
        # Allow some tolerance for test execution
        self.assertGreater(elapsed, 1.4)
        self.assertLess(elapsed, 2.0)
        self.assertEqual(result, {"status": "ok"})
