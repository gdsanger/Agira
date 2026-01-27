"""
Tests for project detail view tab persistence
"""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import Project, ProjectStatus, User


class ProjectDetailTabPersistenceTestCase(TestCase):
    """Test cases for project detail view tab persistence"""
    
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
        
        # Create projects
        self.project1 = Project.objects.create(
            name="Project Alpha",
            status=ProjectStatus.WORKING
        )
        
        self.project2 = Project.objects.create(
            name="Project Beta",
            status=ProjectStatus.WORKING
        )
    
    def test_project_detail_view_loads(self):
        """Test that project detail view loads successfully"""
        response = self.client.get(reverse('project-detail', args=[self.project1.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('project', response.context)
        self.assertEqual(response.context['project'].id, self.project1.id)
    
    def test_project_detail_has_tabs(self):
        """Test that project detail view contains tab structure"""
        response = self.client.get(reverse('project-detail', args=[self.project1.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check for tab navigation
        self.assertIn('id="projectTabs"', content)
        
        # Check for individual tabs
        self.assertIn('id="items-tab"', content)
        self.assertIn('id="nodes-tab"', content)
        self.assertIn('id="releases-tab"', content)
        self.assertIn('id="clients-tab"', content)
        self.assertIn('id="attachments-tab"', content)
    
    def test_project_detail_has_tab_persistence_script(self):
        """Test that project detail view includes tab persistence JavaScript"""
        response = self.client.get(reverse('project-detail', args=[self.project1.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check for tab persistence script elements
        self.assertIn('projectDetail.activeTab', content)
        self.assertIn('localStorage.getItem', content)
        self.assertIn('localStorage.setItem', content)
        self.assertIn('restoreActiveTab', content)
        self.assertIn('saveActiveTab', content)
    
    def test_project_detail_has_project_specific_storage_key(self):
        """Test that storage key is project-specific"""
        response = self.client.get(reverse('project-detail', args=[self.project1.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check that project ID is used in storage key
        self.assertIn(f'projectDetail.activeTab.{self.project1.id}', content)
    
    def test_different_projects_have_different_storage_keys(self):
        """Test that different projects have different storage keys"""
        response1 = self.client.get(reverse('project-detail', args=[self.project1.id]))
        response2 = self.client.get(reverse('project-detail', args=[self.project2.id]))
        
        content1 = response1.content.decode('utf-8')
        content2 = response2.content.decode('utf-8')
        
        # Check that each project has its own storage key
        self.assertIn(f'projectDetail.activeTab.{self.project1.id}', content1)
        self.assertIn(f'projectDetail.activeTab.{self.project2.id}', content2)
        
        # And they are different
        self.assertNotEqual(
            f'projectDetail.activeTab.{self.project1.id}',
            f'projectDetail.activeTab.{self.project2.id}'
        )
    
    def test_tab_persistence_handles_bootstrap_events(self):
        """Test that tab persistence listens to Bootstrap tab events"""
        response = self.client.get(reverse('project-detail', args=[self.project1.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check for Bootstrap tab event listeners
        self.assertIn('shown.bs.tab', content)
        self.assertIn('addEventListener', content)
    
    def test_tab_persistence_uses_bootstrap_tab_api(self):
        """Test that tab restoration uses Bootstrap Tab API"""
        response = self.client.get(reverse('project-detail', args=[self.project1.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check for Bootstrap Tab API usage
        self.assertIn('new bootstrap.Tab', content)
        self.assertIn('tab.show()', content)
    
    def test_tab_persistence_has_error_handling(self):
        """Test that tab persistence includes error handling for localStorage"""
        response = self.client.get(reverse('project-detail', args=[self.project1.id]))
        self.assertEqual(response.status_code, 200)
        
        content = response.content.decode('utf-8')
        
        # Check for try-catch blocks
        self.assertIn('try {', content)
        self.assertIn('catch (e)', content)
