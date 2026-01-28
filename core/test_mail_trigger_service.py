"""
Tests for mail trigger service.
"""

from django.test import TestCase
from core.models import (
    Item,
    ItemType,
    ItemStatus,
    Project,
    User,
    MailTemplate,
    MailActionMapping,
    ProjectStatus,
)
from core.services.mail.mail_trigger_service import (
    check_mail_trigger,
    prepare_mail_preview,
)


class MailTriggerServiceTestCase(TestCase):
    """Test cases for mail trigger service"""
    
    def setUp(self):
        """Set up test data"""
        # Create a project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project description',
            status=ProjectStatus.WORKING
        )
        
        # Create item types
        self.bug_type = ItemType.objects.create(
            key='bug',
            name='Bug'
        )
        self.feature_type = ItemType.objects.create(
            key='feature',
            name='Feature'
        )
        
        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='pass123'
        )
        self.user.name = 'Test User'
        self.user.save()
        
        # Create mail template
        self.template = MailTemplate.objects.create(
            key='status-changed',
            subject='Status changed: {{ issue.title }}',
            message='Your issue {{ issue.title }} is now {{ issue.status }}',
            from_name='Support Team',
            from_address='support@example.com',
            cc_address='manager@example.com'
        )
        
        # Create active mapping for Bug + Working
        self.mapping = MailActionMapping.objects.create(
            is_active=True,
            item_status=ItemStatus.WORKING,
            item_type=self.bug_type,
            mail_template=self.template
        )
        
        # Create item with matching status and type
        self.item = Item.objects.create(
            project=self.project,
            title='Test Bug Item',
            type=self.bug_type,
            status=ItemStatus.WORKING,
            requester=self.user
        )
    
    def test_check_mail_trigger_finds_active_mapping(self):
        """Test that check_mail_trigger finds active mapping"""
        mapping = check_mail_trigger(self.item)
        
        self.assertIsNotNone(mapping)
        self.assertEqual(mapping.id, self.mapping.id)
        self.assertEqual(mapping.mail_template, self.template)
    
    def test_check_mail_trigger_returns_none_for_no_mapping(self):
        """Test that None is returned when no mapping exists"""
        # Create item with different status
        item = Item.objects.create(
            project=self.project,
            title='Different Status Item',
            type=self.bug_type,
            status=ItemStatus.TESTING  # No mapping for this status
        )
        
        mapping = check_mail_trigger(item)
        
        self.assertIsNone(mapping)
    
    def test_check_mail_trigger_returns_none_for_different_type(self):
        """Test that None is returned for different item type"""
        # Create item with different type
        item = Item.objects.create(
            project=self.project,
            title='Feature Item',
            type=self.feature_type,  # Different type
            status=ItemStatus.WORKING
        )
        
        mapping = check_mail_trigger(item)
        
        self.assertIsNone(mapping)
    
    def test_check_mail_trigger_ignores_inactive_mappings(self):
        """Test that inactive mappings are not returned"""
        # Make the mapping inactive
        self.mapping.is_active = False
        self.mapping.save()
        
        mapping = check_mail_trigger(self.item)
        
        self.assertIsNone(mapping)
    
    def test_check_mail_trigger_handles_multiple_mappings(self):
        """Test behavior when multiple mappings exist (edge case)"""
        # Create another active mapping with same status and type
        # This shouldn't happen with proper constraints, but test the handling
        duplicate_template = MailTemplate.objects.create(
            key='duplicate-template',
            subject='Duplicate',
            message='Duplicate message'
        )
        MailActionMapping.objects.create(
            is_active=True,
            item_status=ItemStatus.WORKING,
            item_type=self.bug_type,
            mail_template=duplicate_template
        )
        
        # Should return one of them (first one)
        mapping = check_mail_trigger(self.item)
        
        self.assertIsNotNone(mapping)
    
    def test_prepare_mail_preview_processes_template(self):
        """Test that prepare_mail_preview processes the template correctly"""
        preview = prepare_mail_preview(self.item, self.mapping)
        
        # Check that variables are replaced
        self.assertIn('Test Bug Item', preview['subject'])
        self.assertIn('Test Bug Item', preview['message'])
        self.assertIn('Working', preview['message'])
    
    def test_prepare_mail_preview_includes_metadata(self):
        """Test that prepare_mail_preview includes template metadata"""
        preview = prepare_mail_preview(self.item, self.mapping)
        
        self.assertEqual(preview['template_key'], 'status-changed')
        self.assertEqual(preview['from_name'], 'Support Team')
        self.assertEqual(preview['from_address'], 'support@example.com')
        self.assertEqual(preview['cc_address'], 'manager@example.com')
    
    def test_prepare_mail_preview_handles_empty_metadata(self):
        """Test that empty template metadata is handled"""
        # Create template without optional fields
        minimal_template = MailTemplate.objects.create(
            key='minimal-template',
            subject='Test',
            message='Test message'
        )
        minimal_mapping = MailActionMapping.objects.create(
            is_active=True,
            item_status=ItemStatus.TESTING,
            item_type=self.bug_type,
            mail_template=minimal_template
        )
        
        item = Item.objects.create(
            project=self.project,
            title='Minimal Item',
            type=self.bug_type,
            status=ItemStatus.TESTING
        )
        
        preview = prepare_mail_preview(item, minimal_mapping)
        
        self.assertEqual(preview['from_name'], '')
        self.assertEqual(preview['from_address'], '')
        self.assertEqual(preview['cc_address'], '')
    
    def test_integration_check_and_prepare(self):
        """Test integration: check trigger and prepare preview"""
        # Check if mail should be triggered
        mapping = check_mail_trigger(self.item)
        
        self.assertIsNotNone(mapping)
        
        # Prepare preview
        preview = prepare_mail_preview(self.item, mapping)
        
        self.assertIn('subject', preview)
        self.assertIn('message', preview)
        self.assertIn('template_key', preview)
