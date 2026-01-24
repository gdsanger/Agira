"""
Tests for Microsoft Graph API client.
"""

from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
from django.test import TestCase
from django.core.cache import cache

from core.models import GraphAPIConfiguration
from core.services.graph.client import GraphClient, get_client
from core.services.exceptions import ServiceDisabled, ServiceNotConfigured, ServiceError


class GraphClientTestCase(TestCase):
    """Test cases for the Graph API client."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Clear any existing configuration
        GraphAPIConfiguration.objects.all().delete()
        # Clear cache
        cache.clear()
    
    def test_client_raises_disabled_when_not_enabled(self):
        """Test that GraphClient raises ServiceDisabled when config is disabled."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=False
        )
        
        with self.assertRaises(ServiceDisabled):
            GraphClient()
    
    def test_client_raises_disabled_when_no_config(self):
        """Test that GraphClient raises ServiceDisabled when config doesn't exist."""
        with self.assertRaises(ServiceDisabled):
            GraphClient()
    
    def test_client_raises_not_configured_when_missing_tenant_id(self):
        """Test that GraphClient raises ServiceNotConfigured when tenant_id is missing."""
        GraphAPIConfiguration.objects.create(
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        with self.assertRaises(ServiceNotConfigured):
            GraphClient()
    
    def test_client_raises_not_configured_when_missing_client_id(self):
        """Test that GraphClient raises ServiceNotConfigured when client_id is missing."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_secret='test-secret',
            enabled=True
        )
        
        with self.assertRaises(ServiceNotConfigured):
            GraphClient()
    
    def test_client_raises_not_configured_when_missing_client_secret(self):
        """Test that GraphClient raises ServiceNotConfigured when client_secret is missing."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            enabled=True
        )
        
        with self.assertRaises(ServiceNotConfigured):
            GraphClient()
    
    @patch('core.services.graph.client.msal.ConfidentialClientApplication')
    def test_client_initializes_with_valid_config(self, mock_msal):
        """Test that GraphClient initializes successfully with valid config."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        client = GraphClient()
        self.assertIsNotNone(client)
        self.assertEqual(client.config.tenant_id, 'test-tenant')
    
    @patch('core.services.graph.client.msal.ConfidentialClientApplication')
    def test_get_access_token_acquires_new_token(self, mock_msal_class):
        """Test that get_access_token acquires a new token from MSAL."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        # Mock MSAL app
        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {
            'access_token': 'test-token-123',
            'expires_in': 3600
        }
        mock_msal_class.return_value = mock_app
        
        client = GraphClient()
        token = client.get_access_token()
        
        self.assertEqual(token, 'test-token-123')
        mock_app.acquire_token_for_client.assert_called_once()
    
    @patch('core.services.graph.client.msal.ConfidentialClientApplication')
    def test_get_access_token_uses_cache(self, mock_msal_class):
        """Test that get_access_token uses cached token when valid."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        # Mock MSAL app
        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {
            'access_token': 'test-token-123',
            'expires_in': 3600
        }
        mock_msal_class.return_value = mock_app
        
        client = GraphClient()
        
        # First call - should acquire token
        token1 = client.get_access_token()
        self.assertEqual(mock_app.acquire_token_for_client.call_count, 1)
        
        # Second call - should use cached token
        token2 = client.get_access_token()
        self.assertEqual(token1, token2)
        self.assertEqual(mock_app.acquire_token_for_client.call_count, 1)  # Still 1
    
    @patch('core.services.graph.client.msal.ConfidentialClientApplication')
    def test_get_access_token_refreshes_expired_token(self, mock_msal_class):
        """Test that get_access_token refreshes token when expired."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        # Mock MSAL app
        mock_app = Mock()
        mock_app.acquire_token_for_client.side_effect = [
            {'access_token': 'token-1', 'expires_in': 3600},
            {'access_token': 'token-2', 'expires_in': 3600},
        ]
        mock_msal_class.return_value = mock_app
        
        client = GraphClient()
        
        # First call
        token1 = client.get_access_token()
        self.assertEqual(token1, 'token-1')
        
        # Simulate token expiry by setting expiry to past
        client._token_expiry = datetime.now() - timedelta(minutes=10)
        
        # Second call - should refresh
        token2 = client.get_access_token()
        self.assertEqual(token2, 'token-2')
        self.assertEqual(mock_app.acquire_token_for_client.call_count, 2)
    
    @patch('core.services.graph.client.msal.ConfidentialClientApplication')
    def test_get_access_token_raises_on_error(self, mock_msal_class):
        """Test that get_access_token raises ServiceError on MSAL error."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        # Mock MSAL app to return error
        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {
            'error': 'invalid_client',
            'error_description': 'Invalid client credentials'
        }
        mock_msal_class.return_value = mock_app
        
        client = GraphClient()
        
        with self.assertRaises(ServiceError) as context:
            client.get_access_token()
        
        self.assertIn('Invalid client credentials', str(context.exception))
    
    @patch('core.services.graph.client.requests.request')
    @patch('core.services.graph.client.msal.ConfidentialClientApplication')
    def test_request_makes_http_call(self, mock_msal_class, mock_request):
        """Test that request makes HTTP call with correct headers."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        # Mock MSAL
        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {
            'access_token': 'test-token',
            'expires_in': 3600
        }
        mock_msal_class.return_value = mock_app
        
        # Mock HTTP response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'value': 'success'}
        mock_request.return_value = mock_response
        
        client = GraphClient()
        result = client.request('GET', '/users')
        
        self.assertEqual(result, {'value': 'success'})
        mock_request.assert_called_once()
        
        # Check that authorization header was set
        call_args = mock_request.call_args
        headers = call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer test-token')
    
    @patch('core.services.graph.client.requests.request')
    @patch('core.services.graph.client.msal.ConfidentialClientApplication')
    def test_request_handles_202_response(self, mock_msal_class, mock_request):
        """Test that request handles 202 Accepted response (returns None)."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        # Mock MSAL
        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {
            'access_token': 'test-token',
            'expires_in': 3600
        }
        mock_msal_class.return_value = mock_app
        
        # Mock 202 response
        mock_response = Mock()
        mock_response.status_code = 202
        mock_request.return_value = mock_response
        
        client = GraphClient()
        result = client.request('POST', '/users/test@test.com/sendMail')
        
        self.assertIsNone(result)
    
    @patch('core.services.graph.client.requests.request')
    @patch('core.services.graph.client.msal.ConfidentialClientApplication')
    def test_request_raises_on_error_status(self, mock_msal_class, mock_request):
        """Test that request raises ServiceError on HTTP error status."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        # Mock MSAL
        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {
            'access_token': 'test-token',
            'expires_in': 3600
        }
        mock_msal_class.return_value = mock_app
        
        # Mock error response
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = 'Unauthorized'
        mock_response.json.side_effect = ValueError()
        mock_request.return_value = mock_response
        
        client = GraphClient()
        
        with self.assertRaises(ServiceError) as context:
            client.request('GET', '/users')
        
        self.assertIn('401', str(context.exception))
    
    @patch('core.services.graph.client.msal.ConfidentialClientApplication')
    def test_send_mail_calls_request(self, mock_msal_class):
        """Test that send_mail calls request with correct parameters."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        # Mock MSAL
        mock_app = Mock()
        mock_app.acquire_token_for_client.return_value = {
            'access_token': 'test-token',
            'expires_in': 3600
        }
        mock_msal_class.return_value = mock_app
        
        client = GraphClient()
        
        # Mock the request method
        with patch.object(client, 'request') as mock_request:
            mock_request.return_value = None  # 202 Accepted
            
            payload = {'message': {'subject': 'Test'}}
            client.send_mail('user@test.com', payload)
            
            mock_request.assert_called_once_with(
                'POST',
                '/users/user@test.com/sendMail',
                json=payload
            )
    
    def test_get_client_function(self):
        """Test that get_client() returns a GraphClient instance."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        client = get_client()
        self.assertIsInstance(client, GraphClient)
