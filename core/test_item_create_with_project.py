"""
Tests for item creation with project pre-selection
"""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ProjectStatus
)


class ItemCreateWithProjectTestCase(TestCase):
    """Test cases for item creation with project query parameter"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation"
        )
        
        # Create test user
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            name="Test User"
        )
        
        # Create projects
        self.project1 = Project.objects.create(
            name="Project Alpha",
            status=ProjectStatus.WORKING
        )
        
        self.project2 = Project.objects.create(
            name="Project Beta",
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key="feature",
            name="Feature",
            is_active=True
        )
    
    def test_item_create_view_without_project_param(self):
        """Test item create view without project parameter"""
        response = self.client.get(reverse('item-create'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('projects', response.context)
        self.assertIsNone(response.context.get('default_project'))
    
    def test_item_create_view_with_valid_project_param(self):
        """Test item create view with valid project parameter"""
        response = self.client.get(
            reverse('item-create'),
            {'project': self.project1.id}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('default_project', response.context)
        self.assertEqual(response.context['default_project'], self.project1)
    
    def test_item_create_view_with_invalid_project_param(self):
        """Test item create view with invalid project parameter"""
        # Test with non-existent project ID
        response = self.client.get(
            reverse('item-create'),
            {'project': 99999}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context.get('default_project'))
        
        # Test with non-numeric project ID
        response = self.client.get(
            reverse('item-create'),
            {'project': 'invalid'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context.get('default_project'))
    
    def test_projects_page_has_new_item_button(self):
        """Test that projects page contains new item button for each project"""
        response = self.client.get(reverse('projects'))
        self.assertEqual(response.status_code, 200)
        
        # Check that the response contains links to item creation with project parameter
        content = response.content.decode('utf-8')
        self.assertIn(f'href="{reverse("item-create")}?project={self.project1.id}"', content)
        self.assertIn(f'href="{reverse("item-create")}?project={self.project2.id}"', content)
        
        # Check that the button text is present
        self.assertIn('New Item', content)
