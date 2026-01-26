"""
Tests for authentication functionality
"""

from django.test import TestCase, Client
from django.urls import reverse
from core.models import User


class AuthenticationTestCase(TestCase):
    """Test cases for login/logout functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        self.user.active = True
        self.user.save()
        
        # Create inactive user
        self.inactive_user = User.objects.create_user(
            username='inactiveuser',
            email='inactive@example.com',
            password='testpass123',
            name='Inactive User'
        )
        self.inactive_user.active = False
        self.inactive_user.save()
    
    def test_login_page_accessible(self):
        """Test that login page is accessible without authentication"""
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')
    
    def test_home_page_accessible_without_login(self):
        """Test that home page is accessible without authentication"""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'home.html')
    
    def test_dashboard_requires_login(self):
        """Test that dashboard redirects to login when not authenticated"""
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_projects_requires_login(self):
        """Test that projects page redirects to login when not authenticated"""
        response = self.client.get(reverse('projects'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_items_inbox_requires_login(self):
        """Test that items inbox redirects to login when not authenticated"""
        response = self.client.get(reverse('items-inbox'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_login_with_valid_credentials(self):
        """Test login with valid credentials"""
        response = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'testpass123',
        })
        # Should redirect after successful login
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))
        
        # User should be authenticated
        self.assertTrue('_auth_user_id' in self.client.session)
    
    def test_login_with_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'wrongpassword',
        })
        # Should stay on login page
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')
        self.assertIn('error', response.context)
        
        # User should not be authenticated
        self.assertFalse('_auth_user_id' in self.client.session)
    
    def test_login_with_inactive_user(self):
        """Test login with inactive user account"""
        response = self.client.post(reverse('login'), {
            'username': 'inactiveuser',
            'password': 'testpass123',
        })
        # Should stay on login page
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'login.html')
        self.assertIn('error', response.context)
        self.assertIn('deaktiviert', response.context['error'])
        
        # User should not be authenticated
        self.assertFalse('_auth_user_id' in self.client.session)
    
    def test_login_redirect_to_next(self):
        """Test login redirects to 'next' parameter"""
        next_url = reverse('projects')
        response = self.client.post(reverse('login') + f'?next={next_url}', {
            'username': 'testuser',
            'password': 'testpass123',
            'next': next_url,
        })
        # Should redirect to next URL
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, next_url)
    
    def test_logout(self):
        """Test logout functionality"""
        # First login
        self.client.login(username='testuser', password='testpass123')
        self.assertTrue('_auth_user_id' in self.client.session)
        
        # Then logout
        response = self.client.get(reverse('logout'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'logged_out.html')
        
        # User should not be authenticated anymore
        self.assertFalse('_auth_user_id' in self.client.session)
    
    def test_authenticated_user_can_access_dashboard(self):
        """Test that authenticated users can access dashboard"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'dashboard.html')
    
    def test_authenticated_user_can_access_projects(self):
        """Test that authenticated users can access projects"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('projects'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'projects.html')
    
    def test_already_authenticated_user_redirected_from_login(self):
        """Test that already authenticated users are redirected from login page"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('login'))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('dashboard'))
    
    def test_logout_after_accessing_protected_page(self):
        """Test that after logout, protected pages are inaccessible"""
        # Login and access dashboard
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)
        
        # Logout
        self.client.get(reverse('logout'))
        
        # Try to access dashboard again
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
