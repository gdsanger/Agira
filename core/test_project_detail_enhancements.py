"""
Tests for project detail view enhancements (Issue #189)
"""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ProjectStatus, Release, ReleaseStatus, RiskLevel, ReleaseType
)


class ProjectItemsSolutionReleaseTestCase(TestCase):
    """Test cases for Solution Release column in Items tab"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(name="Test Organisation")
        
        # Create test user and authenticate
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.client.login(username="testuser", password="testpass123")
        
        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key="task",
            name="Task"
        )
        
        # Create releases
        self.release1 = Release.objects.create(
            project=self.project,
            name="Release 1.0",
            version="1.0.0",
            status=ReleaseStatus.PLANNED,
            risk=RiskLevel.NORMAL
        )
        
        self.release2 = Release.objects.create(
            project=self.project,
            name="Release 2.0",
            version="2.0.0",
            status=ReleaseStatus.WORKING,
            risk=RiskLevel.HIGH
        )
        
        # Create items
        self.item1 = Item.objects.create(
            title="Test Item 1",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.INBOX,
            organisation=self.org,
            solution_release=self.release1
        )
        
        self.item2 = Item.objects.create(
            title="Test Item 2",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.CLOSED,
            organisation=self.org
        )
    
    def test_items_tab_shows_solution_release_column(self):
        """Test that Solution Release column is displayed"""
        response = self.client.get(reverse('project-items-tab', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        self.assertIn('Solution Release', content)
        self.assertNotIn('Assigned To', content)
    
    def test_items_tab_shows_release_dropdown(self):
        """Test that release dropdown is shown for each item"""
        response = self.client.get(reverse('project-items-tab', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        # Check for dropdown with HTMX attributes
        self.assertIn('hx-post=', content)
        self.assertIn('item-update-release', content)
        self.assertIn(self.release1.version, content)
        self.assertIn(self.release2.version, content)
    
    def test_solution_release_update_endpoint(self):
        """Test that solution release can be updated via HTMX"""
        response = self.client.post(
            reverse('item-update-release', args=[self.item2.id]),
            {'solution_release': self.release2.id}
        )
        self.assertEqual(response.status_code, 200)
        
        # Verify the item was updated
        self.item2.refresh_from_db()
        self.assertEqual(self.item2.solution_release, self.release2)


class ProjectItemsStatusFilterTestCase(TestCase):
    """Test cases for simplified status filter"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(name="Test Organisation")
        
        # Create test user and authenticate
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.client.login(username="testuser", password="testpass123")
        
        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key="task",
            name="Task"
        )
        
        # Create items with different statuses
        Item.objects.create(
            title="Open Item 1",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.INBOX,
            organisation=self.org
        )
        
        Item.objects.create(
            title="Open Item 2",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
            organisation=self.org
        )
        
        Item.objects.create(
            title="Closed Item 1",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.CLOSED,
            organisation=self.org
        )
        
        Item.objects.create(
            title="Closed Item 2",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.CLOSED,
            organisation=self.org
        )
    
    def test_default_filter_shows_not_closed(self):
        """Test that default filter shows non-closed items"""
        response = self.client.get(reverse('project-items-tab', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        # Should show 2 open items by default
        self.assertEqual(len(response.context['page_obj']), 2)
    
    def test_filter_closed_items(self):
        """Test filtering for closed items"""
        response = self.client.get(
            reverse('project-items-tab', args=[self.project.id]),
            {'status_filter': 'closed'}
        )
        self.assertEqual(response.status_code, 200)
        
        # Should show 2 closed items
        self.assertEqual(len(response.context['page_obj']), 2)
        for item in response.context['page_obj']:
            self.assertEqual(item.status, ItemStatus.CLOSED)
    
    def test_status_filter_select_in_template(self):
        """Test that status filter is a select dropdown"""
        response = self.client.get(reverse('project-items-tab', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        self.assertIn('status_filter', content)
        self.assertIn('Open Items (Not Closed)', content)
        self.assertIn('Closed Items', content)


class ProjectReleasesEditDeleteTestCase(TestCase):
    """Test cases for Release Edit and Delete functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test user and authenticate
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.client.login(username="testuser", password="testpass123")
        
        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
        
        # Create release
        self.release = Release.objects.create(
            project=self.project,
            name="Test Release",
            version="1.0.0",
            type=ReleaseType.MAJOR,
            status=ReleaseStatus.PLANNED,
            risk=RiskLevel.NORMAL
        )
    
    def test_create_release_with_status_and_risk(self):
        """Test creating a release with status and risk fields"""
        response = self.client.post(
            reverse('project-add-release', args=[self.project.id]),
            {
                'name': 'New Release',
                'version': '2.0.0',
                'type': ReleaseType.MINOR,
                'status': ReleaseStatus.WORKING,
                'risk': RiskLevel.HIGH
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify release was created with correct fields
        release = Release.objects.get(version='2.0.0')
        self.assertEqual(release.status, ReleaseStatus.WORKING)
        self.assertEqual(release.risk, RiskLevel.HIGH)
    
    def test_update_release(self):
        """Test updating a release"""
        response = self.client.post(
            reverse('project-update-release', args=[self.project.id, self.release.id]),
            {
                'name': 'Updated Release',
                'version': '1.1.0',
                'type': ReleaseType.HOTFIX,
                'status': ReleaseStatus.CLOSED,
                'risk': RiskLevel.LOW
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify release was updated
        self.release.refresh_from_db()
        self.assertEqual(self.release.name, 'Updated Release')
        self.assertEqual(self.release.version, '1.1.0')
        self.assertEqual(self.release.status, ReleaseStatus.CLOSED)
        self.assertEqual(self.release.risk, RiskLevel.LOW)
    
    def test_delete_release(self):
        """Test deleting a release"""
        release_id = self.release.id
        
        response = self.client.post(
            reverse('project-delete-release', args=[self.project.id, self.release.id])
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify release was deleted
        with self.assertRaises(Release.DoesNotExist):
            Release.objects.get(id=release_id)
    
    def test_project_detail_shows_edit_delete_buttons(self):
        """Test that release table shows edit and delete buttons"""
        response = self.client.get(reverse('project-detail', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        self.assertIn('editRelease', content)
        self.assertIn('project-delete-release', content)


class ProjectAttachmentsPagingTestCase(TestCase):
    """Test cases for Attachments tab pagination"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test user and authenticate
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        self.client.login(username="testuser", password="testpass123")
        
        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
    
    def test_attachments_tab_has_pagination(self):
        """Test that attachments tab template includes pagination"""
        response = self.client.get(reverse('project-attachments-tab', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        # Check that the response uses page_obj instead of attachments
        self.assertIn('page_obj', response.context)
    
    def test_attachments_pagination_10_per_page(self):
        """Test that pagination shows 10 items per page"""
        response = self.client.get(reverse('project-attachments-tab', args=[self.project.id]))
        self.assertEqual(response.status_code, 200)
        
        # Verify pagination is configured for 10 per page
        page_obj = response.context['page_obj']
        self.assertEqual(page_obj.paginator.per_page, 10)
