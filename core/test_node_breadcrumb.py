"""
Tests for Node breadcrumb functionality and Item description updates.
"""
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item, 
    ItemStatus, Node, NodeType
)

User = get_user_model()


class NodeBreadcrumbTest(TestCase):
    """Test the Node breadcrumb generation."""
    
    def setUp(self):
        """Set up test data."""
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        
        # Create node hierarchy
        self.root_node = Node.objects.create(
            project=self.project,
            name='Root',
            type=NodeType.PROJECT,
            parent_node=None
        )
        
        self.sub_node = Node.objects.create(
            project=self.project,
            name='Subnode',
            type=NodeType.VIEW,
            parent_node=self.root_node
        )
        
        self.leaf_node = Node.objects.create(
            project=self.project,
            name='Leafnode',
            type=NodeType.ENTITY,
            parent_node=self.sub_node
        )
    
    def test_breadcrumb_root_node(self):
        """Test breadcrumb for a root node (no parent)."""
        breadcrumb = self.root_node.get_breadcrumb()
        self.assertEqual(breadcrumb, 'Root')
    
    def test_breadcrumb_sub_node(self):
        """Test breadcrumb for a node with one parent."""
        breadcrumb = self.sub_node.get_breadcrumb()
        self.assertEqual(breadcrumb, 'Root / Subnode')
    
    def test_breadcrumb_leaf_node(self):
        """Test breadcrumb for a leaf node with two ancestors."""
        breadcrumb = self.leaf_node.get_breadcrumb()
        self.assertEqual(breadcrumb, 'Root / Subnode / Leafnode')


class ItemNodeBreadcrumbTest(TestCase):
    """Test Item description updates with node breadcrumbs."""
    
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
        
        self.sub_node = Node.objects.create(
            project=self.project,
            name='Feature A',
            type=NodeType.VIEW,
            parent_node=self.root_node
        )
    
    def test_item_update_description_with_breadcrumb(self):
        """Test that updating an item with a node adds breadcrumb to description."""
        # Create item with initial description
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='This is the original description.',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Update description with breadcrumb
        item.update_description_with_breadcrumb(self.sub_node)
        
        # Check the description format
        expected_desc = "Betrifft: Root / Feature A\n\n---\nThis is the original description."
        self.assertEqual(item.description, expected_desc)
    
    def test_item_update_description_replaces_existing_breadcrumb(self):
        """Test that updating breadcrumb replaces the existing one."""
        # Create item with existing breadcrumb
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Betrifft: Old Breadcrumb\n\n---\nOriginal content.',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Update with new breadcrumb
        item.update_description_with_breadcrumb(self.sub_node)
        
        # Check the description only has new breadcrumb
        expected_desc = "Betrifft: Root / Feature A\n\n---\nOriginal content."
        self.assertEqual(item.description, expected_desc)
    
    def test_item_remove_breadcrumb(self):
        """Test that removing a node removes the breadcrumb."""
        # Create item with breadcrumb
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Betrifft: Root / Feature A\n\n---\nOriginal content.',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Remove breadcrumb by passing None
        item.update_description_with_breadcrumb(None)
        
        # Check the description has no breadcrumb
        self.assertEqual(item.description, 'Original content.')
    
    def test_item_with_no_initial_description(self):
        """Test breadcrumb update on item with no description."""
        # Create item with no description
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Update with breadcrumb
        item.update_description_with_breadcrumb(self.root_node)
        
        # Check the description has only breadcrumb
        expected_desc = "Betrifft: Root\n\n---\n"
        self.assertEqual(item.description, expected_desc)
    
    def test_get_primary_node(self):
        """Test getting the primary node of an item."""
        # Create item
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # No nodes assigned yet
        self.assertIsNone(item.get_primary_node())
        
        # Add a node
        item.nodes.add(self.sub_node)
        
        # Should return the first node
        self.assertEqual(item.get_primary_node(), self.sub_node)
    
    def test_validate_nodes_success(self):
        """Test that validate_nodes passes when all nodes belong to project."""
        # Create item
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Add nodes from the same project
        item.nodes.add(self.root_node)
        item.nodes.add(self.sub_node)
        
        # Should not raise an exception
        try:
            item.validate_nodes()
        except ValidationError:
            self.fail("validate_nodes() raised ValidationError unexpectedly")
    
    def test_validate_nodes_failure(self):
        """Test that validate_nodes fails when node belongs to different project."""
        # Create another project
        other_project = Project.objects.create(
            name='Other Project',
            description='Other description'
        )
        
        # Create node in other project
        other_node = Node.objects.create(
            project=other_project,
            name='Other Node',
            type=NodeType.PROJECT
        )
        
        # Create item in first project
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        
        # Try to add node from different project
        item.nodes.add(other_node)
        
        # Should raise ValidationError
        with self.assertRaises(ValidationError) as context:
            item.validate_nodes()
        
        self.assertIn('nodes', context.exception.message_dict)
