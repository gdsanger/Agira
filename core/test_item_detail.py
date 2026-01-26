"""
Tests for Item Detail page views and HTMX endpoints.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item, 
    ItemStatus, Release, ItemComment, ExternalIssueMapping, 
    ExternalIssueKind, AttachmentRole, Attachment, AttachmentLink
)
from core.services.activity import ActivityService

User = get_user_model()


class ItemDetailViewTest(TestCase):
    """Test the item detail view."""
    
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
        
        # Create release
        self.release = Release.objects.create(
            project=self.project,
            name='Release 1.0',
            version='1.0.0'
        )
        
        # Create test item
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Test description',
            type=self.item_type,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user,
            status=ItemStatus.WORKING,
            solution_release=self.release
        )
        
        self.client = Client()
    
    def test_item_detail_view_loads(self):
        """Test that item detail view loads successfully."""
        url = reverse('item-detail', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item.title)
        self.assertContains(response, 'Overview')
        self.assertContains(response, 'Comments')
        self.assertContains(response, 'Attachments')
        self.assertContains(response, 'Activity')
        self.assertContains(response, 'GitHub')
    
    def test_item_comments_tab_loads(self):
        """Test that comments tab endpoint loads successfully."""
        # Create test comments
        ItemComment.objects.create(
            item=self.item,
            author=self.user,
            body='Test comment'
        )
        
        url = reverse('item-comments-tab', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test comment')
        self.assertContains(response, 'Add Comment')
    
    def test_item_activity_tab_loads(self):
        """Test that activity tab endpoint loads successfully."""
        # Create test activity
        activity_service = ActivityService()
        activity_service.log(
            verb='item.created',
            target=self.item,
            actor=self.user,
            summary='Created item'
        )
        
        url = reverse('item-activity-tab', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'item.created')
    
    def test_item_github_tab_loads(self):
        """Test that GitHub tab endpoint loads successfully."""
        # Create test mapping
        ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=123456,
            number=42,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/test/test/issues/42'
        )
        
        url = reverse('item-github-tab', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '#42')
        self.assertContains(response, 'Issue')
    
    def test_item_attachments_tab_loads(self):
        """Test that attachments tab endpoint loads successfully."""
        url = reverse('item-attachments-tab', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Drag & drop files here')
    
    def test_item_change_status(self):
        """Test changing item status."""
        self.client.login(username='testuser', password='testpass')
        
        url = reverse('item-change-status', args=[self.item.id])
        response = self.client.post(url, {'status': ItemStatus.TESTING})
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item status changed
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.TESTING)
    
    def test_item_add_comment(self):
        """Test adding a comment to an item."""
        self.client.login(username='testuser', password='testpass')
        
        url = reverse('item-add-comment', args=[self.item.id])
        response = self.client.post(url, {'body': 'New test comment'})
        
        # Should return rendered template (200)
        self.assertEqual(response.status_code, 200)
        
        # Verify comment was created
        comment = ItemComment.objects.filter(item=self.item, body='New test comment').first()
        self.assertIsNotNone(comment)
        self.assertEqual(comment.author, self.user)
        
        # Verify activity was logged
        activities = ActivityService().latest(item=self.item, limit=1)
        self.assertEqual(activities.count(), 1)
        self.assertEqual(activities[0].verb, 'comment.added')


class ItemDetailWorkflowTest(TestCase):
    """Test item detail workflow transitions."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            name='Test User'
        )
        
        self.org = Organisation.objects.create(name='Test Org')
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org,
            is_primary=True
        )
        
        self.project = Project.objects.create(name='Test Project')
        self.project.clients.add(self.org)
        
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            organisation=self.org,
            requester=self.user,
            status=ItemStatus.BACKLOG
        )
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def test_valid_status_transition(self):
        """Test a valid status transition (Backlog -> Working)."""
        url = reverse('item-change-status', args=[self.item.id])
        response = self.client.post(url, {'status': ItemStatus.WORKING})
        
        self.assertEqual(response.status_code, 200)
        
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)
    
    def test_invalid_status_transition(self):
        """Test an invalid status transition (Backlog -> ReadyForRelease)."""
        url = reverse('item-change-status', args=[self.item.id])
        response = self.client.post(url, {'status': ItemStatus.READY_FOR_RELEASE})
        
        # Should return 400 error for invalid transition
        self.assertEqual(response.status_code, 400)
        
        # Status should not change
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.BACKLOG)


