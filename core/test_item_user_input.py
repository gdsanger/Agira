"""
Tests for Item model user_input field.
"""

from django.test import TestCase
from core.models import (
    Organisation,
    Project,
    ItemType,
    Item,
    ItemStatus,
)


class ItemUserInputFieldTest(TestCase):
    """Tests for Item model user_input field."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create test project
        self.project = Project.objects.create(
            name="TestProject",
            description="Test project",
        )
        
        # Create item type
        self.task_type = ItemType.objects.create(
            key="task",
            name="Task",
            is_active=True,
        )
    
    def test_user_input_field_exists(self):
        """Test that user_input field exists and can be set."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Test description',
            user_input='Original email content',
            type=self.task_type,
            status=ItemStatus.INBOX,
        )
        
        # Verify field was saved
        self.assertEqual(item.user_input, 'Original email content')
        
        # Reload from database
        item_from_db = Item.objects.get(id=item.id)
        self.assertEqual(item_from_db.user_input, 'Original email content')
    
    def test_user_input_field_blank(self):
        """Test that user_input field can be blank."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Test description',
            user_input='',
            type=self.task_type,
            status=ItemStatus.INBOX,
        )
        
        # Verify blank value was saved
        self.assertEqual(item.user_input, '')
    
    def test_user_input_field_default(self):
        """Test that user_input field defaults to empty string."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Test description',
            type=self.task_type,
            status=ItemStatus.INBOX,
        )
        
        # Verify default value
        self.assertEqual(item.user_input, '')
    
    def test_user_input_independent_from_description(self):
        """Test that user_input and description are independent fields."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='AI-processed description',
            user_input='Original email HTML',
            type=self.task_type,
            status=ItemStatus.INBOX,
        )
        
        # Modify description
        item.description = 'Updated AI description'
        item.save()
        
        # Reload from database
        item.refresh_from_db()
        
        # Verify user_input was not affected
        self.assertEqual(item.user_input, 'Original email HTML')
        self.assertEqual(item.description, 'Updated AI description')
    
    def test_user_input_can_store_html(self):
        """Test that user_input can store HTML content."""
        html_content = '<h1>Test Header</h1><p>This is <strong>HTML</strong> content</p>'
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Plain text description',
            user_input=html_content,
            type=self.task_type,
            status=ItemStatus.INBOX,
        )
        
        # Reload from database
        item.refresh_from_db()
        
        # Verify HTML was preserved
        self.assertEqual(item.user_input, html_content)
