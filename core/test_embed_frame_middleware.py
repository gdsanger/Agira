"""
Tests for embed frame middleware.

Verifies that embed endpoints can be embedded in iframes from allowed origins
while other endpoints remain protected.
"""
from django.test import TestCase, Client, override_settings
from core.models import (
    Organisation, Project, OrganisationEmbedProject, ItemType
)


class EmbedFrameMiddlewareTestCase(TestCase):
    """Test embed frame middleware functionality"""

    def setUp(self):
        """Set up test data"""
        # Create organisation and project
        self.org = Organisation.objects.create(name='Test Org')
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project'
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        
        # Create embed access
        self.embed_access = OrganisationEmbedProject.objects.create(
            organisation=self.org,
            project=self.project,
            is_enabled=True
        )
        self.valid_token = self.embed_access.embed_token
        
        # Create test client
        self.client = Client()

    def test_embed_endpoint_allows_framing(self):
        """Test that embed endpoints don't have X-Frame-Options: DENY"""
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # X-Frame-Options should not be set or should not be DENY
        x_frame_options = response.get('X-Frame-Options', '')
        self.assertNotEqual(x_frame_options, 'DENY')

    def test_embed_endpoint_sets_csp_frame_ancestors(self):
        """Test that embed endpoints set CSP frame-ancestors"""
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Should have Content-Security-Policy with frame-ancestors
        csp = response.get('Content-Security-Policy', '')
        self.assertIn('frame-ancestors', csp)

    @override_settings(EMBED_ALLOWED_ORIGINS='https://app.ebner-vermietung.de')
    def test_embed_endpoint_csp_includes_allowed_origin(self):
        """Test that CSP includes the configured allowed origin"""
        # Mock os.getenv to return our test value
        from unittest.mock import patch
        with patch('core.middleware.os.getenv') as mock_getenv:
            mock_getenv.return_value = 'https://app.ebner-vermietung.de'
            
            # Reload middleware to pick up the mocked value
            from importlib import reload
            from core import middleware
            reload(middleware)
            
            response = self.client.get(
                f'/embed/projects/{self.project.id}/issues/',
                {'token': self.valid_token}
            )
            
            self.assertEqual(response.status_code, 200)
            csp = response.get('Content-Security-Policy', '')
            self.assertIn('https://app.ebner-vermietung.de', csp)

    def test_non_embed_endpoint_has_frame_protection(self):
        """Test that non-embed endpoints still have X-Frame-Options"""
        # Try to access a non-embed endpoint (e.g., login page)
        response = self.client.get('/login/')
        
        # Should have X-Frame-Options set
        x_frame_options = response.get('X-Frame-Options', '')
        # Django's default is DENY
        self.assertIn(x_frame_options, ['DENY', 'SAMEORIGIN'])

    def test_embed_issue_detail_allows_framing(self):
        """Test that embed issue detail endpoint allows framing"""
        # Create an item first
        from core.models import Item, ItemStatus
        item = Item.objects.create(
            project=self.project,
            organisation=self.org,
            title='Test Issue',
            description='Test',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        response = self.client.get(
            f'/embed/issues/{item.id}/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Should not have X-Frame-Options: DENY
        x_frame_options = response.get('X-Frame-Options', '')
        self.assertNotEqual(x_frame_options, 'DENY')
        # Should have CSP frame-ancestors
        csp = response.get('Content-Security-Policy', '')
        self.assertIn('frame-ancestors', csp)

    def test_embed_create_form_allows_framing(self):
        """Test that embed create form endpoint allows framing"""
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/create/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Should not have X-Frame-Options: DENY
        x_frame_options = response.get('X-Frame-Options', '')
        self.assertNotEqual(x_frame_options, 'DENY')
        # Should have CSP frame-ancestors
        csp = response.get('Content-Security-Policy', '')
        self.assertIn('frame-ancestors', csp)

    def test_csp_headers_are_preserved(self):
        """Test that existing CSP headers are preserved and frame-ancestors is appended"""
        from unittest.mock import patch
        from django.test import RequestFactory
        from core.middleware import EmbedFrameMiddleware
        from django.http import HttpResponse
        
        # Create a request for an embed endpoint
        factory = RequestFactory()
        request = factory.get('/embed/projects/1/issues/')
        
        # Create a response with an existing CSP header
        def get_response(req):
            response = HttpResponse()
            response['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'"
            response['X-Frame-Options'] = 'DENY'
            return response
        
        # Process through middleware
        middleware = EmbedFrameMiddleware(get_response)
        response = middleware.process_response(request, get_response(request))
        
        # Check that frame-ancestors was added
        csp = response.get('Content-Security-Policy', '')
        self.assertIn('frame-ancestors', csp)
        # Check that existing directives are preserved
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src 'self' 'unsafe-inline'", csp)
        # Check that X-Frame-Options was removed
        self.assertNotIn('X-Frame-Options', response)
