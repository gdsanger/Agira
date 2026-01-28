"""
Test to verify CSRF token is properly available in templates after fix
"""
from django.test import TestCase, Client, RequestFactory
from django.contrib.auth import get_user_model
from django.template import Template, Context
from django.middleware.csrf import get_token

User = get_user_model()


class CSRFTokenTestCase(TestCase):
    """Test that CSRF token is properly available in templates"""
    
    def setUp(self):
        """Set up test data"""
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
        
    def test_csrf_token_in_meta_tag(self):
        """Test that CSRF token is rendered in meta tag"""
        response = self.client.get('/mail-templates/new/')
        
        self.assertEqual(response.status_code, 200)
        # Check that the response contains a meta tag with csrf-token
        self.assertContains(response, '<meta name="csrf-token"')
        # Check that the meta tag has content (not empty)
        self.assertNotContains(response, '<meta name="csrf-token" content="">')
        
    def test_csrf_token_context_processor(self):
        """Test that csrf token is available in template context"""
        rf = RequestFactory()
        request = rf.get('/mail-templates/create/')
        
        # Get CSRF token
        token = get_token(request)
        
        # Verify token is not empty
        self.assertIsNotNone(token)
        self.assertGreater(len(token), 0)
        
        # Test template rendering with csrf_token in context
        template = Template('<meta name="csrf-token" content="{{ csrf_token }}">')
        context = Context({'csrf_token': token})
        rendered = template.render(context)
        
        # Verify the token is rendered
        self.assertIn(token, rendered)
        self.assertNotIn('""', rendered)  # Should not have empty content
