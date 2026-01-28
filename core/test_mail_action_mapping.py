"""
Tests for MailActionMapping model
"""

from django.test import TestCase
from django.db import IntegrityError
from core.models import (
    MailActionMapping,
    MailTemplate,
    ItemType,
    ItemStatus,
)


class MailActionMappingTestCase(TestCase):
    """Test cases for MailActionMapping model"""
    
    def setUp(self):
        """Set up test data"""
        # Create a mail template
        self.template = MailTemplate.objects.create(
            key='test-template',
            subject='Test Subject',
            message='Test message content'
        )
        
        # Create an item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug'
        )
        
        # Create a basic mapping
        self.mapping = MailActionMapping.objects.create(
            item_status=ItemStatus.WORKING,
            item_type=self.item_type,
            mail_template=self.template
        )
    
    def test_create_mail_action_mapping(self):
        """Test creating a mail action mapping with required fields"""
        template = MailTemplate.objects.create(
            key='issue-created',
            subject='Issue Created',
            message='New issue created'
        )
        item_type = ItemType.objects.create(
            key='feature',
            name='Feature'
        )
        
        mapping = MailActionMapping.objects.create(
            item_status=ItemStatus.INBOX,
            item_type=item_type,
            mail_template=template
        )
        
        self.assertEqual(mapping.item_status, ItemStatus.INBOX)
        self.assertEqual(mapping.item_type, item_type)
        self.assertEqual(mapping.mail_template, template)
        self.assertTrue(mapping.is_active)
        self.assertIsNotNone(mapping.created_at)
        self.assertIsNotNone(mapping.updated_at)
    
    def test_create_inactive_mapping(self):
        """Test creating an inactive mapping"""
        template = MailTemplate.objects.create(
            key='inactive-test',
            subject='Test',
            message='Test'
        )
        item_type = ItemType.objects.create(
            key='task',
            name='Task'
        )
        
        mapping = MailActionMapping.objects.create(
            item_status=ItemStatus.CLOSED,
            item_type=item_type,
            mail_template=template,
            is_active=False
        )
        
        self.assertFalse(mapping.is_active)
    
    def test_default_is_active(self):
        """Test that is_active defaults to True"""
        template = MailTemplate.objects.create(
            key='default-test',
            subject='Test',
            message='Test'
        )
        item_type = ItemType.objects.create(
            key='change',
            name='Change'
        )
        
        mapping = MailActionMapping.objects.create(
            item_status=ItemStatus.TESTING,
            item_type=item_type,
            mail_template=template
        )
        
        self.assertTrue(mapping.is_active)
    
    def test_foreign_key_to_mail_template(self):
        """Test ForeignKey relationship to MailTemplate"""
        self.assertEqual(self.mapping.mail_template, self.template)
        self.assertIn(self.mapping, self.template.mail_action_mappings.all())
    
    def test_foreign_key_to_item_type(self):
        """Test ForeignKey relationship to ItemType"""
        self.assertEqual(self.mapping.item_type, self.item_type)
        self.assertIn(self.mapping, self.item_type.mail_action_mappings.all())
    
    def test_item_status_choices(self):
        """Test that various item statuses can be used"""
        template = MailTemplate.objects.create(
            key='status-test',
            subject='Test',
            message='Test'
        )
        item_type = ItemType.objects.create(
            key='test-type',
            name='Test Type'
        )
        
        # Test various statuses
        statuses = [
            ItemStatus.INBOX,
            ItemStatus.BACKLOG,
            ItemStatus.WORKING,
            ItemStatus.TESTING,
            ItemStatus.READY_FOR_RELEASE,
            ItemStatus.PLANING,
            ItemStatus.SPECIFICATION,
            ItemStatus.CLOSED,
        ]
        
        for status in statuses:
            mapping = MailActionMapping.objects.create(
                item_status=status,
                item_type=item_type,
                mail_template=template
            )
            self.assertEqual(mapping.item_status, status)
    
    def test_multiple_mappings_allowed(self):
        """Test that multiple mappings can exist with different combinations"""
        template1 = MailTemplate.objects.create(
            key='template-1',
            subject='Template 1',
            message='Message 1'
        )
        template2 = MailTemplate.objects.create(
            key='template-2',
            subject='Template 2',
            message='Message 2'
        )
        type1 = ItemType.objects.create(key='type1', name='Type 1')
        type2 = ItemType.objects.create(key='type2', name='Type 2')
        
        # Create multiple mappings
        mapping1 = MailActionMapping.objects.create(
            item_status=ItemStatus.WORKING,
            item_type=type1,
            mail_template=template1
        )
        mapping2 = MailActionMapping.objects.create(
            item_status=ItemStatus.TESTING,
            item_type=type1,
            mail_template=template2
        )
        mapping3 = MailActionMapping.objects.create(
            item_status=ItemStatus.WORKING,
            item_type=type2,
            mail_template=template2
        )
        
        # All should be retrievable
        self.assertEqual(MailActionMapping.objects.count(), 4)  # Including setUp mapping
    
    def test_toggle_is_active(self):
        """Test toggling the is_active flag"""
        self.assertTrue(self.mapping.is_active)
        
        self.mapping.is_active = False
        self.mapping.save()
        
        self.assertFalse(self.mapping.is_active)
        
        self.mapping.is_active = True
        self.mapping.save()
        
        self.assertTrue(self.mapping.is_active)
    
    def test_cascade_delete_item_type(self):
        """Test that deleting ItemType cascades to mappings"""
        mapping_id = self.mapping.id
        
        # Delete the item type
        self.item_type.delete()
        
        # Mapping should also be deleted (CASCADE)
        with self.assertRaises(MailActionMapping.DoesNotExist):
            MailActionMapping.objects.get(id=mapping_id)
    
    def test_protect_delete_mail_template(self):
        """Test that deleting MailTemplate is protected when referenced"""
        # Try to delete the template that is referenced by mapping
        with self.assertRaises(Exception):  # Will raise ProtectedError
            self.template.delete()
        
        # Mapping should still exist
        self.assertTrue(MailActionMapping.objects.filter(id=self.mapping.id).exists())
    
    def test_str_method(self):
        """Test string representation of mapping"""
        str_repr = str(self.mapping)
        
        # Should contain status display name
        self.assertIn('Working', str_repr)
        # Should contain type name
        self.assertIn('Bug', str_repr)
        # Should contain template key
        self.assertIn('test-template', str_repr)
        # Should indicate active status
        self.assertIn('active', str_repr)
    
    def test_str_method_inactive(self):
        """Test string representation for inactive mapping"""
        self.mapping.is_active = False
        self.mapping.save()
        
        str_repr = str(self.mapping)
        self.assertIn('inactive', str_repr)
    
    def test_ordering(self):
        """Test that mappings are ordered by status and type"""
        template = MailTemplate.objects.create(
            key='order-test',
            subject='Test',
            message='Test'
        )
        type_a = ItemType.objects.create(key='a-type', name='A Type')
        type_z = ItemType.objects.create(key='z-type', name='Z Type')
        
        # Create mappings in random order
        MailActionMapping.objects.create(
            item_status=ItemStatus.TESTING,
            item_type=type_z,
            mail_template=template
        )
        MailActionMapping.objects.create(
            item_status=ItemStatus.INBOX,
            item_type=type_a,
            mail_template=template
        )
        MailActionMapping.objects.create(
            item_status=ItemStatus.TESTING,
            item_type=type_a,
            mail_template=template
        )
        
        # Get all mappings
        mappings = list(MailActionMapping.objects.all())
        
        # Should be ordered by item_status first, then item_type
        # We can verify by checking consecutive pairs
        for i in range(len(mappings) - 1):
            current = mappings[i]
            next_item = mappings[i + 1]
            # Either status is less, or status is equal and type name is less/equal
            self.assertTrue(
                current.item_status < next_item.item_status or
                (current.item_status == next_item.item_status and
                 current.item_type.name <= next_item.item_type.name)
            )
    
    def test_update_mapping(self):
        """Test updating a mapping"""
        new_template = MailTemplate.objects.create(
            key='new-template',
            subject='New Template',
            message='New message'
        )
        
        self.mapping.mail_template = new_template
        self.mapping.item_status = ItemStatus.CLOSED
        self.mapping.save()
        
        refreshed = MailActionMapping.objects.get(id=self.mapping.id)
        self.assertEqual(refreshed.mail_template, new_template)
        self.assertEqual(refreshed.item_status, ItemStatus.CLOSED)
    
    def test_filter_by_status(self):
        """Test filtering mappings by status"""
        template = MailTemplate.objects.create(
            key='filter-test',
            subject='Test',
            message='Test'
        )
        item_type = ItemType.objects.create(key='filter-type', name='Filter Type')
        
        # Create mappings with different statuses
        MailActionMapping.objects.create(
            item_status=ItemStatus.TESTING,
            item_type=item_type,
            mail_template=template
        )
        MailActionMapping.objects.create(
            item_status=ItemStatus.TESTING,
            item_type=item_type,
            mail_template=template
        )
        
        # Filter by status
        testing_mappings = MailActionMapping.objects.filter(item_status=ItemStatus.TESTING)
        self.assertEqual(testing_mappings.count(), 2)
    
    def test_filter_by_active_status(self):
        """Test filtering mappings by is_active"""
        template = MailTemplate.objects.create(
            key='active-filter-test',
            subject='Test',
            message='Test'
        )
        item_type = ItemType.objects.create(key='active-type', name='Active Type')
        
        # Create active and inactive mappings
        MailActionMapping.objects.create(
            item_status=ItemStatus.INBOX,
            item_type=item_type,
            mail_template=template,
            is_active=True
        )
        MailActionMapping.objects.create(
            item_status=ItemStatus.BACKLOG,
            item_type=item_type,
            mail_template=template,
            is_active=False
        )
        
        # Filter by active status
        active_mappings = MailActionMapping.objects.filter(is_active=True)
        inactive_mappings = MailActionMapping.objects.filter(is_active=False)
        
        # Should have at least 1 active (plus the setUp one)
        self.assertGreaterEqual(active_mappings.count(), 2)
        self.assertEqual(inactive_mappings.count(), 1)
    
    def test_get_status_display(self):
        """Test that get_item_status_display returns the friendly name"""
        display = self.mapping.get_item_status_display()
        # Should contain the emoji and text
        self.assertIn('Working', display)
