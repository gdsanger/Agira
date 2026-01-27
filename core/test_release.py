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
