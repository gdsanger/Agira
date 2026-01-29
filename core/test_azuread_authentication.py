"""
Tests for Azure AD authentication functionality
"""

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from unittest.mock import patch, MagicMock
from core.models import User
from core.backends.azuread import AzureADAuth, AzureADAuthError
import jwt
import time


@override_settings(
    AZURE_AD_ENABLED=True,
    AZURE_AD_TENANT_ID='test-tenant-id',
    AZURE_AD_CLIENT_ID='test-client-id',
    AZURE_AD_CLIENT_SECRET='test-client-secret',
    AZURE_AD_REDIRECT_URI='http://testserver/auth/azuread/callback/',
    AZURE_AD_DEFAULT_ROLE='User',
    AZURE_AD_AUTHORITY='https://login.microsoftonline.com/test-tenant-id'
)
class AzureADAuthenticationTestCase(TestCase):
    """Test cases for Azure AD authentication functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test user with Azure AD
        self.azure_user = User.objects.create_user(
            username='azureuser',
            email='azureuser@example.com',
            password='',  # No password for Azure AD users
            name='Azure User',
            azure_ad_object_id='azure-ad-object-123'
        )
        self.azure_user.active = True
        self.azure_user.save()
        
        # Create regular user without Azure AD
        self.regular_user = User.objects.create_user(
            username='regularuser',
            email='regular@example.com',
            password='testpass123',
            name='Regular User'
        )
        self.regular_user.active = True
        self.regular_user.save()
    
    def test_azuread_login_disabled(self):
        """Test Azure AD login when disabled"""
        with override_settings(AZURE_AD_ENABLED=False):
            response = self.client.get(reverse('azuread-login'))
            self.assertEqual(response.status_code, 200)
            self.assertTemplateUsed(response, 'login.html')
            self.assertIn('error', response.context)
            self.assertIn('nicht verfügbar', response.context['error'])
    
    @patch('core.backends.azuread.msal.ConfidentialClientApplication')
    def test_azuread_login_redirects_to_azure(self, mock_msal):
        """Test Azure AD login initiates redirect to Azure"""
        # Mock MSAL app
        mock_app = MagicMock()
        mock_app.get_authorization_request_url.return_value = 'https://login.microsoftonline.com/test-tenant-id/oauth2/v2.0/authorize?...'
        mock_msal.return_value = mock_app
        
        response = self.client.get(reverse('azuread-login'))
        
        # Should redirect to Azure AD
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('https://login.microsoftonline.com'))
        
        # State should be stored in session
        self.assertIn('azure_ad_state', self.client.session)
    
    @patch('core.backends.azuread.msal.ConfidentialClientApplication')
    def test_azuread_login_with_next_parameter(self, mock_msal):
        """Test Azure AD login stores next parameter"""
        # Mock MSAL app
        mock_app = MagicMock()
        mock_app.get_authorization_request_url.return_value = 'https://login.microsoftonline.com/...'
        mock_msal.return_value = mock_app
        
        next_url = reverse('projects')
        response = self.client.get(reverse('azuread-login') + f'?next={next_url}')
        
        # Next URL should be stored in session
        self.assertEqual(self.client.session['azure_ad_next'], next_url)
    
    def test_azuread_callback_missing_code(self):
        """Test Azure AD callback with missing code"""
        response = self.client.get(reverse('azuread-callback'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')
        self.assertIn('error', response.context)
    
    def test_azuread_callback_with_error(self):
        """Test Azure AD callback with error from Azure"""
        response = self.client.get(reverse('azuread-callback') + '?error=access_denied&error_description=User denied')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')
        self.assertIn('error', response.context)
    
    def test_azuread_callback_state_mismatch(self):
        """Test Azure AD callback with state token mismatch (CSRF protection)"""
        # Set a different state in session
        session = self.client.session
        session['azure_ad_state'] = 'different-state'
        session.save()
        
        response = self.client.get(reverse('azuread-callback') + '?code=test-code&state=wrong-state')
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')
        self.assertIn('error', response.context)
        self.assertIn('Sicherheitsvalidierung', response.context['error'])
    
    @patch('core.backends.azuread.msal.ConfidentialClientApplication')
    @patch('core.backends.azuread.jwt.decode')
    def test_azuread_callback_successful_existing_user(self, mock_jwt_decode, mock_msal):
        """Test successful Azure AD callback for existing user"""
        # Set state in session
        session = self.client.session
        session['azure_ad_state'] = 'test-state'
        session.save()
        
        # Mock MSAL token acquisition
        mock_app = MagicMock()
        mock_app.acquire_token_by_authorization_code.return_value = {
            'id_token': 'mock-id-token',
            'access_token': 'mock-access-token'
        }
        mock_msal.return_value = mock_app
        
        # Mock JWT decode
        mock_jwt_decode.return_value = {
            'oid': 'azure-ad-object-123',
            'email': 'azureuser@example.com',
            'name': 'Azure User',
            'iss': 'https://login.microsoftonline.com/test-tenant-id/v2.0',
            'aud': 'test-client-id',
            'exp': int(time.time()) + 3600
        }
        
        response = self.client.get(reverse('azuread-callback') + '?code=test-code&state=test-state')
        
        # Should redirect to dashboard
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, 'dashboard')
        
        # User should be authenticated
        self.assertTrue('_auth_user_id' in self.client.session)
        
        # Should be the existing user
        user_id = self.client.session['_auth_user_id']
        self.assertEqual(int(user_id), self.azure_user.id)
    
    @patch('core.backends.azuread.msal.ConfidentialClientApplication')
    @patch('core.backends.azuread.jwt.decode')
    def test_azuread_callback_auto_provision_new_user(self, mock_jwt_decode, mock_msal):
        """Test Azure AD callback auto-provisions new user"""
        # Set state in session
        session = self.client.session
        session['azure_ad_state'] = 'test-state'
        session.save()
        
        # Mock MSAL token acquisition
        mock_app = MagicMock()
        mock_app.acquire_token_by_authorization_code.return_value = {
            'id_token': 'mock-id-token',
            'access_token': 'mock-access-token'
        }
        mock_msal.return_value = mock_app
        
        # Mock JWT decode for new user
        mock_jwt_decode.return_value = {
            'oid': 'new-azure-ad-object-456',
            'email': 'newuser@example.com',
            'name': 'New Azure User',
            'iss': 'https://login.microsoftonline.com/test-tenant-id/v2.0',
            'aud': 'test-client-id',
            'exp': int(time.time()) + 3600
        }
        
        # Get initial user count
        initial_count = User.objects.count()
        
        response = self.client.get(reverse('azuread-callback') + '?code=test-code&state=test-state')
        
        # Should redirect to dashboard
        self.assertEqual(response.status_code, 302)
        
        # New user should be created
        self.assertEqual(User.objects.count(), initial_count + 1)
        
        # Verify new user details
        new_user = User.objects.get(email='newuser@example.com')
        self.assertEqual(new_user.azure_ad_object_id, 'new-azure-ad-object-456')
        self.assertEqual(new_user.name, 'New Azure User')
        self.assertEqual(new_user.role, 'User')  # Default role
        self.assertTrue(new_user.active)
    
    @patch('core.backends.azuread.msal.ConfidentialClientApplication')
    @patch('core.backends.azuread.jwt.decode')
    def test_azuread_callback_links_existing_user_by_email(self, mock_jwt_decode, mock_msal):
        """Test Azure AD callback links existing user by email"""
        # Set state in session
        session = self.client.session
        session['azure_ad_state'] = 'test-state'
        session.save()
        
        # Mock MSAL token acquisition
        mock_app = MagicMock()
        mock_app.acquire_token_by_authorization_code.return_value = {
            'id_token': 'mock-id-token',
            'access_token': 'mock-access-token'
        }
        mock_msal.return_value = mock_app
        
        # Mock JWT decode with email matching regular_user but no azure_ad_object_id
        mock_jwt_decode.return_value = {
            'oid': 'new-azure-object-789',
            'email': 'regular@example.com',  # Existing user's email
            'name': 'Regular User',
            'iss': 'https://login.microsoftonline.com/test-tenant-id/v2.0',
            'aud': 'test-client-id',
            'exp': int(time.time()) + 3600
        }
        
        initial_count = User.objects.count()
        
        response = self.client.get(reverse('azuread-callback') + '?code=test-code&state=test-state')
        
        # Should not create new user
        self.assertEqual(User.objects.count(), initial_count)
        
        # Should link Azure AD to existing user
        self.regular_user.refresh_from_db()
        self.assertEqual(self.regular_user.azure_ad_object_id, 'new-azure-object-789')
    
    @patch('core.backends.azuread.msal.ConfidentialClientApplication')
    @patch('core.backends.azuread.jwt.decode')
    def test_azuread_callback_inactive_user(self, mock_jwt_decode, mock_msal):
        """Test Azure AD callback rejects inactive user"""
        # Make Azure user inactive
        self.azure_user.active = False
        self.azure_user.save()
        
        # Set state in session
        session = self.client.session
        session['azure_ad_state'] = 'test-state'
        session.save()
        
        # Mock MSAL token acquisition
        mock_app = MagicMock()
        mock_app.acquire_token_by_authorization_code.return_value = {
            'id_token': 'mock-id-token',
            'access_token': 'mock-access-token'
        }
        mock_msal.return_value = mock_app
        
        # Mock JWT decode
        mock_jwt_decode.return_value = {
            'oid': 'azure-ad-object-123',
            'email': 'azureuser@example.com',
            'name': 'Azure User',
            'iss': 'https://login.microsoftonline.com/test-tenant-id/v2.0',
            'aud': 'test-client-id',
            'exp': int(time.time()) + 3600
        }
        
        response = self.client.get(reverse('azuread-callback') + '?code=test-code&state=test-state')
        
        # Should stay on login page
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')
        self.assertIn('error', response.context)
        self.assertIn('deaktiviert', response.context['error'])
        
        # User should not be authenticated
        self.assertFalse('_auth_user_id' in self.client.session)
    
    def test_azuread_logout_redirects_to_azure(self):
        """Test logout for Azure AD user redirects to Azure logout"""
        # Login the Azure user
        self.client.force_login(self.azure_user)
        
        response = self.client.get(reverse('logout'))
        
        # Should redirect to Azure AD logout
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith('https://login.microsoftonline.com'))
        self.assertIn('logout', response.url)
    
    def test_regular_logout_no_azure_redirect(self):
        """Test logout for regular user doesn't redirect to Azure"""
        # Login the regular user
        self.client.force_login(self.regular_user)
        
        response = self.client.get(reverse('logout'))
        
        # Should show logged out page (not redirect to Azure)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'logged_out.html')


