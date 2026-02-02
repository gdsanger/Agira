"""
Tests for embed frame middleware.

Verifies that embed endpoints can be embedded in iframes from allowed origins
while other endpoints remain protected.
"""
from django.test import TestCase, Client
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
        
        # Create embed access with allowed origins
        self.embed_access = OrganisationEmbedProject.objects.create(
            organisation=self.org,
            project=self.project,
            is_enabled=True,
            allowed_origins='https://app.example.com,https://portal.example.org'
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

    def test_embed_endpoint_csp_includes_allowed_origins(self):
        """Test that CSP includes the configured allowed origins from database"""
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        csp = response.get('Content-Security-Policy', '')
        # Should include both configured origins
        self.assertIn('https://app.example.com', csp)
        self.assertIn('https://portal.example.org', csp)

    def test_embed_endpoint_without_token_denies_framing(self):
        """Test that embed endpoints without token deny iframe embedding"""
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/'
        )
        
        # Should still return 404 (from view validation)
        # But if it returns a response, CSP should deny framing
        if response.status_code == 200:
            csp = response.get('Content-Security-Policy', '')
            self.assertIn("frame-ancestors 'none'", csp)

    def test_embed_endpoint_with_invalid_token_denies_framing(self):
        """Test that embed endpoints with invalid token deny iframe embedding"""
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/',
            {'token': 'invalid-token-12345'}
        )
        
        # Should return 404 from view validation
        # But check CSP is set to deny
        if response.status_code == 200:
            csp = response.get('Content-Security-Policy', '')
            self.assertIn("frame-ancestors 'none'", csp)

    def test_embed_endpoint_with_disabled_access_denies_framing(self):
        """Test that disabled embed access denies iframe embedding"""
        # Disable the embed access
        self.embed_access.is_enabled = False
        self.embed_access.save()
        
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/',
            {'token': self.valid_token}
        )
        
        # Should return 403 from view validation
        # CSP should deny framing
        csp = response.get('Content-Security-Policy', '')
        self.assertIn("frame-ancestors 'none'", csp)

    def test_embed_endpoint_with_empty_origins_denies_framing(self):
        """Test that embed access with no allowed origins denies iframe embedding"""
        # Clear allowed origins
        self.embed_access.allowed_origins = ''
        self.embed_access.save()
        
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        csp = response.get('Content-Security-Policy', '')
        # Should deny framing when no origins configured
        self.assertIn("frame-ancestors 'none'", csp)

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
        # Should include allowed origins
        self.assertIn('https://app.example.com', csp)

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
        from django.test import RequestFactory
        from core.middleware import EmbedFrameMiddleware
        from django.http import HttpResponse
        
        # Create a request for an embed endpoint with token
        factory = RequestFactory()
        request = factory.get(f'/embed/projects/1/issues/?token={self.valid_token}')
        
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

    def test_middleware_with_multiple_origins(self):
        """Test that multiple origins are included in CSP"""
        # Create embed access with multiple origins
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org,
            project=Project.objects.create(name='Multi Origin Project', description='Test'),
            is_enabled=True,
            allowed_origins='https://app1.example.com,https://app2.example.com,https://app3.example.com'
        )
        
        response = self.client.get(
            f'/embed/projects/{embed.project.id}/issues/',
            {'token': embed.embed_token}
        )
        
        self.assertEqual(response.status_code, 200)
        csp = response.get('Content-Security-Policy', '')
        # All three origins should be in CSP
        self.assertIn('https://app1.example.com', csp)
        self.assertIn('https://app2.example.com', csp)
        self.assertIn('https://app3.example.com', csp)

    def test_middleware_with_whitespace_in_origins(self):
        """Test that whitespace in origins is handled correctly"""
        # Create embed access with whitespace
        embed = OrganisationEmbedProject.objects.create(
            organisation=self.org,
            project=Project.objects.create(name='Whitespace Project', description='Test'),
            is_enabled=True,
            allowed_origins='  https://app.example.com  ,  https://portal.example.com  '
        )
        
        response = self.client.get(
            f'/embed/projects/{embed.project.id}/issues/',
            {'token': embed.embed_token}
        )
        
        self.assertEqual(response.status_code, 200)
        csp = response.get('Content-Security-Policy', '')
        # Origins should be trimmed
        self.assertIn('https://app.example.com', csp)
        self.assertIn('https://portal.example.com', csp)
        # Should not have extra spaces
        self.assertNotIn('  https://app.example.com  ', csp)
