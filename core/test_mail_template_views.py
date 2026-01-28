"""
Tests for MailTemplate views
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import MailTemplate
import json

User = get_user_model()


class MailTemplateViewsTestCase(TestCase):
    """Test cases for MailTemplate views"""
    
    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        # Create test templates
        self.template1 = MailTemplate.objects.create(
            key='welcome-email',
            subject='Welcome to Agira',
            message='<p>Welcome {{username}}!</p>',
            is_active=True
        )
        
        self.template2 = MailTemplate.objects.create(
            key='notification-email',
            subject='New Notification',
            message='<p>You have a new notification.</p>',
            from_address='notify@example.com',
            is_active=False
        )
        
        # Set up client
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def test_mail_templates_list_view(self):
        """Test that mail templates list view works"""
        response = self.client.get(reverse('mail-templates'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'welcome-email')
        self.assertContains(response, 'notification-email')
        self.assertContains(response, 'Mail Templates')
    
    def test_mail_templates_search(self):
        """Test search functionality"""
        response = self.client.get(reverse('mail-templates'), {'q': 'welcome'})
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'welcome-email')
        self.assertNotContains(response, 'notification-email')
    
    def test_mail_templates_filter_active(self):
        """Test filtering by active status"""
        response = self.client.get(reverse('mail-templates'), {'is_active': 'true'})
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'welcome-email')
        self.assertNotContains(response, 'notification-email')
    
    def test_mail_template_detail_view(self):
        """Test mail template detail view"""
        response = self.client.get(reverse('mail-template-detail', args=[self.template1.id]))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'welcome-email')
        self.assertContains(response, 'Welcome to Agira')
    
    def test_mail_template_create_view(self):
        """Test create form view"""
        response = self.client.get(reverse('mail-template-create'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create New Mail Template')
    
    def test_mail_template_edit_view(self):
        """Test edit form view"""
        response = self.client.get(reverse('mail-template-edit', args=[self.template1.id]))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'welcome-email')
        self.assertContains(response, 'Edit Mail Template')
    
    def test_mail_template_create_new(self):
        """Test creating a new template via POST"""
        data = {
            'key': 'new-template',
            'subject': 'New Template Subject',
            'message': '<p>New template message</p>',
            'is_active': 'on',
            'action': 'save'
        }
        
        response = self.client.post(
            reverse('mail-template-update', args=[0]),
            data=data
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['success'])
        
        # Verify template was created
        template = MailTemplate.objects.get(key='new-template')
        self.assertEqual(template.subject, 'New Template Subject')
        self.assertTrue(template.is_active)
    
    def test_mail_template_create_duplicate_key(self):
        """Test that duplicate keys are rejected"""
        data = {
            'key': 'welcome-email',  # Already exists
            'subject': 'Duplicate',
            'message': '<p>Duplicate</p>',
            'is_active': 'on'
        }
        
        response = self.client.post(
            reverse('mail-template-update', args=[0]),
            data=data
        )
        
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertFalse(response_data['success'])
        self.assertIn('already exists', response_data['error'])
    
    def test_mail_template_create_invalid_key(self):
        """Test that invalid key formats are rejected"""
        data = {
            'key': 'Invalid Key!',  # Invalid characters
            'subject': 'Test',
            'message': '<p>Test</p>',
            'is_active': 'on'
        }
        
        response = self.client.post(
            reverse('mail-template-update', args=[0]),
            data=data
        )
        
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertFalse(response_data['success'])
        self.assertIn('lowercase', response_data['error'])
    
    def test_mail_template_create_with_hyphens(self):
        """Test that keys with hyphens are accepted"""
        data = {
            'key': 'test-template-with-hyphens',
            'subject': 'Test Template',
            'message': '<p>Test message</p>',
            'is_active': 'on',
            'action': 'save'
        }
        
        response = self.client.post(
            reverse('mail-template-update', args=[0]),
            data=data
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['success'])
        
        # Verify template was created
        template = MailTemplate.objects.get(key='test-template-with-hyphens')
        self.assertEqual(template.subject, 'Test Template')
    
    def test_mail_template_update_existing(self):
        """Test updating an existing template"""
        data = {
            'key': 'welcome-email',  # Key is readonly, but sent for validation
            'subject': 'Updated Welcome',
            'message': '<p>Updated message</p>',
            'from_name': 'Agira System',
            'from_address': 'system@agira.com',
            'is_active': 'on',
            'action': 'save'
        }
        
        response = self.client.post(
            reverse('mail-template-update', args=[self.template1.id]),
            data=data
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['success'])
        
        # Verify update
        self.template1.refresh_from_db()
        self.assertEqual(self.template1.subject, 'Updated Welcome')
        self.assertEqual(self.template1.from_name, 'Agira System')
    
    def test_mail_template_save_and_close(self):
        """Test save and close action"""
        from django.urls import reverse
        
        data = {
            'key': 'welcome-email',
            'subject': 'Updated',
            'message': '<p>Updated</p>',
            'is_active': 'on',
            'action': 'save_close'
        }
        
        response = self.client.post(
            reverse('mail-template-update', args=[self.template1.id]),
            data=data
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['success'])
        # Check that redirect uses reverse URL
        self.assertEqual(response_data['redirect'], reverse('mail-templates'))
    
    def test_mail_template_delete(self):
        """Test deleting a template"""
        response = self.client.post(
            reverse('mail-template-delete', args=[self.template1.id])
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = json.loads(response.content)
        self.assertTrue(response_data['success'])
        
        # Verify deletion
        self.assertFalse(MailTemplate.objects.filter(id=self.template1.id).exists())
    
    def test_mail_template_delete_nonexistent(self):
        """Test deleting a non-existent template returns 404"""
        response = self.client.post(
            reverse('mail-template-delete', args=[9999])
        )
        
        self.assertEqual(response.status_code, 404)
    
    def test_mail_template_required_fields(self):
        """Test that required fields are validated"""
        # Missing subject
        data = {
            'key': 'test-key',
            'message': '<p>Test</p>',
            'is_active': 'on'
        }
        
        response = self.client.post(
            reverse('mail-template-update', args=[0]),
            data=data
        )
        
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertFalse(response_data['success'])
        self.assertIn('Subject', response_data['error'])
    
    def test_mail_template_ai_generate_endpoint_exists(self):
        """Test that AI generation endpoint exists"""
        # We can't fully test AI generation without mocking the agent service
        # but we can verify the endpoint exists and requires proper input
        data = {}  # Empty data
        
        response = self.client.post(
            reverse('mail-template-generate-ai', args=[self.template1.id]),
            data=json.dumps(data),
            content_type='application/json'
        )
        
        # Should fail due to missing context
        self.assertEqual(response.status_code, 400)
        response_data = json.loads(response.content)
        self.assertFalse(response_data['success'])
        self.assertIn('Context', response_data['error'])
    
    def test_login_required(self):
        """Test that login is required for all views"""
        # Logout
        self.client.logout()
        
        # Test list view redirects to login
        response = self.client.get(reverse('mail-templates'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
        
        # Test create view redirects to login
        response = self.client.get(reverse('mail-template-create'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_mail_template_detail_html_sanitization(self):
        """Test that HTML in mail templates is sanitized to prevent XSS"""
        from html.parser import HTMLParser
        
        # Create a template with potentially malicious HTML
        malicious_template = MailTemplate.objects.create(
            key='malicious-test',
            subject='Test XSS Prevention',
            message='<h1>Safe Heading</h1><p>Safe paragraph</p><script>alert("XSS")</script><p onclick="alert(\'click\')">Click me</p>',
            is_active=True
        )
        
        response = self.client.get(reverse('mail-template-detail', args=[malicious_template.id]))
        
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # Verify safe HTML is preserved in the preview
        self.assertIn('<h1>Safe Heading</h1>', content)
        self.assertIn('<p>Safe paragraph</p>', content)
        
        # Find the HTML preview div using a more robust method
        # Look for the preview div and verify dangerous content is not there
        preview_marker = 'class="html-preview'
        preview_start = content.find(preview_marker)
        self.assertNotEqual(preview_start, -1, "HTML preview section not found")
        
        # Find the end of the preview div by counting nested divs
        # First, find the start of the div tag
        div_start = content.rfind('<div', 0, preview_start)
        preview_content_start = content.find('>', div_start) + 1
        depth = 1
        i = preview_content_start
        while i < len(content) and depth > 0:
            if content[i:i+5] == '<div ':
                depth += 1
            elif content[i:i+6] == '</div>':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        
        preview_section = content[div_start:i]
        
        # Verify script tags and event handlers are not in the preview section
        self.assertNotIn('<script>', preview_section)
        self.assertNotIn('</script>', preview_section)
        self.assertNotIn('onclick=', preview_section)
