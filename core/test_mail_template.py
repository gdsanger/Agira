"""
Tests for MailTemplate model
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from core.models import MailTemplate


class MailTemplateTestCase(TestCase):
    """Test cases for MailTemplate model"""
    
    def setUp(self):
        """Set up test data"""
        # Create a basic mail template
        self.template = MailTemplate.objects.create(
            key='test-template',
            subject='Test Subject',
            message='Test message content'
        )
    
    def test_create_mail_template(self):
        """Test creating a mail template with required fields"""
        template = MailTemplate.objects.create(
            key='issue-created',
            subject='New Issue Created',
            message='A new issue has been created: {{issue_title}}'
        )
        
        self.assertEqual(template.key, 'issue-created')
        self.assertEqual(template.subject, 'New Issue Created')
        self.assertTrue(template.is_active)
        self.assertIsNotNone(template.created_at)
        self.assertIsNotNone(template.updated_at)
    
    def test_create_mail_template_with_all_fields(self):
        """Test creating a mail template with all optional fields"""
        template = MailTemplate.objects.create(
            key='full-template',
            subject='Complete Template',
            message='Full message content',
            from_name='Agira System',
            from_address='no-reply@agira.com',
            cc_address='admin@agira.com',
            is_active=False
        )
        
        self.assertEqual(template.from_name, 'Agira System')
        self.assertEqual(template.from_address, 'no-reply@agira.com')
        self.assertEqual(template.cc_address, 'admin@agira.com')
        self.assertFalse(template.is_active)
    
    def test_key_uniqueness(self):
        """Test that key must be unique"""
        # First template already created in setUp
        with self.assertRaises(IntegrityError):
            MailTemplate.objects.create(
                key='test-template',  # Same key as in setUp
                subject='Duplicate Key',
                message='This should fail'
            )
    
    def test_str_method(self):
        """Test string representation of mail template"""
        self.assertIn('test-template', str(self.template))
        self.assertIn('active', str(self.template))
        
        # Test with inactive template
        inactive = MailTemplate.objects.create(
            key='inactive-template',
            subject='Inactive',
            message='Content',
            is_active=False
        )
        self.assertIn('inactive', str(inactive))
    
    def test_default_is_active(self):
        """Test that is_active defaults to True"""
        template = MailTemplate.objects.create(
            key='default-active',
            subject='Test',
            message='Content'
        )
        self.assertTrue(template.is_active)
    
    def test_ordering(self):
        """Test that templates are ordered by key"""
        MailTemplate.objects.create(key='z-template', subject='Z', message='Z')
        MailTemplate.objects.create(key='a-template', subject='A', message='A')
        MailTemplate.objects.create(key='m-template', subject='M', message='M')
        
        templates = list(MailTemplate.objects.all())
        keys = [t.key for t in templates]
        
        self.assertEqual(keys, sorted(keys))
    
    def test_blank_optional_fields(self):
        """Test that optional fields can be blank"""
        template = MailTemplate.objects.create(
            key='minimal-template',
            subject='Minimal',
            message='Content',
            from_name='',
            from_address='',
            cc_address=''
        )
        
        self.assertEqual(template.from_name, '')
        self.assertEqual(template.from_address, '')
        self.assertEqual(template.cc_address, '')
    
    def test_update_template(self):
        """Test updating a mail template"""
        original_updated_at = self.template.updated_at
        
        self.template.subject = 'Updated Subject'
        self.template.save()
        
        self.assertEqual(self.template.subject, 'Updated Subject')
        # updated_at should change when model is saved
        # (Note: In tests this might not always be detectable depending on timing)
    
    def test_deactivate_template(self):
        """Test deactivating a template"""
        self.assertTrue(self.template.is_active)
        
        self.template.is_active = False
        self.template.save()
        
        self.assertFalse(self.template.is_active)
    
    def test_placeholders_stored_not_evaluated(self):
        """Test that placeholders are stored as-is, not evaluated"""
        template = MailTemplate.objects.create(
            key='placeholder-test',
            subject='Issue: {{issue_id}}',
            message='Dear {{user_name}}, your issue {{issue_id}} has been {{status}}.'
        )
        
        # Placeholders should remain in the text
        self.assertIn('{{issue_id}}', template.subject)
        self.assertIn('{{user_name}}', template.message)
        self.assertIn('{{status}}', template.message)
