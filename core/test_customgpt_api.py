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
from unittest.mock import patch
from django.test import TestCase, Client
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ProjectStatus,
    ItemType, Item, ItemStatus, UserRole,
    ExternalIssueMapping, ExternalIssueKind, GitHubConfiguration,
)
from core.services.integrations.errors import IntegrationPermanentError
from core.services.rag.models import RAGContextObject
from core.services.rag.extended_service import ExtendedRAGContext

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
        self.assertEqual(data['status'], ItemStatus.WORKING)
    
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
    
    def test_update_item_sets_solution_description(self):
        """Test PATCH .../items/{id} writes the 'Solution' field."""
        response = self.client.patch(
            f'/api/customgpt/items/{self.open_item.id}',
            data=json.dumps({'solution_description': 'Restarted the worker.'}),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertEqual(data['solution_description'], 'Restarted the worker.')

        self.open_item.refresh_from_db()
        self.assertEqual(self.open_item.solution_description, 'Restarted the worker.')

    def test_update_item_sets_pr_description(self):
        """Test PATCH .../items/{id} writes the 'PR-Description' field."""
        response = self.client.patch(
            f'/api/customgpt/items/{self.open_item.id}',
            data=json.dumps({'pr_description': '## Summary\n\nFixed the bug.'}),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertEqual(data['pr_description'], '## Summary\n\nFixed the bug.')

        self.open_item.refresh_from_db()
        self.assertEqual(self.open_item.pr_description, '## Summary\n\nFixed the bug.')

    def test_update_item_not_found(self):
        """Test PATCH .../items/{id} with an invalid item id fails cleanly."""
        response = self.client.patch(
            '/api/customgpt/items/99999',
            data=json.dumps({'solution_description': 'x'}),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.content)
        self.assertIn('error', data)

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
        self.assertEqual(data[0]['status'], ItemStatus.WORKING)

    def test_create_item_with_parent_id(self):
        """Test POST .../items sets the parent when parent_id is given."""
        create_data = {
            'title': 'Child Item',
            'type_id': self.item_type.id,
            'parent_id': self.open_item.id,
        }
        response = self.client.post(
            f'/api/customgpt/projects/{self.project.id}/items',
            data=json.dumps(create_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 201)

        data = json.loads(response.content)
        self.assertEqual(data['parent_id'], self.open_item.id)

        item = Item.objects.get(id=data['id'])
        self.assertEqual(item.parent_id, self.open_item.id)

    def test_create_item_without_parent_id(self):
        """Test POST .../items leaves parent unset when parent_id is omitted."""
        create_data = {
            'title': 'No Parent Item',
            'type_id': self.item_type.id,
        }
        response = self.client.post(
            f'/api/customgpt/projects/{self.project.id}/items',
            data=json.dumps(create_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 201)

        data = json.loads(response.content)
        self.assertIsNone(data['parent_id'])

    def test_create_item_with_null_parent_id(self):
        """Test POST .../items with parent_id explicitly null creates without a parent."""
        create_data = {
            'title': 'Null Parent Item',
            'type_id': self.item_type.id,
            'parent_id': None,
        }
        response = self.client.post(
            f'/api/customgpt/projects/{self.project.id}/items',
            data=json.dumps(create_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 201)

        data = json.loads(response.content)
        self.assertIsNone(data['parent_id'])

    def test_create_item_with_invalid_parent_id(self):
        """Test POST .../items rejects a non-existent parent_id."""
        create_data = {
            'title': 'Bad Parent Item',
            'type_id': self.item_type.id,
            'parent_id': 999999,
        }
        response = self.client.post(
            f'/api/customgpt/projects/{self.project.id}/items',
            data=json.dumps(create_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_update_item_sets_parent(self):
        """Test PATCH .../items/{id} sets the parent when parent_id is given."""
        update_data = {'parent_id': self.open_item.id}
        response = self.client.patch(
            f'/api/customgpt/items/{self.closed_item.id}',
            data=json.dumps(update_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertEqual(data['parent_id'], self.open_item.id)

    def test_update_item_changes_parent(self):
        """Test PATCH .../items/{id} changes an existing parent to a new one."""
        other_item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Other Item',
            status=ItemStatus.WORKING,
        )
        self.closed_item.parent = self.open_item
        self.closed_item.save()

        update_data = {'parent_id': other_item.id}
        response = self.client.patch(
            f'/api/customgpt/items/{self.closed_item.id}',
            data=json.dumps(update_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertEqual(data['parent_id'], other_item.id)

    def test_update_item_removes_parent_with_null(self):
        """Test PATCH .../items/{id} removes the parent when parent_id is null."""
        self.closed_item.parent = self.open_item
        self.closed_item.save()

        update_data = {'parent_id': None}
        response = self.client.patch(
            f'/api/customgpt/items/{self.closed_item.id}',
            data=json.dumps(update_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertIsNone(data['parent_id'])

    def test_update_item_without_parent_id_leaves_parent_unchanged(self):
        """Test PATCH .../items/{id} without parent_id does not touch the parent."""
        self.closed_item.parent = self.open_item
        self.closed_item.save()

        update_data = {'title': 'Renamed, parent untouched'}
        response = self.client.patch(
            f'/api/customgpt/items/{self.closed_item.id}',
            data=json.dumps(update_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertEqual(data['parent_id'], self.open_item.id)

    def test_update_item_with_invalid_parent_id(self):
        """Test PATCH .../items/{id} rejects a non-existent parent_id."""
        update_data = {'parent_id': 999999}
        response = self.client.patch(
            f'/api/customgpt/items/{self.open_item.id}',
            data=json.dumps(update_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 400)

    def test_update_item_rejects_self_reference(self):
        """Test PATCH .../items/{id} rejects an item as its own parent."""
        update_data = {'parent_id': self.open_item.id}
        response = self.client.patch(
            f'/api/customgpt/items/{self.open_item.id}',
            data=json.dumps(update_data),
            content_type='application/json',
            **self.headers
        )
        self.assertEqual(response.status_code, 400)

        self.open_item.refresh_from_db()
        self.assertIsNone(self.open_item.parent)


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
    
    def test_get_item_context_includes_status_per_item(self):
        """Related items in the RAG context must expose their status directly."""
        related_item = RAGContextObject(
            object_type='item',
            object_id='42',
            title='Related Item',
            content='Related content',
            source='agira',
            relevance_score=0.9,
            link='/items/42/',
            updated_at='2024-01-01',
            status=ItemStatus.REVIEW,
        )
        stub_context = ExtendedRAGContext(
            query='Test Item',
            optimized_query=None,
            layer_a=[],
            layer_b=[related_item],
            layer_c=[],
            all_items=[related_item],
            summary='Found 1 item',
            stats={'total': 1},
        )

        with patch('core.views_api.build_extended_context', return_value=stub_context):
            response = self.client.get(
                f'/api/customgpt/items/{self.item.id}/context',
                **self.headers
            )
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['object_id'], '42')
        self.assertEqual(data['items'][0]['status'], ItemStatus.REVIEW)
        # Same data must be reachable via the richer layer_b field too
        self.assertEqual(data['layer_b'][0]['status'], ItemStatus.REVIEW)

    def test_get_item_context_not_found(self):
        """Test GET /api/customgpt/items/{id}/context with invalid item ID."""
        response = self.client.get(
            '/api/customgpt/items/99999/context',
            **self.headers
        )
        self.assertEqual(response.status_code, 404)


class MCPResponsibleTests(TestCase):
    """Tests for the per-user MCP token -> responsible attribution on create."""

    def setUp(self):
        os.environ['CUSTOMGPT_API_SECRET'] = 'test-secret-123'
        self.client = Client()
        self.headers = {'HTTP_X_API_SECRET': 'test-secret-123'}

        self.project = Project.objects.create(
            name='MCP Project', description='', status=ProjectStatus.WORKING
        )
        self.item_type = ItemType.objects.create(
            key='task', name='Task', description='A task'
        )

        # An Agent user (allowed as responsible) with an MCP token.
        self.agent = User.objects.create_user(
            username='agent1', email='agent1@example.com', name='Agent One',
            role=UserRole.AGENT, mcp_token='agent-token-123',
        )
        # A non-Agent user (not allowed as responsible) with an MCP token.
        self.plain = User.objects.create_user(
            username='user1', email='user1@example.com', name='User One',
            role=UserRole.USER, mcp_token='user-token-123',
        )

    def tearDown(self):
        if 'CUSTOMGPT_API_SECRET' in os.environ:
            del os.environ['CUSTOMGPT_API_SECRET']

    def _create(self, user_token=None):
        headers = dict(self.headers)
        if user_token is not None:
            headers['HTTP_X_AGIRA_USER_TOKEN'] = user_token
        return self.client.post(
            f'/api/customgpt/projects/{self.project.id}/items',
            data=json.dumps({'title': 'Via MCP', 'type_id': self.item_type.id}),
            content_type='application/json',
            **headers,
        )

    def test_agent_token_sets_responsible(self):
        response = self._create(user_token='agent-token-123')
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.content)
        self.assertEqual(data['responsible_id'], self.agent.id)

    def test_non_agent_token_rejected(self):
        response = self._create(user_token='user-token-123')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Agent', json.loads(response.content)['error'])
        self.assertFalse(Item.objects.filter(title='Via MCP').exists())

    def test_no_token_creates_without_responsible(self):
        response = self._create(user_token=None)
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.content)
        self.assertIsNone(data['responsible_id'])

    def test_unknown_token_creates_without_responsible(self):
        response = self._create(user_token='does-not-exist')
        self.assertEqual(response.status_code, 201)
        data = json.loads(response.content)
        self.assertIsNone(data['responsible_id'])


class CustomGPTItemLinkGitHubPRAPITest(TestCase):
    """Test POST /api/customgpt/items/{id}/github-pr (PR -> ExternalIssueMapping linking)."""

    def setUp(self):
        os.environ['CUSTOMGPT_API_SECRET'] = 'test-secret-123'
        self.client = Client()
        self.headers = {'HTTP_X_API_SECRET': 'test-secret-123'}

        self.config = GitHubConfiguration.load()
        self.config.enable_github = True
        self.config.github_token = 'test_token_123'
        self.config.github_api_base_url = 'https://api.github.com'
        self.config.save()

        self.project = Project.objects.create(
            name='Test Project',
            github_owner='testowner',
            github_repo='testrepo',
        )
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Item with a PR',
            status=ItemStatus.WORKING,
        )

    def tearDown(self):
        if 'CUSTOMGPT_API_SECRET' in os.environ:
            del os.environ['CUSTOMGPT_API_SECRET']

    def _link(self, item_id, pr_number):
        return self.client.post(
            f'/api/customgpt/items/{item_id}/github-pr',
            data=json.dumps({'pr_number': pr_number}),
            content_type='application/json',
            **self.headers,
        )

    @patch('core.services.github.client.GitHubClient.get_pr')
    def test_link_creates_new_mapping(self, mock_get_pr):
        mock_get_pr.return_value = {
            'id': 55501,
            'number': 42,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/pull/42',
        }

        response = self._link(self.item.id, 42)
        self.assertEqual(response.status_code, 201)

        data = json.loads(response.content)
        self.assertEqual(data['item_id'], self.item.id)
        self.assertTrue(data['created'])
        self.assertEqual(data['mapping']['number'], 42)
        self.assertEqual(data['mapping']['github_id'], 55501)
        self.assertEqual(data['mapping']['kind'], ExternalIssueKind.PR)
        self.assertEqual(data['mapping']['state'], 'open')

        self.assertEqual(ExternalIssueMapping.objects.count(), 1)
        mapping = ExternalIssueMapping.objects.get()
        self.assertEqual(mapping.item_id, self.item.id)
        self.assertEqual(mapping.github_id, 55501)

    @patch('core.services.github.client.GitHubClient.get_pr')
    def test_link_same_pr_twice_is_idempotent(self, mock_get_pr):
        mock_get_pr.return_value = {
            'id': 55502,
            'number': 43,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/pull/43',
        }

        first = self._link(self.item.id, 43)
        second = self._link(self.item.id, 43)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertFalse(json.loads(second.content)['created'])

        # No duplicate rows for the same item/PR.
        self.assertEqual(ExternalIssueMapping.objects.count(), 1)
        self.assertEqual(
            json.loads(first.content)['mapping']['id'],
            json.loads(second.content)['mapping']['id'],
        )

    @patch('core.services.github.client.GitHubClient.get_pr')
    def test_link_updates_existing_mapping_deterministically(self, mock_get_pr):
        existing = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=55503,
            number=44,
            kind=ExternalIssueKind.PR,
            state='open',
            html_url='https://github.com/testowner/testrepo/pull/44',
        )

        mock_get_pr.return_value = {
            'id': 55503,
            'number': 44,
            'state': 'closed',
            'merged_at': '2026-08-01T10:00:00Z',
            'html_url': 'https://github.com/testowner/testrepo/pull/44',
        }

        response = self._link(self.item.id, 44)
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.content)
        self.assertFalse(data['created'])
        self.assertEqual(data['mapping']['id'], existing.id)
        self.assertEqual(data['mapping']['state'], 'merged')

        # The same row was updated in place, not a second one created.
        self.assertEqual(ExternalIssueMapping.objects.count(), 1)
        existing.refresh_from_db()
        self.assertEqual(existing.state, 'merged')

    def test_link_item_not_found(self):
        response = self._link(999999, 1)
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', json.loads(response.content))

    def test_link_missing_pr_number(self):
        response = self.client.post(
            f'/api/customgpt/items/{self.item.id}/github-pr',
            data=json.dumps({}),
            content_type='application/json',
            **self.headers,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', json.loads(response.content))
        self.assertEqual(ExternalIssueMapping.objects.count(), 0)

    def test_link_invalid_pr_number(self):
        response = self._link(self.item.id, 'not-a-number')
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', json.loads(response.content))

    @patch('core.services.github.client.GitHubClient.get_pr')
    def test_link_unresolvable_pr_returns_clean_error(self, mock_get_pr):
        mock_get_pr.side_effect = IntegrationPermanentError(
            "Client error (HTTP 404): Not Found"
        )

        response = self._link(self.item.id, 9999)
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertIn('error', data)
        self.assertIn('9999', data['error'])
        self.assertEqual(ExternalIssueMapping.objects.count(), 0)

    def test_link_project_without_github_repo_configured(self):
        project = Project.objects.create(name='No GitHub Project')
        item = Item.objects.create(
            project=project,
            type=self.item_type,
            title='Unconfigured item',
        )

        response = self._link(item.id, 1)
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', json.loads(response.content))
