"""
Tests for First AID views and services.
"""

from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.urls import reverse
from core.models import User, Project, Organisation, Item, ItemType


class FirstAIDViewTestCase(TestCase):
    """Test cases for First AID views"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create and login test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.client.force_login(self.user)
        
        # Create test organisation
        self.org = Organisation.objects.create(
            name='Test Org',
            short='TEST'
        )
        
        # Create test project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project description',
            status='Working'
        )
        
        # Create test item type
        self.item_type = ItemType.objects.create(
            key="bug",
            name="Bug",
            description='Bug type'
        )
        
        # Create test item
        self.item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Test Item',
            description='Test description',
            
            status='Inbox'
        )
    
    def test_firstaid_home_view(self):
        """Test that the First AID home view loads"""
        url = reverse('firstaid:home')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'firstaid/home.html')
        self.assertIn('projects', response.context)
    
    def test_firstaid_home_with_project(self):
        """Test First AID home view with a selected project"""
        url = reverse('firstaid:home') + f'?project={self.project.id}'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'firstaid/home.html')
        self.assertIn('selected_project', response.context)
        self.assertEqual(response.context['selected_project'], self.project)
        self.assertIn('sources', response.context)
    
    def test_firstaid_sources_view(self):
        """Test the sources view returns sources for a project"""
        url = reverse('firstaid:sources') + f'?project_id={self.project.id}'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Items', response.content)  # Should show Items section
    
    @patch('firstaid.services.firstaid_service.build_extended_context')
    def test_firstaid_chat(self, mock_build_context):
        """Test the chat endpoint"""
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_build_context.return_value = mock_context
        
        url = reverse('firstaid:chat')
        data = {
            'question': 'What is this project about?',
            'project_id': self.project.id
        }
        
        response = self.client.post(
            url,
            data=data,
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn('answer', response_data)
        self.assertIn('sources', response_data)
    
    def test_create_issue_endpoint(self):
        """Test creating an issue from the First AID interface"""
        url = reverse('firstaid:create-issue')
        data = {
            'title': 'New Issue from First AID',
            'description': 'Test description',
            'project_id': self.project.id
        }
        
        response = self.client.post(
            url,
            data=data,
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        self.assertIn('item_id', response_data)
        self.assertIn('url', response_data)
        
        # Verify the item was created
        new_item = Item.objects.get(id=response_data['item_id'])
        self.assertEqual(new_item.title, 'New Issue from First AID')
        self.assertEqual(new_item.project, self.project)


class FirstAIDServiceTestCase(TestCase):
    """Test cases for First AID service"""
    
    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        # Create test organisation
        self.org = Organisation.objects.create(
            name='Test Org',
            short='TEST'
        )
        
        # Create test project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project description',
            status='Working'
        )
        
        # Create test item type
        self.item_type = ItemType.objects.create(
            key="bug",
            name="Bug",
            description='Bug type'
        )
        
        # Create test item
        self.item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Test Item',
            description='Test description',
            
            status='Inbox'
        )
    
    def test_get_project_sources(self):
        """Test retrieving project sources"""
        from firstaid.services.firstaid_service import FirstAIDService
        
        service = FirstAIDService()
        sources = service.get_project_sources(
            project_id=self.project.id,
            user=self.user
        )
        
        self.assertIn('items', sources)
        self.assertIn('github_issues', sources)
        self.assertIn('github_prs', sources)
        self.assertIn('attachments', sources)
        
        # Should have at least one item
        self.assertTrue(len(sources['items']) > 0)
        self.assertEqual(sources['items'][0].id, self.item.id)

