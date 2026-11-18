"""
Tests for Node hierarchical functionality.
"""
from django.core.exceptions import ValidationError
from django.test import TestCase
from core.models import Project, Node, NodeType


class NodeHierarchyTest(TestCase):
    """Test the Node hierarchy methods."""
    
    def setUp(self):
        """Set up test data."""
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        
        # Create node hierarchy
        self.root = Node.objects.create(
            project=self.project,
            name='Root',
            type=NodeType.PROJECT,
            parent_node=None
        )
        
        self.child1 = Node.objects.create(
            project=self.project,
            name='Child1',
            type=NodeType.VIEW,
            parent_node=self.root
        )
        
        self.child2 = Node.objects.create(
            project=self.project,
            name='Child2',
            type=NodeType.VIEW,
            parent_node=self.root
        )
        
        self.grandchild = Node.objects.create(
            project=self.project,
            name='Grandchild',
            type=NodeType.ENTITY,
            parent_node=self.child1
        )
    
    def test_would_create_cycle_self(self):
        """Test that a node cannot be its own parent."""
        self.assertTrue(self.root.would_create_cycle(self.root))
    
    def test_would_create_cycle_direct_descendant(self):
        """Test that a node cannot have its child as parent."""
        self.assertTrue(self.root.would_create_cycle(self.child1))
    
    def test_would_create_cycle_indirect_descendant(self):
        """Test that a node cannot have its grandchild as parent."""
        self.assertTrue(self.root.would_create_cycle(self.grandchild))
    
    def test_would_create_cycle_valid_parent(self):
        """Test that a valid parent assignment is allowed."""
        # Child2 can have Child1 as parent (they are siblings)
        self.assertFalse(self.child2.would_create_cycle(self.child1))
        
        # Grandchild can have Child2 as parent (different branch)
        self.assertFalse(self.grandchild.would_create_cycle(self.child2))
    
    def test_would_create_cycle_none(self):
        """Test that None is always valid (root node)."""
        self.assertFalse(self.root.would_create_cycle(None))
        self.assertFalse(self.child1.would_create_cycle(None))
    
    def test_get_tree_structure(self):
        """Test tree structure generation."""
        tree = self.root.get_tree_structure()
        
        self.assertEqual(tree['id'], self.root.id)
        self.assertEqual(tree['name'], 'Root')
        self.assertEqual(len(tree['children']), 2)
        
        # Check first child
        child1_tree = next(c for c in tree['children'] if c['id'] == self.child1.id)
        self.assertEqual(child1_tree['name'], 'Child1')
        self.assertEqual(len(child1_tree['children']), 1)
        
        # Check grandchild
        grandchild_tree = child1_tree['children'][0]
        self.assertEqual(grandchild_tree['id'], self.grandchild.id)
        self.assertEqual(grandchild_tree['name'], 'Grandchild')
        self.assertEqual(len(grandchild_tree['children']), 0)


class ClosedParentTests(TestCase):
    """A closed epic can no longer be chosen as parent, but its children stay editable."""

    def setUp(self):
        from core.models import Item, ItemStatus, ItemType, Project
        self.Item, self.ItemStatus = Item, ItemStatus
        self.project = Project.objects.create(name='P')
        self.type = ItemType.objects.create(key='bug', name='Bug')
        self.epic = Item.objects.create(
            title='Epic', description='d', project=self.project, type=self.type)

    def _item(self, **kw):
        return self.Item.objects.create(
            title='Sub', description='d', project=self.project, type=self.type, **kw)

    def test_closed_item_cannot_become_parent_of_new_or_existing_item(self):
        sub = self._item(parent=self.epic)
        other = self._item()
        self.epic.status = self.ItemStatus.CLOSED
        self.epic.save()
        with self.assertRaises(ValidationError):
            self._item(parent=self.epic)
        other.parent = self.epic
        with self.assertRaises(ValidationError):
            other.save()

    def test_child_of_closed_parent_can_still_be_saved(self):
        sub = self._item(parent=self.epic)
        self.epic.status = self.ItemStatus.CLOSED
        self.epic.save()
        sub = self.Item.objects.get(pk=sub.pk)
        sub.pr_description = 'PR text'
        sub.save(update_fields=['pr_description'])
        sub.status = self.ItemStatus.TESTING
        sub.save()
        self.assertEqual(self.Item.objects.get(pk=sub.pk).pr_description, 'PR text')
