"""
Tests for Item Detail page views and HTMX endpoints.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item, 
    ItemStatus, Release, ItemComment, ExternalIssueMapping, 
    ExternalIssueKind, AttachmentRole, Attachment, AttachmentLink,
    CommentKind, ReleaseStatus
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
        self.client.login(username='testuser', password='testpass')
    
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
    
    def test_item_comments_tab_with_ai_generated_markdown(self):
        """Test that AI-generated comments with markdown are rendered correctly."""
        # Create AI-generated comment with markdown content
        markdown_content = """# AI Analysis

This is an **AI-generated** comment with markdown:

- Point 1
- Point 2
- Point 3

```python
def example():
    return "code block"
```
"""
        ItemComment.objects.create(
            item=self.item,
            author=self.user,
            body=markdown_content,
            kind=CommentKind.AI_GENERATED
        )
        
        url = reverse('item-comments-tab', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        # Check that the markdown-viewer div is present for AI-generated comments
        self.assertContains(response, 'markdown-viewer')
        # Check that markdown is converted to HTML (heading tag should be present)
        self.assertContains(response, '<h1>')
        # Check that the AI Generated badge is present
        self.assertContains(response, 'AI Generated')
    
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
        url = reverse('item-change-status', args=[self.item.id])
        response = self.client.post(url, {'status': ItemStatus.TESTING})
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item status changed
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.TESTING)
    
    def test_item_add_comment(self):
        """Test adding a comment to an item."""
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
    
    def test_item_detail_has_releases_context(self):
        """Test that item detail view includes releases in context."""
        url = reverse('item-detail', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('releases', response.context)
        self.assertIn(self.release, response.context['releases'])
    
    def test_item_detail_shows_incoming_warning_for_incoming_project(self):
        """Test that incoming warning is shown for items in Incoming project."""
        # Create Incoming project
        incoming_project = Project.objects.create(
            name='Incoming',
            description='Incoming items'
        )
        incoming_project.clients.add(self.org)
        
        # Create item in Incoming project
        incoming_item = Item.objects.create(
            project=incoming_project,
            title='Incoming Item',
            description='Test description',
            type=self.item_type,
            organisation=self.org,
            status=ItemStatus.INBOX
        )
        
        url = reverse('item-detail', args=[incoming_item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Incoming-Projekt')
        self.assertContains(response, 'Achtung')
    
    def test_item_detail_no_incoming_warning_for_normal_project(self):
        """Test that incoming warning is not shown for normal projects."""
        url = reverse('item-detail', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Incoming-Projekt')
    
    def test_item_detail_has_content_tabs(self):
        """Test that item detail view has content tabs for Description, Original Mail, and Solution."""
        url = reverse('item-detail', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        # Check for tab navigation
        self.assertContains(response, 'description-content-tab')
        self.assertContains(response, 'original-mail-content-tab')
        self.assertContains(response, 'solution-content-tab')
        # Check for tab content areas
        self.assertContains(response, 'id="description-content"')
        self.assertContains(response, 'id="original-mail-content"')
        self.assertContains(response, 'id="solution-content"')
    
    def test_item_update_release_endpoint(self):
        """Test that the update release endpoint works correctly."""
        # Create another release
        new_release = Release.objects.create(
            project=self.project,
            name='Release 2.0',
            version='2.0.0'
        )
        
        url = reverse('item-update-release', args=[self.item.id])
        response = self.client.post(url, {'solution_release': new_release.id})
        
        self.assertEqual(response.status_code, 200)
        
        # Check that item was updated
        self.item.refresh_from_db()
        self.assertEqual(self.item.solution_release, new_release)
    
    def test_item_update_release_can_clear_release(self):
        """Test that release can be cleared to None."""
        url = reverse('item-update-release', args=[self.item.id])
        response = self.client.post(url, {'solution_release': ''})
        
        self.assertEqual(response.status_code, 200)
        
        # Check that item release was cleared
        self.item.refresh_from_db()
        self.assertIsNone(self.item.solution_release)


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
    
    def test_any_status_transition_allowed(self):
        """Test that any status transition is now allowed (Backlog -> ReadyForRelease)."""
        url = reverse('item-change-status', args=[self.item.id])
        response = self.client.post(url, {'status': ItemStatus.READY_FOR_RELEASE})
        
        # Should now return 200 as any transition is allowed
        self.assertEqual(response.status_code, 200)
        
        # Status should change
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.READY_FOR_RELEASE)


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


class SolutionReleaseFilteringTest(TestCase):
    """Test solution release filtering in item detail view."""
    
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
        
        # Create two projects
        self.project_a = Project.objects.create(
            name='Project A',
            description='Test project A'
        )
        self.project_a.clients.add(self.org)
        
        self.project_b = Project.objects.create(
            name='Project B',
            description='Test project B'
        )
        self.project_b.clients.add(self.org)
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        
        # Create releases for Project A
        self.release_a_planned = Release.objects.create(
            project=self.project_a,
            name='Release A Planned',
            version='1.0.0',
            status=ReleaseStatus.PLANNED
        )
        
        self.release_a_working = Release.objects.create(
            project=self.project_a,
            name='Release A Working',
            version='1.1.0',
            status=ReleaseStatus.WORKING
        )
        
        self.release_a_closed = Release.objects.create(
            project=self.project_a,
            name='Release A Closed',
            version='0.9.0',
            status=ReleaseStatus.CLOSED
        )
        
        # Create releases for Project B
        self.release_b_planned = Release.objects.create(
            project=self.project_b,
            name='Release B Planned',
            version='2.0.0',
            status=ReleaseStatus.PLANNED
        )
        
        self.release_b_closed = Release.objects.create(
            project=self.project_b,
            name='Release B Closed',
            version='1.9.0',
            status=ReleaseStatus.CLOSED
        )
        
        # Create test item in Project A
        self.item = Item.objects.create(
            project=self.project_a,
            title='Test Item',
            description='Test description',
            type=self.item_type,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user,
            status=ItemStatus.WORKING
        )
        
        self.client = Client()
        self.client.login(username='testuser', password='testpass')
    
    def test_releases_filtered_by_project(self):
        """Test that only releases from the same project are shown in dropdown."""
        url = reverse('item-detail', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Get releases from context
        releases = response.context['releases']
        release_ids = [r.id for r in releases]
        
        # Should contain Project A releases (but not closed ones)
        self.assertIn(self.release_a_planned.id, release_ids)
        self.assertIn(self.release_a_working.id, release_ids)
        
        # Should NOT contain Project B releases
        self.assertNotIn(self.release_b_planned.id, release_ids)
        self.assertNotIn(self.release_b_closed.id, release_ids)
    
    def test_releases_exclude_closed_status(self):
        """Test that Closed releases are excluded from dropdown."""
        url = reverse('item-detail', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Get releases from context
        releases = response.context['releases']
        release_ids = [r.id for r in releases]
        
        # Should NOT contain closed releases
        self.assertNotIn(self.release_a_closed.id, release_ids)
        self.assertNotIn(self.release_b_closed.id, release_ids)
        
        # Should contain non-closed releases from same project
        self.assertIn(self.release_a_planned.id, release_ids)
        self.assertIn(self.release_a_working.id, release_ids)
    
    def test_badge_shows_assigned_closed_release(self):
        """Test that badge displays assigned release even if it's Closed."""
        # Assign a closed release to the item
        self.item.solution_release = self.release_a_closed
        self.item.save()
        
        url = reverse('item-detail', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check that the page contains the release badge
        self.assertContains(response, 'Release: 0.9.0')
        self.assertContains(response, 'bg-success')  # Closed releases use success color
        
        # Verify closed release is NOT in the dropdown options
        releases = response.context['releases']
        release_ids = [r.id for r in releases]
        self.assertNotIn(self.release_a_closed.id, release_ids)
    
    def test_badge_shows_assigned_foreign_project_release(self):
        """Test that badge displays assigned release even if from different project."""
        # Assign a release from Project B to item in Project A
        # (This would normally be prevented by validation, but could exist as legacy data)
        # We use update() to bypass the save() method validation
        Item.objects.filter(id=self.item.id).update(solution_release=self.release_b_planned)
        self.item.refresh_from_db()
        
        url = reverse('item-detail', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check that the page contains the release badge
        self.assertContains(response, 'Release: 2.0.0')
        self.assertContains(response, 'bg-info')  # Non-closed releases use info color
        
        # Verify foreign project release is NOT in the dropdown options
        releases = response.context['releases']
        release_ids = [r.id for r in releases]
        self.assertNotIn(self.release_b_planned.id, release_ids)
    
    def test_no_badge_when_no_release_assigned(self):
        """Test that no badge is shown when item has no solution_release."""
        # Item has no solution_release (None)
        url = reverse('item-detail', args=[self.item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Check that the release version badge pattern is not present in card header
        # The badge would show "Release: X.Y.Z"
        content = response.content.decode('utf-8')
        
        # Check that header doesn't contain release badge
        # Look for the pattern: badge with bg-success or bg-info containing "Release: "
        self.assertNotIn('bg-success">Release: ', content)
        self.assertNotIn('bg-info">Release: ', content)
    
    def test_empty_dropdown_when_all_releases_closed(self):
        """Test that dropdown is empty when all releases for project are Closed."""
        # Create a new project with only closed releases
        project_c = Project.objects.create(
            name='Project C',
            description='Test project C'
        )
        project_c.clients.add(self.org)
        
        Release.objects.create(
            project=project_c,
            name='Release C Closed 1',
            version='1.0.0',
            status=ReleaseStatus.CLOSED
        )
        
        Release.objects.create(
            project=project_c,
            name='Release C Closed 2',
            version='2.0.0',
            status=ReleaseStatus.CLOSED
        )
        
        # Create item in Project C
        item_c = Item.objects.create(
            project=project_c,
            title='Test Item C',
            description='Test description',
            type=self.item_type,
            organisation=self.org,
            requester=self.user,
            status=ItemStatus.WORKING
        )
        
        url = reverse('item-detail', args=[item_c.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Verify releases list is empty
        releases = response.context['releases']
        self.assertEqual(len(releases), 0)