class AzureADAuthBackendTestCase(TestCase):
    """Test cases for AzureADAuth backend class"""
    
    @override_settings(AZURE_AD_ENABLED=False)
    def test_init_raises_error_when_disabled(self):
        """Test AzureADAuth raises error when Azure AD is disabled"""
        with self.assertRaises(AzureADAuthError):
            AzureADAuth()
    
    @override_settings(
        AZURE_AD_ENABLED=True,
        AZURE_AD_TENANT_ID='',
        AZURE_AD_CLIENT_ID='test-client-id',
        AZURE_AD_CLIENT_SECRET='test-secret',
        AZURE_AD_REDIRECT_URI='http://localhost/callback/'
    )
    def test_init_raises_error_when_config_incomplete(self):
        """Test AzureADAuth raises error when configuration is incomplete"""
        with self.assertRaises(AzureADAuthError):
            AzureADAuth()
    
    @override_settings(
        AZURE_AD_ENABLED=True,
        AZURE_AD_TENANT_ID='test-tenant',
        AZURE_AD_CLIENT_ID='test-client-id',
        AZURE_AD_CLIENT_SECRET='test-secret',
        AZURE_AD_REDIRECT_URI='http://localhost/callback/',
        AZURE_AD_AUTHORITY='https://login.microsoftonline.com/test-tenant'
    )
    @patch('core.backends.azuread.msal.ConfidentialClientApplication')
    def test_get_auth_url(self, mock_msal):
        """Test get_auth_url returns authorization URL"""
        mock_app = MagicMock()
        mock_app.get_authorization_request_url.return_value = 'https://login.microsoftonline.com/authorize'
        mock_msal.return_value = mock_app
        
        azure_ad = AzureADAuth()
        auth_url = azure_ad.get_auth_url('test-state')
        
        self.assertTrue(auth_url.startswith('https://login.microsoftonline.com'))
        mock_app.get_authorization_request_url.assert_called_once()
    
    @override_settings(
        AZURE_AD_ENABLED=True,
        AZURE_AD_TENANT_ID='test-tenant',
        AZURE_AD_CLIENT_ID='test-client-id',
        AZURE_AD_CLIENT_SECRET='test-secret',
        AZURE_AD_REDIRECT_URI='http://localhost/callback/',
        AZURE_AD_AUTHORITY='https://login.microsoftonline.com/test-tenant'
    )
    def test_get_logout_url(self):
        """Test get_logout_url returns Azure logout URL"""
        azure_ad = AzureADAuth()
        logout_url = azure_ad.get_logout_url('http://localhost/login')
        
        self.assertTrue(logout_url.startswith('https://login.microsoftonline.com'))
        self.assertIn('logout', logout_url)
        self.assertIn('post_logout_redirect_uri', logout_url)
