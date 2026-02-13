"""
Tests for Item creation with description field persistence.
This tests the fix for issue #397 where the description field was not being saved.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item, Node,
    ItemStatus, ProjectStatus
)

User = get_user_model()


class ItemDescriptionSaveTest(TestCase):
    """Test that item description is saved during item creation."""
    
    def setUp(self):
        """Set up test data."""
        # Create user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            name='Test User',
            role='Agent'
        )
        
        # Create organisation
        self.org = Organisation.objects.create(name='Test Org')
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description',
            status=ProjectStatus.WORKING
        )
        self.project.clients.add(self.org)
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        
        # Create client
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def test_item_create_saves_description(self):
        """Test that description field is saved when creating an item."""
        # Arrange
        test_description = "This is a test description with multiple lines.\n\nSecond paragraph here."
        test_title = "Test Item Title"
        
        # Act
        response = self.client.post(
            reverse('item-create'),
            {
                'project': self.project.id,
                'type': self.item_type.id,
                'title': test_title,
                'description': test_description,
                'status': ItemStatus.INBOX,
            },
            HTTP_HX_REQUEST='true'  # Simulate HTMX request
        )
        
        # Assert
        self.assertEqual(response.status_code, 200, "Item creation should succeed")
        
        # Verify item was created
        items = Item.objects.filter(title=test_title)
        self.assertEqual(items.count(), 1, "Exactly one item should be created")
        
        item = items.first()
        self.assertIsNotNone(item, "Item should exist")
        self.assertEqual(item.description, test_description, 
                        "Description should be saved exactly as provided")
        self.assertEqual(item.title, test_title, "Title should be saved")
        self.assertEqual(item.project, self.project, "Project should be assigned")
        self.assertEqual(item.type, self.item_type, "Type should be assigned")
    
    def test_item_create_saves_empty_description(self):
        """Test that empty description is handled correctly."""
        # Arrange
        test_title = "Test Item Without Description"
        
        # Act
        response = self.client.post(
            reverse('item-create'),
            {
                'project': self.project.id,
                'type': self.item_type.id,
                'title': test_title,
                'description': '',  # Empty description
                'status': ItemStatus.INBOX,
            },
            HTTP_HX_REQUEST='true'
        )
        
        # Assert
        self.assertEqual(response.status_code, 200)
        
        item = Item.objects.filter(title=test_title).first()
        self.assertIsNotNone(item)
        self.assertEqual(item.description, '', "Empty description should be saved as empty string")
    
    def test_item_create_saves_markdown_description(self):
        """Test that markdown formatted description is saved correctly."""
        # Arrange
        test_description = """# Test Heading

This is a **bold** text and *italic* text.

## Subheading

- List item 1
- List item 2

```python
def test():
    return True
```
"""
        test_title = "Test Item With Markdown"
        
        # Act
        response = self.client.post(
            reverse('item-create'),
            {
                'project': self.project.id,
                'type': self.item_type.id,
                'title': test_title,
                'description': test_description,
                'status': ItemStatus.INBOX,
            },
            HTTP_HX_REQUEST='true'
        )
        
        # Assert
        self.assertEqual(response.status_code, 200)
        
        item = Item.objects.filter(title=test_title).first()
        self.assertIsNotNone(item)
        self.assertEqual(item.description, test_description, 
                        "Markdown description should be saved exactly as provided")
    
    def test_item_reload_shows_saved_description(self):
        """Test that after creating an item, reloading shows the saved description."""
        # Arrange
        test_description = "Description that should persist after reload"
        test_title = "Test Item For Reload"
        
        # Act - Create item
        response = self.client.post(
            reverse('item-create'),
            {
                'project': self.project.id,
                'type': self.item_type.id,
                'title': test_title,
                'description': test_description,
                'status': ItemStatus.INBOX,
            },
            HTTP_HX_REQUEST='true'
        )
        
        # Get the created item
        item = Item.objects.filter(title=test_title).first()
        self.assertIsNotNone(item, "Item should be created")
        
        # Act - Reload item detail page
        detail_response = self.client.get(reverse('item-detail', args=[item.id]))
        
        # Assert
        self.assertEqual(detail_response.status_code, 200)
        self.assertContains(detail_response, test_description, 
                          msg_prefix="Description should be visible in detail view")
    
    def test_no_regression_existing_items_keep_description(self):
        """Test that existing items are not affected by the fix."""
        # Arrange - Create an item directly using Django ORM
        existing_description = "Existing item description"
        existing_item = Item.objects.create(
            project=self.project,
            title="Existing Item",
            description=existing_description,
            type=self.item_type,
            status=ItemStatus.BACKLOG
        )
        
        # Act - Reload the item
        reloaded_item = Item.objects.get(id=existing_item.id)
        
        # Assert
        self.assertEqual(reloaded_item.description, existing_description,
                        "Existing items should retain their description")

    def test_item_update_with_empty_node_param_preserves_description(self):
        """Description should survive updates even when node is posted as empty string."""
        item = Item.objects.create(
            project=self.project,
            title="Item to update",
            description="Beschreibung bleibt erhalten",
            type=self.item_type,
            status=ItemStatus.BACKLOG
        )
        Node.objects.create(project=self.project, name='Root')

        response = self.client.post(
            reverse('item-update', args=[item.id]),
            {
                'project': self.project.id,
                'type': self.item_type.id,
                'title': item.title,
                'description': item.description,
                'status': ItemStatus.BACKLOG,
                'node': '',
            },
            HTTP_HX_REQUEST='true'
        )

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.description, "Beschreibung bleibt erhalten")
