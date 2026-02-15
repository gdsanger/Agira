"""
Tests for First AID views and services.
"""

from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.urls import reverse
from core.models import User, Project, Organisation, Item, ItemType
from core.services.exceptions import ServiceNotConfigured


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
        mock_context.to_context_text.return_value = 'Test context text'
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
        
        # Verify build_extended_context was called with raw question only (Issue #421)
        mock_build_context.assert_called_once()
        rag_query = mock_build_context.call_args[1]['query']
        self.assertEqual(rag_query, 'What is this project about?', "RAG should receive only raw user question")
        
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
        mock_context.to_context_text.return_value = 'Test context text'
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
        mock_context.to_context_text.return_value = 'Test context text'
        mock_build_context.return_value = mock_context
        
        # Mock agent execution to raise an error
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


class ChatHistoryTestCase(TestCase):
    """Test cases for chat history and thinking level features"""
    
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
        
        # Create test project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project description',
            status='Working'
        )
    
    @patch('firstaid.services.firstaid_service.build_extended_context')
    @patch('firstaid.services.firstaid_service.AgentService.execute_agent')
    def test_chat_with_thinking_level(self, mock_execute_agent, mock_build_context):
        """Test that thinking level is passed to the RAG pipeline"""
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_context.layer_a = []
        mock_context.layer_b = []
        mock_context.layer_c = []
        mock_context.to_context_text.return_value = 'Test context text'
        mock_build_context.return_value = mock_context
        
        # Mock agent execution
        mock_execute_agent.return_value = "Test answer"
        
        url = reverse('firstaid:chat')
        
        # Test with different thinking levels
        for level, expected_length in [('standard', 3000), ('erweitert', 6000), ('professionell', 10000)]:
            data = {
                'question': 'Test question?',
                'project_id': self.project.id,
                'thinking_level': level
            }
            
            response = self.client.post(
                url,
                data=data,
                content_type='application/json'
            )
            
            self.assertEqual(response.status_code, 200)
            
            # Verify build_extended_context was called with correct max_content_length
            call_kwargs = mock_build_context.call_args[1]
            self.assertEqual(call_kwargs['max_content_length'], expected_length)
    
    @patch('firstaid.services.firstaid_service.build_extended_context')
    @patch('firstaid.services.firstaid_service.AgentService.execute_agent')
    def test_chat_history_stored_in_session(self, mock_execute_agent, mock_build_context):
        """Test that chat history is stored in session"""
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_context.layer_a = []
        mock_context.layer_b = []
        mock_context.layer_c = []
        mock_context.to_context_text.return_value = 'Test context text'
        mock_build_context.return_value = mock_context
        
        # Mock agent execution
        mock_execute_agent.return_value = "Test answer"
        
        url = reverse('firstaid:chat')
        data = {
            'question': 'Test question?',
            'project_id': self.project.id
        }
        
        response = self.client.post(
            url,
            data=data,
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify chat history is in session
        session = self.client.session
        session_key = f'firstaid_chat_history_{self.project.id}'
        self.assertIn(session_key, session)
        
        # Verify history has user and assistant messages
        history = session[session_key]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]['role'], 'user')
        self.assertEqual(history[0]['content'], 'Test question?')
        self.assertEqual(history[1]['role'], 'assistant')
        self.assertEqual(history[1]['content'], 'Test answer')
        
        # Verify timestamps are present
        self.assertIn('timestamp', history[0])
        self.assertIn('timestamp', history[1])
    
    @patch('firstaid.services.firstaid_service.build_extended_context')
    @patch('firstaid.services.firstaid_service.AgentService.execute_agent')
    def test_chat_history_summarization(self, mock_execute_agent, mock_build_context):
        """Test that chat history is summarized when follow-up questions are asked"""
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_context.layer_a = []
        mock_context.layer_b = []
        mock_context.layer_c = []
        mock_context.to_context_text.return_value = 'Test context text'
        mock_build_context.return_value = mock_context
        
        # Mock agent execution - return different responses for different agents
        def agent_side_effect(filename, input_text, user, **kwargs):
            if 'chat-summary-agent' in filename:
                return '{"summary": "Previous discussion about authentication", "keywords": ["auth", "security", "login"]}'
            else:
                return "Test answer"
        
        mock_execute_agent.side_effect = agent_side_effect
        
        # First question
        url = reverse('firstaid:chat')
        data1 = {
            'question': 'How does authentication work?',
            'project_id': self.project.id
        }
        self.client.post(url, data=data1, content_type='application/json')
        
        # Second question (follow-up)
        data2 = {
            'question': 'Can you explain more?',
            'project_id': self.project.id
        }
        response = self.client.post(url, data=data2, content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify chat-summary-agent was NOT called (only 2 messages, less than 10)
        calls = [call for call in mock_execute_agent.call_args_list if 'chat-summary-agent' in str(call)]
        self.assertEqual(len(calls), 0, "chat-summary-agent should NOT be called when history <= 10 messages")
    
    @patch('firstaid.services.firstaid_service.build_extended_context')
    @patch('firstaid.services.firstaid_service.AgentService.execute_agent')
    def test_chat_history_recent_transcript_only(self, mock_execute_agent, mock_build_context):
        """Test that recent history (< 10 messages) is sent as transcript only, no summary"""
        from firstaid.services.firstaid_service import FirstAIDService
        
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_context.to_context_text.return_value = 'Test context text'
        mock_build_context.return_value = mock_context
        
        # Mock agent execution
        mock_execute_agent.return_value = "Test answer"
        
        # Create service and test with 4 messages (< 10)
        service = FirstAIDService()
        chat_history = [
            {'role': 'user', 'content': 'Question 1'},
            {'role': 'assistant', 'content': 'Answer 1'},
            {'role': 'user', 'content': 'Question 2'},
            {'role': 'assistant', 'content': 'Answer 2'},
        ]
        
        result = service.chat(
            project_id=self.project.id,
            question='Question 3',
            user=self.user,
            chat_history=chat_history
        )
        
        # Verify that chat-summary-agent was NOT called
        summary_calls = [call for call in mock_execute_agent.call_args_list if 'chat-summary-agent' in str(call)]
        self.assertEqual(len(summary_calls), 0, "chat-summary-agent should NOT be called when history <= 10 messages")
        
        # Verify that build_extended_context was called with ONLY the raw question (Issue #421)
        # Chat history should NOT be in the RAG retrieval query
        mock_build_context.assert_called_once()
        rag_query = mock_build_context.call_args[1]['query']
        self.assertEqual(rag_query, 'Question 3', "RAG should receive only raw user question")
        self.assertNotIn('RECENT_CHAT_TRANSCRIPT', rag_query, "Chat transcript should NOT be in RAG query")
        self.assertNotIn('Question 1', rag_query, "Previous questions should NOT be in RAG query")
        
        # Verify that the question-answering-agent was called
        qa_calls = [call for call in mock_execute_agent.call_args_list if 'question-answering-agent' in str(call)]
        self.assertEqual(len(qa_calls), 1, "question-answering-agent should be called once")
        
        # Verify that recent transcript is included in QA agent input
        qa_input = qa_calls[0][1]['input_text']
        self.assertIn('Letzte Konversation', qa_input)
        self.assertIn('Question 1', qa_input)
        self.assertIn('Answer 2', qa_input)
        
    @patch('firstaid.services.firstaid_service.build_extended_context')
    @patch('firstaid.services.firstaid_service.AgentService.execute_agent')
    def test_chat_history_split_recent_and_older(self, mock_execute_agent, mock_build_context):
        """Test that history > 10 messages is split into recent transcript and older summary"""
        from firstaid.services.firstaid_service import FirstAIDService
        
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_context.to_context_text.return_value = 'Test context text'
        mock_build_context.return_value = mock_context
        
        # Mock agent execution - return different responses for different agents
        def agent_side_effect(filename, input_text, user, **kwargs):
            if 'chat-summary-agent' in filename:
                return '{"summary": "Previous discussion", "keywords": ["test"]}'
            else:
                return "Test answer"
        
        mock_execute_agent.side_effect = agent_side_effect
        
        # Create service and test with 14 messages (> 10)
        service = FirstAIDService()
        chat_history = []
        for i in range(7):  # 7 pairs = 14 messages
            chat_history.append({'role': 'user', 'content': f'Question {i}'})
            chat_history.append({'role': 'assistant', 'content': f'Answer {i}'})
        
        result = service.chat(
            project_id=self.project.id,
            question='Question 8',
            user=self.user,
            chat_history=chat_history
        )
        
        # Verify that chat-summary-agent WAS called for older messages
        summary_calls = [call for call in mock_execute_agent.call_args_list if 'chat-summary-agent' in str(call)]
        self.assertEqual(len(summary_calls), 1, "chat-summary-agent should be called once for older messages")
        
        # Verify that only the first 4 messages (2 pairs, older) were sent to summary agent
        # (14 total - 10 recent = 4 older)
        summary_input = summary_calls[0][1]['input_text']
        num_lines_in_summary = len([line for line in summary_input.split('\n') if line.strip()])
        self.assertEqual(num_lines_in_summary, 4, "Exactly 4 older messages should be summarized")
        self.assertIn('Question 0', summary_input)
        self.assertIn('Answer 1', summary_input)
        self.assertNotIn('Question 5', summary_input)  # Recent messages should not be summarized
        self.assertNotIn('Answer 6', summary_input)
        
        # Verify that build_extended_context was called with ONLY the raw question (Issue #421)
        # Chat history should NOT be in the RAG retrieval query
        mock_build_context.assert_called_once()
        rag_query = mock_build_context.call_args[1]['query']
        self.assertEqual(rag_query, 'Question 8', "RAG should receive only raw user question")
        self.assertNotIn('RECENT_CHAT_TRANSCRIPT', rag_query, "Chat transcript should NOT be in RAG query")
        self.assertNotIn('OLDER_CHAT_SUMMARY', rag_query, "Chat summary should NOT be in RAG query")
        self.assertNotIn('KEYWORDS', rag_query, "Keywords should NOT be in RAG query")
        
        # Verify that the question-answering-agent was called
        qa_calls = [call for call in mock_execute_agent.call_args_list if 'question-answering-agent' in str(call)]
        self.assertEqual(len(qa_calls), 1, "question-answering-agent should be called once")
        
        # Verify that both recent transcript and older summary are included in QA agent input
        qa_input = qa_calls[0][1]['input_text']
        self.assertIn('Letzte Konversation', qa_input)
        self.assertIn('Ältere Chat-Zusammenfassung', qa_input)
        # Recent messages (last 10) should be in the transcript
        self.assertIn('Question 5', qa_input)
        self.assertIn('Answer 6', qa_input)
        
    @patch('firstaid.services.firstaid_service.build_extended_context')
    @patch('firstaid.services.firstaid_service.AgentService.execute_agent')
    def test_chat_history_exactly_10_messages(self, mock_execute_agent, mock_build_context):
        """Test that exactly 10 messages (5 pairs) are sent as recent transcript only"""
        from firstaid.services.firstaid_service import FirstAIDService
        
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_context.to_context_text.return_value = 'Test context text'
        mock_build_context.return_value = mock_context
        
        # Mock agent execution
        mock_execute_agent.return_value = "Test answer"
        
        # Create service and test with exactly 10 messages (5 pairs)
        service = FirstAIDService()
        chat_history = []
        for i in range(5):  # 5 pairs = 10 messages
            chat_history.append({'role': 'user', 'content': f'Question {i}'})
            chat_history.append({'role': 'assistant', 'content': f'Answer {i}'})
        
        result = service.chat(
            project_id=self.project.id,
            question='Question 6',
            user=self.user,
            chat_history=chat_history
        )
        
        # Verify that chat-summary-agent was NOT called
        summary_calls = [call for call in mock_execute_agent.call_args_list if 'chat-summary-agent' in str(call)]
        self.assertEqual(len(summary_calls), 0, "chat-summary-agent should NOT be called for exactly 10 messages")
        
        # Verify that build_extended_context was called with ONLY the raw question (Issue #421)
        mock_build_context.assert_called_once()
        rag_query = mock_build_context.call_args[1]['query']
        self.assertEqual(rag_query, 'Question 6', "RAG should receive only raw user question")
        self.assertNotIn('RECENT_CHAT_TRANSCRIPT', rag_query, "Chat transcript should NOT be in RAG query")
        self.assertNotIn('Question 0', rag_query, "Previous questions should NOT be in RAG query")
        
        # Verify that all messages are in the recent transcript for QA agent
        qa_calls = [call for call in mock_execute_agent.call_args_list if 'question-answering-agent' in str(call)]
        self.assertEqual(len(qa_calls), 1)
        qa_input = qa_calls[0][1]['input_text']
        self.assertIn('Letzte Konversation', qa_input)
        self.assertIn('Question 0', qa_input)
        self.assertIn('Answer 4', qa_input)
    
    
    def test_clear_chat_history(self):
        """Test clearing chat history"""
        # Add some history to session
        session = self.client.session
        session_key = f'firstaid_chat_history_{self.project.id}'
        session[session_key] = [
            {'role': 'user', 'content': 'Test', 'timestamp': '2024-01-01T10:00:00'},
            {'role': 'assistant', 'content': 'Response', 'timestamp': '2024-01-01T10:00:05'}
        ]
        session.save()
        
        # Clear history
        url = reverse('firstaid:clear-chat-history')
        data = {'project_id': self.project.id}
        response = self.client.post(url, data=data, content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        
        # Verify history is cleared
        session = self.client.session
        self.assertNotIn(session_key, session)
    
    @patch('firstaid.services.firstaid_service.build_extended_context')
    @patch('firstaid.services.firstaid_service.AgentService.execute_agent')
    def test_chat_history_truncation(self, mock_execute_agent, mock_build_context):
        """Test that chat history is truncated to last 20 messages"""
        # Mock the RAG context
        mock_context = Mock()
        mock_context.summary = 'Test summary'
        mock_context.all_items = []
        mock_context.stats = {}
        mock_context.layer_a = []
        mock_context.layer_b = []
        mock_context.layer_c = []
        mock_context.to_context_text.return_value = 'Test context text'
        mock_build_context.return_value = mock_context
        
        # Mock agent execution
        mock_execute_agent.return_value = "Test answer"
        
        # Add 10 exchanges (20 messages) to session
        session = self.client.session
        session_key = f'firstaid_chat_history_{self.project.id}'
        history = []
        for i in range(10):
            history.append({'role': 'user', 'content': f'Question {i}', 'timestamp': f'2024-01-01T10:{i:02d}:00'})
            history.append({'role': 'assistant', 'content': f'Answer {i}', 'timestamp': f'2024-01-01T10:{i:02d}:05'})
        session[session_key] = history
        session.save()
        
        # Add one more question (should trigger truncation)
        url = reverse('firstaid:chat')
        data = {
            'question': 'Question 11',
            'project_id': self.project.id
        }
        response = self.client.post(url, data=data, content_type='application/json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify history is truncated to 20 messages
        session = self.client.session
        updated_history = session[session_key]
        self.assertEqual(len(updated_history), 20)
        
        # Verify oldest messages are removed
        self.assertNotEqual(updated_history[0]['content'], 'Question 0')

