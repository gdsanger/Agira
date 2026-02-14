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
    
    def test_firstaid_home_with_github_mappings(self):
        """Test First AID home view with a project that has GitHub mappings"""
        from core.models import ExternalIssueMapping, ExternalIssueKind
        
        # Create GitHub issue and PR mappings
        ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=12345,
            number=123,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/test/repo/issues/123'
        )
        
        ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=67890,
            number=456,
            kind=ExternalIssueKind.PR,
            state='open',
            html_url='https://github.com/test/repo/pull/456'
        )
        
        url = reverse('firstaid:home') + f'?project={self.project.id}'
        response = self.client.get(url)
        
        # Should return 200, not 500
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'firstaid/home.html')
        self.assertIn('sources', response.context)
        
        # Verify sources contain GitHub issues and PRs
        sources = response.context['sources']
        self.assertGreater(len(sources['github_issues']), 0)
        self.assertGreater(len(sources['github_prs']), 0)
    
    def test_firstaid_sources_view(self):
        """Test the sources view returns sources for a project"""
        url = reverse('firstaid:sources') + f'?project_id={self.project.id}'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Items', response.content)  # Should show Items section
    
    @patch('firstaid.services.firstaid_service.build_extended_context')
    @patch('firstaid.services.firstaid_service.AgentService.execute_agent')
    def test_firstaid_chat_uses_question_answering_agent(self, mock_execute_agent, mock_build_context):
        """Test that chat uses question-answering-agent by default"""
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_context.layer_a = []
        mock_context.layer_b = []
        mock_context.layer_c = []
        mock_build_context.return_value = mock_context
        
        # Mock agent execution
        mock_execute_agent.return_value = "This is a test answer from the agent."
        
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
        
        # Verify agent was called with correct parameters
        self.assertEqual(mock_execute_agent.call_count, 1)
        call_kwargs = mock_execute_agent.call_args[1]
        self.assertEqual(call_kwargs['filename'], 'question-answering-agent.yml')
        self.assertIn('What is this project about?', call_kwargs['input_text'])
        
        # Verify response contains agent answer
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertEqual(response_data['answer'], "This is a test answer from the agent.")
        self.assertNotIn('Please configure', response_data['answer'])
    
    @patch('firstaid.services.firstaid_service.build_extended_context')
    def test_firstaid_chat(self, mock_build_context):
        """Test the chat endpoint"""
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_context.layer_a = []
        mock_context.layer_b = []
        mock_context.layer_c = []
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
    
    @patch('firstaid.services.firstaid_service.build_extended_context')
    @patch('firstaid.services.firstaid_service.AgentService.execute_agent')
    def test_firstaid_chat_no_configure_message_on_agent_error(self, mock_execute_agent, mock_build_context):
        """Test that 'Please configure' message does not appear even on agent errors"""
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_context.layer_a = []
        mock_context.layer_b = []
        mock_context.layer_c = []
        mock_build_context.return_value = mock_context
        
        # Mock agent execution to raise an error
        from core.services.exceptions import ServiceNotConfigured
        mock_execute_agent.side_effect = ServiceNotConfigured("AI provider not configured")
        
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
        
        # Should return error but not the "Please configure" message
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertIn('answer', response_data)
        # Error message should be present
        self.assertIn('error', response_data['answer'].lower())
        # But NOT the "Please configure" message
        self.assertNotIn('Please configure an AI agent', response_data['answer'])
    
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
    
    def test_get_project_sources_with_github_issue(self):
        """Test retrieving project sources with GitHub issue mapping"""
        from firstaid.services.firstaid_service import FirstAIDService
        from core.models import ExternalIssueMapping, ExternalIssueKind
        
        # Create a GitHub issue mapping
        ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=12345,
            number=123,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/test/repo/issues/123'
        )
        
        service = FirstAIDService()
        sources = service.get_project_sources(
            project_id=self.project.id,
            user=self.user
        )
        
        # Should have the GitHub issue
        self.assertTrue(len(sources['github_issues']) > 0)
        issue_source = sources['github_issues'][0]
        
        # Title should contain the issue number
        self.assertIn('#123', issue_source.title)
        self.assertIn('GH Issue', issue_source.title)
        self.assertIn(self.item.title, issue_source.title)
        
        # URL should be correct
        self.assertEqual(issue_source.url, 'https://github.com/test/repo/issues/123')
    
    def test_get_project_sources_with_github_issue_and_repo_info(self):
        """Test retrieving project sources with GitHub issue mapping and repo info"""
        from firstaid.services.firstaid_service import FirstAIDService
        from core.models import ExternalIssueMapping, ExternalIssueKind
        
        # Set GitHub repo info on project
        self.project.github_owner = 'gdsanger'
        self.project.github_repo = 'Agira'
        self.project.save()
        
        # Create a GitHub issue mapping
        ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=12345,
            number=123,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/gdsanger/Agira/issues/123'
        )
        
        service = FirstAIDService()
        sources = service.get_project_sources(
            project_id=self.project.id,
            user=self.user
        )
        
        # Should have the GitHub issue
        self.assertTrue(len(sources['github_issues']) > 0)
        issue_source = sources['github_issues'][0]
        
        # Title should contain the full repo reference
        self.assertIn('gdsanger/Agira#123', issue_source.title)
        self.assertIn('GH Issue', issue_source.title)
        self.assertIn(self.item.title, issue_source.title)
    
    def test_get_project_sources_with_github_pr(self):
        """Test retrieving project sources with GitHub PR mapping"""
        from firstaid.services.firstaid_service import FirstAIDService
        from core.models import ExternalIssueMapping, ExternalIssueKind
        
        # Create a GitHub PR mapping
        ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=67890,
            number=456,
            kind=ExternalIssueKind.PR,
            state='open',
            html_url='https://github.com/test/repo/pull/456'
        )
        
        service = FirstAIDService()
        sources = service.get_project_sources(
            project_id=self.project.id,
            user=self.user
        )
        
        # Should have the GitHub PR
        self.assertTrue(len(sources['github_prs']) > 0)
        pr_source = sources['github_prs'][0]
        
        # Title should contain the PR number
        self.assertIn('#456', pr_source.title)
        self.assertIn('GH PR', pr_source.title)
        self.assertIn(self.item.title, pr_source.title)
        
        # URL should be correct
        self.assertEqual(pr_source.url, 'https://github.com/test/repo/pull/456')