class ItemCRUDTest(TestCase):
    """Test item CRUD operations."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            name='Test User'
        )
        
        self.org = Organisation.objects.create(name='Test Org')
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org,
            is_primary=True
        )
        
        self.project = Project.objects.create(name='Test Project')
        self.project.clients.add(self.org)
        
        self.item_type = ItemType.objects.create(key='bug', name='Bug', is_active=True)
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def test_item_create_view_loads(self):
        """Test that item create view loads successfully."""
        url = reverse('item-create')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create New Item')
        self.assertContains(response, 'title')
        self.assertContains(response, 'project')
        self.assertContains(response, 'type')
    
    def test_item_create_post(self):
        """Test creating a new item via POST."""
        url = reverse('item-create')
        data = {
            'title': 'New Test Item',
            'description': 'Test description',
            'solution_description': 'Test solution',
            'project': self.project.id,
            'type': self.item_type.id,
            'status': ItemStatus.INBOX,
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item was created
        item = Item.objects.filter(title='New Test Item').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.description, 'Test description')
        self.assertEqual(item.project, self.project)
        self.assertEqual(item.type, self.item_type)
    
    def test_item_edit_view_loads(self):
        """Test that item edit view loads successfully."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG
        )
        
        url = reverse('item-edit', args=[item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Item')
        self.assertContains(response, item.title)
    
    def test_item_update_post(self):
        """Test updating an item via POST."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG
        )
        
        url = reverse('item-update', args=[item.id])
        data = {
            'title': 'Updated Test Item',
            'description': 'Updated description',
            'solution_description': 'Updated solution',
            'project': self.project.id,
            'type': self.item_type.id,
            'status': ItemStatus.WORKING,
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item was updated
        item.refresh_from_db()
        self.assertEqual(item.title, 'Updated Test Item')
        self.assertEqual(item.description, 'Updated description')
        self.assertEqual(item.status, ItemStatus.WORKING)
    
    def test_item_delete_post(self):
        """Test deleting an item via POST."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG
        )
        
        item_id = item.id
        url = reverse('item-delete', args=[item_id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item was deleted
        self.assertFalse(Item.objects.filter(id=item_id).exists())


class ItemAutoPopulateTest(TestCase):
    """Test automatic pre-population of requester and organisation when creating items."""
    
    def setUp(self):
        """Set up test data."""
        # Create organisations
        self.org1 = Organisation.objects.create(name='Primary Org')
        self.org2 = Organisation.objects.create(name='Secondary Org')
        
        # Create user with primary organisation
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            name='Test User',
            role='User'
        )
        
        # Set primary organisation
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org1,
            is_primary=True
        )
        
        # Add secondary organisation (not primary)
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org2,
            is_primary=False
        )
        
        # Create user without primary organisation
        self.user_no_org = User.objects.create_user(
            username='usernoorg',
            email='noorg@example.com',
            password='testpass',
            name='User No Org',
            role='User'
        )
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        self.project.clients.add(self.org1)
        self.project.clients.add(self.org2)
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='feature',
            name='Feature',
            is_active=True
        )
        
        self.client = Client()
    
    def test_item_create_auto_populates_requester_and_organisation(self):
        """Test that item creation auto-populates requester and organisation for logged-in user."""
        # Login as user
        self.client.login(username='testuser', password='testpass')
        
        url = reverse('item-create')
        data = {
            'title': 'Auto-populated Item',
            'description': 'Test description',
            'project': self.project.id,
            'type': self.item_type.id,
            'status': ItemStatus.INBOX,
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item was created with auto-populated fields
        item = Item.objects.filter(title='Auto-populated Item').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.requester, self.user)
        self.assertEqual(item.organisation, self.org1)  # Primary org
    
    def test_item_create_respects_explicit_requester_and_organisation(self):
        """Test that explicitly set requester and organisation are preserved."""
        # Login as user
        self.client.login(username='testuser', password='testpass')
        
        # Create another user to use as explicit requester
        other_user = User.objects.create_user(
            username='otheruser',
            email='other@example.com',
            password='testpass',
            name='Other User'
        )
        # Make other_user a member of org2
        UserOrganisation.objects.create(
            user=other_user,
            organisation=self.org2,
            is_primary=True
        )
        
        url = reverse('item-create')
        data = {
            'title': 'Explicit Values Item',
            'description': 'Test description',
            'project': self.project.id,
            'type': self.item_type.id,
            'status': ItemStatus.INBOX,
            'requester': other_user.id,
            'organisation': self.org2.id,  # Explicitly set to secondary org
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item was created with explicit values
        item = Item.objects.filter(title='Explicit Values Item').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.requester, other_user)  # Not auto-populated
        self.assertEqual(item.organisation, self.org2)  # Not primary org
    
    def test_item_create_without_primary_organisation(self):
        """Test that item creation works when user has no primary organisation."""
        # Login as user without primary org
        self.client.login(username='usernoorg', password='testpass')
        
        url = reverse('item-create')
        data = {
            'title': 'No Primary Org Item',
            'description': 'Test description',
            'project': self.project.id,
            'type': self.item_type.id,
            'status': ItemStatus.INBOX,
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item was created
        item = Item.objects.filter(title='No Primary Org Item').first()
        self.assertIsNotNone(item)
        self.assertEqual(item.requester, self.user_no_org)  # Requester still auto-populated
        self.assertIsNone(item.organisation)  # Organisation not set
    
    def test_item_create_without_authenticated_user(self):
        """Test that item creation without authenticated user doesn't auto-populate."""
        # Don't login
        url = reverse('item-create')
        data = {
            'title': 'No Auth Item',
            'description': 'Test description',
            'project': self.project.id,
            'type': self.item_type.id,
            'status': ItemStatus.INBOX,
        }
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item was created without auto-populated fields
        item = Item.objects.filter(title='No Auth Item').first()
        self.assertIsNotNone(item)
        self.assertIsNone(item.requester)
        self.assertIsNone(item.organisation)
    
    def test_item_create_view_defaults_in_form(self):
        """Test that the create form shows default values for requester and organisation."""
        # Login as user
        self.client.login(username='testuser', password='testpass')
        
        url = reverse('item-create')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check that context contains default values
        self.assertEqual(response.context['default_requester'], self.user)
        self.assertEqual(response.context['default_organisation'], self.org1)
    
    def test_item_create_view_no_defaults_without_auth(self):
        """Test that the create form doesn't have defaults without authentication."""
        # Don't login
        url = reverse('item-create')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check that context has no default values
        self.assertIsNone(response.context['default_requester'])
        self.assertIsNone(response.context['default_organisation'])
