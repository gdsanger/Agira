"""
Tests for CustomGPT Actions API endpoints.

This module tests the API endpoints for CustomGPT Actions including:
- Authentication via x-api-secret header
- Projects CRUD operations (without Delete)
- Items CRUD operations (without Delete)
- Status filtering (open items = status != Closed)
- RAG context endpoint
"""
import json
import os
from django.test import TestCase, Client
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ProjectStatus,
    ItemType, Item, ItemStatus
)

User = get_user_model()


class CustomGPTAPIAuthTest(TestCase):
    """Test authentication for CustomGPT API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        # Set API secret for tests
        os.environ['CUSTOMGPT_API_SECRET'] = 'test-secret-123'
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description',
            status=ProjectStatus.WORKING
        )
        
    def tearDown(self):
        """Clean up after tests."""
        # Remove test environment variable
        if 'CUSTOMGPT_API_SECRET' in os.environ:
            del os.environ['CUSTOMGPT_API_SECRET']
    
    def test_api_requires_secret(self):
        """Test that API endpoints require x-api-secret header."""
        client = Client()
        
        # Request without header should return 401
        response = client.get('/api/customgpt/projects')
        self.assertEqual(response.status_code, 401)
        data = json.loads(response.content)
        self.assertIn('error', data)
        self.assertIn('Unauthorized', data['error'])
    
    def test_api_rejects_invalid_secret(self):
        """Test that API rejects invalid secrets."""
        client = Client()
        
        # Request with wrong secret should return 401
        response = client.get(
            '/api/customgpt/projects',
            HTTP_X_API_SECRET='wrong-secret'
        )
        self.assertEqual(response.status_code, 401)
    
    def test_api_accepts_valid_secret(self):
        """Test that API accepts valid secrets."""
        client = Client()
        
        # Request with correct secret should succeed
        response = client.get(
            '/api/customgpt/projects',
            HTTP_X_API_SECRET='test-secret-123'
        )
        self.assertEqual(response.status_code, 200)


class CustomGPTProjectsAPITest(TestCase):
    """Test Projects API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        # Set API secret for tests
        os.environ['CUSTOMGPT_API_SECRET'] = 'test-secret-123'
        
        self.client = Client()
        self.headers = {'HTTP_X_API_SECRET': 'test-secret-123'}
        
        # Create projects
        self.project1 = Project.objects.create(
            name='Project 1',
            description='Description 1',
            status=ProjectStatus.WORKING
        )
        self.project2 = Project.objects.create(
            name='Project 2',
            description='Description 2',
            status=ProjectStatus.NEW
        )
        
    def tearDown(self):
        """Clean up after tests."""
        if 'CUSTOMGPT_API_SECRET' in os.environ:
            del os.environ['CUSTOMGPT_API_SECRET']
    
    def test_list_projects(self):
        """Test GET /api/customgpt/projects."""
        response = self.client.get('/api/customgpt/projects', **self.headers)
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['name'], 'Project 1')
        self.assertEqual(data[1]['name'], 'Project 2')
    
    def test_get_project(self):
        """Test GET /api/customgpt/projects/{id}."""
        response = self.client.get(
            f'/api/customgpt/projects/{self.project1.id}',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertEqual(data['id'], self.project1.id)
        self.assertEqual(data['name'], 'Project 1')
        self.assertEqual(data['description'], 'Description 1')
        self.assertEqual(data['status'], ProjectStatus.WORKING)
    
    def test_get_project_not_found(self):
        """Test GET /api/customgpt/projects/{id} with invalid ID."""
        response = self.client.get(
            '/api/customgpt/projects/99999',
            **self.headers
        )
        self.assertEqual(response.status_code, 404)
    
    def test_update_project_put(self):
        """Test PUT /api/customgpt/projects/{id}."""
        update_data = {
            'name': 'Updated Project',
            'description': 'Updated description',
            'status': ProjectStatus.CANCELED
        }
        
        response = self.client.put(
            f'/api/customgpt/projects/{self.project1.id}',
            data=json.dumps(update_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertEqual(data['name'], 'Updated Project')
        self.assertEqual(data['description'], 'Updated description')
        self.assertEqual(data['status'], ProjectStatus.CANCELED)
        
        # Verify database was updated
        self.project1.refresh_from_db()
        self.assertEqual(self.project1.name, 'Updated Project')
    
    def test_update_project_patch(self):
        """Test PATCH /api/customgpt/projects/{id}."""
        update_data = {
            'description': 'Patched description'
        }
        
        response = self.client.patch(
            f'/api/customgpt/projects/{self.project1.id}',
            data=json.dumps(update_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertEqual(data['description'], 'Patched description')
        # Name should remain unchanged
        self.assertEqual(data['name'], 'Project 1')


class CustomGPTItemsAPITest(TestCase):
    """Test Items API endpoints."""
    
    def setUp(self):
        """Set up test data."""
        # Set API secret for tests
        os.environ['CUSTOMGPT_API_SECRET'] = 'test-secret-123'
        
        self.client = Client()
        self.headers = {'HTTP_X_API_SECRET': 'test-secret-123'}
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description',
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            
            description='A bug report'
        )
        
        # Create items with different statuses
        self.open_item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Open Item',
            description='This is open',
            status=ItemStatus.WORKING
        )
        
        self.closed_item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Closed Item',
            description='This is closed',
            status=ItemStatus.CLOSED
        )
        
    def tearDown(self):
        """Clean up after tests."""
        if 'CUSTOMGPT_API_SECRET' in os.environ:
            del os.environ['CUSTOMGPT_API_SECRET']
    
    def test_list_items_excludes_closed(self):
        """Test GET /api/customgpt/items excludes closed items."""
        response = self.client.get('/api/customgpt/items', **self.headers)
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        # Should only return open item, not closed
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], self.open_item.id)
        self.assertEqual(data[0]['status'], ItemStatus.WORKING)
    
    def test_get_item(self):
        """Test GET /api/customgpt/items/{id}."""
        response = self.client.get(
            f'/api/customgpt/items/{self.open_item.id}',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertEqual(data['id'], self.open_item.id)
        self.assertEqual(data['title'], 'Open Item')
    
    def test_get_item_not_found(self):
        """Test GET /api/customgpt/items/{id} with invalid ID."""
        response = self.client.get(
            '/api/customgpt/items/99999',
            **self.headers
        )
        self.assertEqual(response.status_code, 404)
    
    def test_update_item_put(self):
        """Test PUT /api/customgpt/items/{id}."""
        update_data = {
            'title': 'Updated Item',
            'description': 'Updated description',
            'status': ItemStatus.TESTING
        }
        
        response = self.client.put(
            f'/api/customgpt/items/{self.open_item.id}',
            data=json.dumps(update_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertEqual(data['title'], 'Updated Item')
        self.assertEqual(data['status'], ItemStatus.TESTING)
    
    def test_update_item_patch(self):
        """Test PATCH /api/customgpt/items/{id}."""
        update_data = {
            'status': ItemStatus.BACKLOG
        }
        
        response = self.client.patch(
            f'/api/customgpt/items/{self.open_item.id}',
            data=json.dumps(update_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        self.assertEqual(data['status'], ItemStatus.BACKLOG)
        # Title should remain unchanged
        self.assertEqual(data['title'], 'Open Item')
    
    def test_create_item(self):
        """Test POST /api/customgpt/projects/{id}/items."""
        create_data = {
            'title': 'New Item',
            'description': 'New description',
            'type_id': self.item_type.id,
            'status': ItemStatus.INBOX
        }
        
        response = self.client.post(
            f'/api/customgpt/projects/{self.project.id}/items',
            data=json.dumps(create_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 201)
        
        data = json.loads(response.content)
        self.assertEqual(data['title'], 'New Item')
        self.assertEqual(data['project_id'], self.project.id)
        self.assertEqual(data['status'], ItemStatus.INBOX)
        
        # Verify item was created in database
        item = Item.objects.get(id=data['id'])
        self.assertEqual(item.title, 'New Item')
    
    def test_create_item_missing_required_field(self):
        """Test POST /api/customgpt/projects/{id}/items with missing required field."""
        create_data = {
            'description': 'New description',
            # Missing title and type_id
        }
        
        response = self.client.post(
            f'/api/customgpt/projects/{self.project.id}/items',
            data=json.dumps(create_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 400)
    
    def test_get_project_open_items(self):
        """Test GET /api/customgpt/projects/{id}/open-items excludes closed items."""
        response = self.client.get(
            f'/api/customgpt/projects/{self.project.id}/open-items',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        # Should only return open item, not closed
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], self.open_item.id)


class CustomGPTItemContextAPITest(TestCase):
    """Test Item Context API endpoint."""
    
    def setUp(self):
        """Set up test data."""
        # Set API secret for tests
        os.environ['CUSTOMGPT_API_SECRET'] = 'test-secret-123'
        
        self.client = Client()
        self.headers = {'HTTP_X_API_SECRET': 'test-secret-123'}
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description',
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            
            description='A bug report'
        )
        
        # Create item
        self.item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Test Item',
            description='Test description',
            status=ItemStatus.WORKING
        )
        
    def tearDown(self):
        """Clean up after tests."""
        if 'CUSTOMGPT_API_SECRET' in os.environ:
            del os.environ['CUSTOMGPT_API_SECRET']
    
    def test_get_item_context(self):
        """Test GET /api/customgpt/items/{id}/context returns RAG context."""
        response = self.client.get(
            f'/api/customgpt/items/{self.item.id}/context',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)
        
        data = json.loads(response.content)
        
        # Verify RAG context structure
        self.assertIn('query', data)
        self.assertIn('alpha', data)
        self.assertIn('summary', data)
        self.assertIn('items', data)
        self.assertIn('stats', data)
        
        # Query should include item title and description
        self.assertIn('Test Item', data['query'])
        
        # Items should be a list (may be empty if Weaviate not configured)
        self.assertIsInstance(data['items'], list)
    
    def test_get_item_context_not_found(self):
        """Test GET /api/customgpt/items/{id}/context with invalid item ID."""
        response = self.client.get(
            '/api/customgpt/items/99999/context',
            **self.headers
        )
        self.assertEqual(response.status_code, 404)
