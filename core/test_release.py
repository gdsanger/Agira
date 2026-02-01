"""
Tests for Release model and related views
"""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Release, ReleaseType, ReleaseStatus,
    Project, ProjectStatus
)


class ReleaseModelTestCase(TestCase):
    """Test cases for Release model"""
    
    def setUp(self):
        """Set up test data"""
        # Create test project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
    
    def test_create_release_with_type(self):
        """Test creating a release with a type"""
        release = Release.objects.create(
            project=self.project,
            name="Version 1.0",
            version="1.0.0",
            type=ReleaseType.MAJOR,
            status=ReleaseStatus.PLANNED
        )
        
        self.assertEqual(release.type, ReleaseType.MAJOR)
        self.assertEqual(release.version, "1.0.0")
        self.assertEqual(release.project, self.project)
    
    def test_create_release_without_type(self):
        """Test creating a release without a type (backward compatibility)"""
        release = Release.objects.create(
            project=self.project,
            name="Version 2.0",
            version="2.0.0",
            status=ReleaseStatus.PLANNED
        )
        
        self.assertIsNone(release.type)
        self.assertEqual(release.version, "2.0.0")
    
    def test_release_type_choices(self):
        """Test all release type choices"""
        for choice in [ReleaseType.MAJOR, ReleaseType.MINOR, ReleaseType.HOTFIX, ReleaseType.SECURITYFIX]:
            release = Release.objects.create(
                project=self.project,
                name=f"Release {choice}",
                version=f"{choice}-1.0",
                type=choice,
                status=ReleaseStatus.PLANNED
            )
            self.assertEqual(release.type, choice)
    
    def test_release_str_representation(self):
        """Test string representation of release"""
        release = Release.objects.create(
            project=self.project,
            name="Test Release",
            version="1.0.0",
            type=ReleaseType.MINOR
        )
        
        expected = f"{self.project.name} - 1.0.0"
        self.assertEqual(str(release), expected)


class ReleaseViewTestCase(TestCase):
    """Test cases for Release views"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test user
        from core.models import User
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        # Log in the test user
        self.client.login(username='testuser', password='testpass123')
        
        # Create test project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
    
    def test_add_release_with_type(self):
        """Test adding a release with a type via view"""
        url = reverse('project-add-release', args=[self.project.id])
        data = {
            'name': 'Release 1.0',
            'version': '1.0.0',
            'type': 'Major'
        }
        
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        
        # Verify release was created
        release = Release.objects.get(version='1.0.0')
        self.assertEqual(release.type, ReleaseType.MAJOR)
        self.assertEqual(release.name, 'Release 1.0')
    
    def test_add_release_without_type(self):
        """Test adding a release without a type via view"""
        url = reverse('project-add-release', args=[self.project.id])
        data = {
            'name': 'Release 2.0',
            'version': '2.0.0'
        }
        
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        
        # Verify release was created without type
        release = Release.objects.get(version='2.0.0')
        self.assertIsNone(release.type)
    
    def test_add_release_missing_required_fields(self):
        """Test adding a release without required fields"""
        url = reverse('project-add-release', args=[self.project.id])
        data = {
            'name': 'Incomplete Release'
            # Missing version
        }
        
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('required', response_data['error'].lower())
    
    def test_add_release_invalid_type(self):
        """Test adding a release with an invalid type"""
        url = reverse('project-add-release', args=[self.project.id])
        data = {
            'name': 'Invalid Release',
            'version': '3.0.0',
            'type': 'InvalidType'
        }
        
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('invalid', response_data['error'].lower())
    
    def test_add_release_with_planned_date(self):
        """Test adding a release with a planned date"""
        from datetime import date
        
        url = reverse('project-add-release', args=[self.project.id])
        data = {
            'name': 'Release with Date',
            'version': '4.0.0',
            'planned_date': '2026-03-15'
        }
        
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        
        # Verify planned_date was saved correctly
        release = Release.objects.get(version='4.0.0')
        self.assertEqual(release.planned_date, date(2026, 3, 15))
    
    def test_update_release_with_planned_date(self):
        """Test updating a release with a planned date"""
        from datetime import date
        
        # Create a release
        release = Release.objects.create(
            project=self.project,
            name="Release to Update",
            version="5.0.0"
        )
        
        # Update the release
        url = reverse('project-update-release', args=[self.project.id, release.id])
        data = {
            'name': 'Updated Release',
            'version': '5.1.0',
            'planned_date': '2026-04-20',
            'status': 'Working'
        }
        
        response = self.client.post(url, data)
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        
        # Verify updates
        release.refresh_from_db()
        self.assertEqual(release.name, 'Updated Release')
        self.assertEqual(release.version, '5.1.0')
        self.assertEqual(release.planned_date, date(2026, 4, 20))
        self.assertEqual(release.status, ReleaseStatus.WORKING)
    
    def test_create_change_from_release(self):
        """Test creating a Change from a Release"""
        from datetime import date
        from core.models import Change, ChangeStatus
        
        # Create a release with planned_date
        release = Release.objects.create(
            project=self.project,
            name="Release for Change",
            version="6.0.0",
            planned_date=date(2026, 5, 1)
        )
        
        # Create change from release
        url = reverse('release-create-change', args=[release.id])
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        
        # Verify change was created
        change = Change.objects.get(id=response_data['change_id'])
        self.assertEqual(change.release, release)
        self.assertEqual(change.project, self.project)
        self.assertEqual(change.planned_date, date(2026, 5, 1))
        self.assertEqual(change.status, ChangeStatus.DRAFT)
        self.assertIn(release.name, change.title)
    
    def test_create_change_duplicate_prevention(self):
        """Test that creating a second Change for the same Release fails"""
        from datetime import date
        from core.models import Change, ChangeStatus
        
        # Create a release
        release = Release.objects.create(
            project=self.project,
            name="Release for Duplicate Test",
            version="7.0.0",
            planned_date=date(2026, 6, 1)
        )
        
        # Create first change
        url = reverse('release-create-change', args=[release.id])
        response = self.client.post(url)
        self.assertEqual(response.status_code, 200)
        
        # Try to create second change - should fail
        response2 = self.client.post(url)
        self.assertEqual(response2.status_code, 400)
        response_data = response2.json()
        self.assertFalse(response_data['success'])
        self.assertIn('already exists', response_data['error'].lower())
    
    def test_get_primary_change(self):
        """Test Release.get_primary_change() method"""
        from datetime import date
        from core.models import Change, ChangeStatus
        
        # Create a release
        release = Release.objects.create(
            project=self.project,
            name="Release with Change",
            version="8.0.0"
        )
        
        # Initially no change
        self.assertIsNone(release.get_primary_change())
        
        # Create a change
        change = Change.objects.create(
            project=self.project,
            title="Test Change",
            release=release,
            status=ChangeStatus.DRAFT
        )
        
        # Now should return the change
        self.assertEqual(release.get_primary_change(), change)
