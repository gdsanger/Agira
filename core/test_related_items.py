"""
Tests for Related Items tab and ItemRelations CRUD functionality.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item, 
    ItemStatus, ItemRelation, RelationType
)

User = get_user_model()


class RelatedItemsTabTest(TestCase):
    """Test the related items tab view."""
    
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
            key='feature',
            name='Feature'
        )
        
        # Create parent item
        self.parent_item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Parent Item',
            description='Parent description',
            status=ItemStatus.INBOX
        )
        
        # Create child items
        self.child_item1 = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Child Item 1',
            description='Child 1 description',
            status=ItemStatus.WORKING,
            parent=self.parent_item
        )
        
        self.child_item2 = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Child Item 2',
            description='Child 2 description',
            status=ItemStatus.BACKLOG,
            parent=self.parent_item
        )
        
        # Create related item relation
        ItemRelation.objects.create(
            from_item=self.parent_item,
            to_item=self.child_item1,
            relation_type=RelationType.RELATED
        )
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def test_related_items_tab_displays_child_items(self):
        """Test that the related items tab displays child items with type=Related."""
        url = reverse('item-related-items-tab', kwargs={'item_id': self.parent_item.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        # Check that Child Item 1 appears in the table (it has an ItemRelation)
        self.assertContains(response, 'Child Item 1')
        # Verify it's in the actual table, not just the modal
        content = response.content.decode()
        self.assertIn('<a href="/items/2/" class="text-decoration-none"><strong>Child Item 1</strong></a>', content)
        # Child Item 2 should not be in the table (no ItemRelation with type=Related)
        # But it may be in the dropdown for adding relations
        self.assertNotIn('<a href="/items/3/" class="text-decoration-none"><strong>Child Item 2</strong></a>', content)
    
    def test_related_items_tab_shows_all_relations(self):
        """Test that the related items tab shows all relations in the management section."""
        url = reverse('item-related-items-tab', kwargs={'item_id': self.parent_item.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'All Relations')
        self.assertContains(response, 'Child Item 1')


class ItemRelationCRUDTest(TestCase):
    """Test CRUD operations for ItemRelations."""
    
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
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='feature',
            name='Feature'
        )
        
        # Create items
        self.item1 = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Item 1',
            description='Item 1 description',
            status=ItemStatus.INBOX
        )
        
        self.item2 = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Item 2',
            description='Item 2 description',
            status=ItemStatus.INBOX
        )
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def test_create_item_relation(self):
        """Test creating a new item relation."""
        url = reverse('item-relation-create', kwargs={'item_id': self.item1.id})
        data = {
            'to_item': self.item2.id,
            'relation_type': RelationType.RELATED
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            ItemRelation.objects.filter(
                from_item=self.item1,
                to_item=self.item2,
                relation_type=RelationType.RELATED
            ).exists()
        )
    
    def test_delete_item_relation(self):
        """Test deleting an item relation."""
        # Create a relation first
        relation = ItemRelation.objects.create(
            from_item=self.item1,
            to_item=self.item2,
            relation_type=RelationType.RELATED
        )
        
        url = reverse('item-relation-delete', kwargs={
            'item_id': self.item1.id,
            'relation_id': relation.id
        })
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertFalse(ItemRelation.objects.filter(id=relation.id).exists())
    
    def test_update_item_relation(self):
        """Test updating an item relation."""
        # Create a relation first
        relation = ItemRelation.objects.create(
            from_item=self.item1,
            to_item=self.item2,
            relation_type=RelationType.RELATED
        )
        
        url = reverse('item-relation-update', kwargs={
            'item_id': self.item1.id,
            'relation_id': relation.id
        })
        data = {
            'to_item': self.item2.id,
            'relation_type': RelationType.DEPEND_ON
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        relation.refresh_from_db()
        self.assertEqual(relation.relation_type, RelationType.DEPEND_ON)
    
    def test_create_relation_duplicate_returns_error(self):
        """Test that creating a duplicate relation returns an error."""
        # Create a relation first
        ItemRelation.objects.create(
            from_item=self.item1,
            to_item=self.item2,
            relation_type=RelationType.RELATED
        )
        
        # Try to create the same relation again
        url = reverse('item-relation-create', kwargs={'item_id': self.item1.id})
        data = {
            'to_item': self.item2.id,
            'relation_type': RelationType.RELATED
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('already exists', response_data['message'])


class BackfillItemRelationsTest(TestCase):
    """Test the backfill_item_relations management command."""
    
    def setUp(self):
        """Set up test data."""
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='feature',
            name='Feature'
        )
        
        # Create parent item
        self.parent_item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Parent Item',
            description='Parent description',
            status=ItemStatus.INBOX
        )
        
        # Create child item with parent set
        self.child_item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Child Item',
            description='Child description',
            status=ItemStatus.INBOX,
            parent=self.parent_item
        )
    
    def test_backfill_creates_missing_relations(self):
        """Test that backfill creates missing ItemRelations."""
        from django.core.management import call_command
        from io import StringIO
        
        # Ensure no relation exists initially
        self.assertFalse(
            ItemRelation.objects.filter(
                from_item=self.parent_item,
                to_item=self.child_item,
                relation_type=RelationType.RELATED
            ).exists()
        )
        
        # Run backfill command
        out = StringIO()
        call_command('backfill_item_relations', stdout=out)
        
        # Verify relation was created
        self.assertTrue(
            ItemRelation.objects.filter(
                from_item=self.parent_item,
                to_item=self.child_item,
                relation_type=RelationType.RELATED
            ).exists()
        )
        
        # Verify output
        output = out.getvalue()
        self.assertIn('CREATE', output)
        self.assertIn('Created: 1', output)
    
    def test_backfill_is_idempotent(self):
        """Test that running backfill multiple times doesn't create duplicates."""
        from django.core.management import call_command
        from io import StringIO
        
        # Run backfill command twice
        call_command('backfill_item_relations', stdout=StringIO())
        call_command('backfill_item_relations', stdout=StringIO())
        
        # Verify only one relation exists
        relation_count = ItemRelation.objects.filter(
            from_item=self.parent_item,
            to_item=self.child_item,
            relation_type=RelationType.RELATED
        ).count()
        
        self.assertEqual(relation_count, 1)
    
    def test_backfill_dry_run_does_not_create_relations(self):
        """Test that dry-run mode doesn't create any relations."""
        from django.core.management import call_command
        from io import StringIO
        
        # Run backfill command in dry-run mode
        out = StringIO()
        call_command('backfill_item_relations', '--dry-run', stdout=out)
        
        # Verify no relation was created
        self.assertFalse(
            ItemRelation.objects.filter(
                from_item=self.parent_item,
                to_item=self.child_item,
                relation_type=RelationType.RELATED
            ).exists()
        )
        
        # Verify output mentions dry run
        output = out.getvalue()
        self.assertIn('DRY RUN', output)
