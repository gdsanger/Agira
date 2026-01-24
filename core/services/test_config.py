"""
Tests for the core configuration service layer.
"""

from django.test import TestCase
from django.core.cache import cache

from core.models import (
    GitHubConfiguration,
    WeaviateConfiguration,
    GooglePSEConfiguration,
    GraphAPIConfiguration,
    ZammadConfiguration,
)
from core.services import config
from core.services.exceptions import ServiceError, ServiceNotConfigured, ServiceDisabled


class ConfigServiceTestCase(TestCase):
    """Test cases for the configuration service layer."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Clear cache before each test
        cache.clear()
    
    def tearDown(self):
        """Clean up after each test."""
        # Clear cache after each test
        cache.clear()
    
    def test_get_singleton_returns_none_when_not_configured(self):
        """Test that get_singleton returns None when config doesn't exist."""
        result = config.get_singleton(GitHubConfiguration)
        self.assertIsNone(result)
    
    def test_get_singleton_returns_instance_when_configured(self):
        """Test that get_singleton returns the singleton instance."""
        # Create a GitHub configuration
        gh_config = GitHubConfiguration.objects.create(
            app_id='test-app-id',
            installation_id='test-install-id',
            enabled=True
        )
        
        result = config.get_singleton(GitHubConfiguration)
        self.assertIsNotNone(result)
        self.assertEqual(result.app_id, 'test-app-id')
        self.assertEqual(result.pk, gh_config.pk)
    
    def test_get_singleton_uses_cache(self):
        """Test that get_singleton uses caching to avoid DB queries."""
        # Create config
        GitHubConfiguration.objects.create(
            app_id='test-app-id',
            enabled=True
        )
        
        # First call should hit the database
        result1 = config.get_singleton(GitHubConfiguration)
        
        # Delete from database
        GitHubConfiguration.objects.all().delete()
        
        # Second call should return cached value (not None)
        result2 = config.get_singleton(GitHubConfiguration)
        
        self.assertIsNotNone(result2)
        self.assertEqual(result1.app_id, result2.app_id)
    
    def test_invalidate_singleton_clears_cache(self):
        """Test that invalidate_singleton clears the cache."""
        # Create config
        GitHubConfiguration.objects.create(
            app_id='test-app-id',
            enabled=True
        )
        
        # Load into cache
        config.get_singleton(GitHubConfiguration)
        
        # Invalidate cache
        config.invalidate_singleton(GitHubConfiguration)
        
        # Delete from database
        GitHubConfiguration.objects.all().delete()
        
        # Should return None now (cache was cleared)
        result = config.get_singleton(GitHubConfiguration)
        self.assertIsNone(result)
    
    def test_get_github_config(self):
        """Test get_github_config helper function."""
        GitHubConfiguration.objects.create(
            app_id='test-app-id',
            enabled=True
        )
        
        result = config.get_github_config()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, GitHubConfiguration)
    
    def test_is_github_enabled_returns_false_when_not_configured(self):
        """Test is_github_enabled returns False when config doesn't exist."""
        self.assertFalse(config.is_github_enabled())
    
    def test_is_github_enabled_returns_false_when_disabled(self):
        """Test is_github_enabled returns False when explicitly disabled."""
        GitHubConfiguration.objects.create(
            app_id='test-app-id',
            enabled=False
        )
        
        self.assertFalse(config.is_github_enabled())
    
    def test_is_github_enabled_returns_true_when_enabled(self):
        """Test is_github_enabled returns True when enabled."""
        GitHubConfiguration.objects.create(
            app_id='test-app-id',
            enabled=True
        )
        
        self.assertTrue(config.is_github_enabled())
    
    def test_get_weaviate_config(self):
        """Test get_weaviate_config helper function."""
        WeaviateConfiguration.objects.create(
            url='http://localhost:8080',
            enabled=True
        )
        
        result = config.get_weaviate_config()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, WeaviateConfiguration)
    
    def test_is_weaviate_enabled_returns_false_when_not_configured(self):
        """Test is_weaviate_enabled returns False when config doesn't exist."""
        self.assertFalse(config.is_weaviate_enabled())
    
    def test_is_weaviate_enabled_returns_false_when_disabled(self):
        """Test is_weaviate_enabled returns False when explicitly disabled."""
        WeaviateConfiguration.objects.create(
            url='http://localhost:8080',
            enabled=False
        )
        
        self.assertFalse(config.is_weaviate_enabled())
    
    def test_is_weaviate_enabled_returns_true_when_enabled(self):
        """Test is_weaviate_enabled returns True when enabled."""
        WeaviateConfiguration.objects.create(
            url='http://localhost:8080',
            enabled=True
        )
        
        self.assertTrue(config.is_weaviate_enabled())
    
    def test_get_google_pse_config(self):
        """Test get_google_pse_config helper function."""
        GooglePSEConfiguration.objects.create(
            search_engine_id='test-engine-id',
            enabled=True
        )
        
        result = config.get_google_pse_config()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, GooglePSEConfiguration)
    
    def test_is_google_pse_enabled_returns_false_when_not_configured(self):
        """Test is_google_pse_enabled returns False when config doesn't exist."""
        self.assertFalse(config.is_google_pse_enabled())
    
    def test_is_google_pse_enabled_returns_false_when_disabled(self):
        """Test is_google_pse_enabled returns False when explicitly disabled."""
        GooglePSEConfiguration.objects.create(
            search_engine_id='test-engine-id',
            enabled=False
        )
        
        self.assertFalse(config.is_google_pse_enabled())
    
    def test_is_google_pse_enabled_returns_true_when_enabled(self):
        """Test is_google_pse_enabled returns True when enabled."""
        GooglePSEConfiguration.objects.create(
            search_engine_id='test-engine-id',
            enabled=True
        )
        
        self.assertTrue(config.is_google_pse_enabled())
    
    def test_get_graph_config(self):
        """Test get_graph_config helper function."""
        GraphAPIConfiguration.objects.create(
            client_id='test-client-id',
            enabled=True
        )
        
        result = config.get_graph_config()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, GraphAPIConfiguration)
    
    def test_is_graph_enabled_returns_false_when_not_configured(self):
        """Test is_graph_enabled returns False when config doesn't exist."""
        self.assertFalse(config.is_graph_enabled())
    
    def test_is_graph_enabled_returns_false_when_disabled(self):
        """Test is_graph_enabled returns False when explicitly disabled."""
        GraphAPIConfiguration.objects.create(
            client_id='test-client-id',
            enabled=False
        )
        
        self.assertFalse(config.is_graph_enabled())
    
    def test_is_graph_enabled_returns_true_when_enabled(self):
        """Test is_graph_enabled returns True when enabled."""
        GraphAPIConfiguration.objects.create(
            client_id='test-client-id',
            enabled=True
        )
        
        self.assertTrue(config.is_graph_enabled())
    
    def test_get_zammad_config(self):
        """Test get_zammad_config helper function."""
        ZammadConfiguration.objects.create(
            url='http://localhost:3000',
            enabled=True
        )
        
        result = config.get_zammad_config()
        self.assertIsNotNone(result)
        self.assertIsInstance(result, ZammadConfiguration)
    
    def test_is_zammad_enabled_returns_false_when_not_configured(self):
        """Test is_zammad_enabled returns False when config doesn't exist."""
        self.assertFalse(config.is_zammad_enabled())
    
    def test_is_zammad_enabled_returns_false_when_disabled(self):
        """Test is_zammad_enabled returns False when explicitly disabled."""
        ZammadConfiguration.objects.create(
            url='http://localhost:3000',
            enabled=False
        )
        
        self.assertFalse(config.is_zammad_enabled())
    
    def test_is_zammad_enabled_returns_true_when_enabled(self):
        """Test is_zammad_enabled returns True when enabled."""
        ZammadConfiguration.objects.create(
            url='http://localhost:3000',
            enabled=True
        )
        
        self.assertTrue(config.is_zammad_enabled())


class ExceptionsTestCase(TestCase):
    """Test cases for service exceptions."""
    
    def test_service_error_is_exception(self):
        """Test that ServiceError is a proper Exception."""
        error = ServiceError("Test error")
        self.assertIsInstance(error, Exception)
        self.assertEqual(str(error), "Test error")
    
    def test_service_not_configured_is_service_error(self):
        """Test that ServiceNotConfigured inherits from ServiceError."""
        error = ServiceNotConfigured("Config missing")
        self.assertIsInstance(error, ServiceError)
        self.assertIsInstance(error, Exception)
    
    def test_service_disabled_is_service_error(self):
        """Test that ServiceDisabled inherits from ServiceError."""
        error = ServiceDisabled("Service is disabled")
        self.assertIsInstance(error, ServiceError)
        self.assertIsInstance(error, Exception)
