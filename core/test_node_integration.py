"""
Integration test for Node breadcrumb in Item CRUD operations.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item, 
    ItemStatus, Node, NodeType
)

User = get_user_model()


class ItemNodeIntegrationTest(TestCase):
    """Integration test for item creation/update with nodes."""
    
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
            description='Test description'
        )
        self.project.clients.add(self.org)
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        
        # Create node hierarchy
        self.root_node = Node.objects.create(
            project=self.project,
            name='Root',
            type=NodeType.PROJECT,
            parent_node=None
        )
        
        self.feature_node = Node.objects.create(
            project=self.project,
            name='Feature X',
            type=NodeType.VIEW,
            parent_node=self.root_node
        )
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def test_item_create_with_node_via_model(self):
        """Test creating item with node using model methods."""
        # Create item
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='This is a test description.',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Add node and update breadcrumb
        item.nodes.add(self.feature_node)
        item.update_description_with_breadcrumb(self.feature_node)
        item.save()
        
        # Verify breadcrumb in description
        self.assertIn('Betrifft: Root / Feature X', item.description)
        self.assertIn('This is a test description.', item.description)
        
        # Verify node is assigned
        self.assertEqual(item.get_primary_node(), self.feature_node)
    
    def test_item_update_node_changes_breadcrumb(self):
        """Test that changing node updates the breadcrumb."""
        # Create item with initial node
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Original content.',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        item.nodes.add(self.root_node)
        item.update_description_with_breadcrumb(self.root_node)
        item.save()
        
        # Verify initial breadcrumb
        self.assertIn('Betrifft: Root', item.description)
        
        # Change to different node
        item.nodes.clear()
        item.nodes.add(self.feature_node)
        item.update_description_with_breadcrumb(self.feature_node)
        item.save()
        
        # Verify new breadcrumb
        self.assertIn('Betrifft: Root / Feature X', item.description)
        self.assertNotIn('Betrifft: Root\n\n---\n', item.description)  # Old breadcrumb removed
        self.assertIn('Original content.', item.description)  # Content preserved
    
    def test_item_remove_node_removes_breadcrumb(self):
        """Test that removing node removes breadcrumb from description."""
        # Create item with node
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Content here.',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        item.nodes.add(self.feature_node)
        item.update_description_with_breadcrumb(self.feature_node)
        item.save()
        
        # Verify breadcrumb exists
        self.assertIn('Betrifft: Root / Feature X', item.description)
        
        # Remove node
        item.nodes.clear()
        item.update_description_with_breadcrumb(None)
        item.save()
        
        # Verify breadcrumb removed, content preserved
        self.assertNotIn('Betrifft:', item.description)
        self.assertEqual(item.description, 'Content here.')
    
    def test_item_validates_node_belongs_to_project(self):
        """Test that validation fails for nodes from different project."""
        # Create another project with node
        other_project = Project.objects.create(
            name='Other Project',
            description='Other description'
        )
        other_node = Node.objects.create(
            project=other_project,
            name='Other Node',
            type=NodeType.PROJECT
        )
        
        # Create item
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Try to add node from wrong project
        item.nodes.add(other_node)
        
        # Validation should fail
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            item.validate_nodes()
