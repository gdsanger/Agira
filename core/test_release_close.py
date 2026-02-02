"""
Tests for release close functionality
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import Project, ProjectStatus, Release, ReleaseStatus, User


class ReleaseCloseTestCase(TestCase):
    """Test cases for release close functionality"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
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
            name="Release 1.0",
            version="1.0.0",
            status=ReleaseStatus.PLANNED
        )
    
    def test_close_release_success(self):
        """Test successfully closing a release"""
        url = reverse('project-close-release', args=[self.project.id, self.release.id])
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        self.assertEqual(response_data['message'], 'Release closed successfully')
        
        # Check database
        self.release.refresh_from_db()
        self.assertEqual(self.release.status, ReleaseStatus.CLOSED)
        self.assertIsNotNone(self.release.closed_at)
        self.assertEqual(self.release.closed_by, self.user)
    
    def test_close_already_closed_release(self):
        """Test closing an already closed release returns error"""
        # Set release to closed
        self.release.status = ReleaseStatus.CLOSED
        self.release.closed_at = timezone.now()
        self.release.closed_by = self.user
        self.release.save()
        
        url = reverse('project-close-release', args=[self.project.id, self.release.id])
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertEqual(response_data['error'], 'Release is already closed')
    
    def test_close_release_unauthorized(self):
        """Test closing a release when not logged in"""
        self.client.logout()
        
        url = reverse('project-close-release', args=[self.project.id, self.release.id])
        response = self.client.post(url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_close_nonexistent_release(self):
        """Test closing a non-existent release returns 404"""
        url = reverse('project-close-release', args=[self.project.id, 99999])
        response = self.client.post(url)
        
        # Should return 404
        self.assertEqual(response.status_code, 404)
