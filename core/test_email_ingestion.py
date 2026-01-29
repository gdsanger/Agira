"""
Tests for email ingestion service.
"""

import json
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model

from core.models import (
    Organisation,
    Project,
    ItemType,
    Item,
    ItemStatus,
    GraphAPIConfiguration,
)
from core.services.graph.email_ingestion_service import EmailIngestionService
from core.services.exceptions import ServiceDisabled, ServiceNotConfigured

User = get_user_model()


class EmailIngestionServiceTest(TestCase):
    """Tests for EmailIngestionService."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create GraphAPI configuration
        self.config = GraphAPIConfiguration.objects.create(
            id=1,
            enabled=True,
            tenant_id="test-tenant",
            client_id="test-client",
            client_secret="test-secret",
            default_mail_sender="support@test.com",
        )
        
        # Create test organization
        self.org = Organisation.objects.create(
            name="Test Org",
            mail_domains="test.com\nexample.com",
        )
        
        # Create test project
        self.project = Project.objects.create(
            name="TestProject",
            description="Test project",
        )
        
        # Create fallback project
        self.fallback_project = Project.objects.create(
            name="Incoming",
            description="Inbox for unclassified items",
        )
        
        # Create item types
        self.task_type = ItemType.objects.create(
            key="task",
            name="Task",
            is_active=True,
        )
        self.bug_type = ItemType.objects.create(
            key="bug",
            name="Bug",
            is_active=True,
        )
    
    def test_service_disabled(self):
        """Test that service raises error when disabled."""
        self.config.enabled = False
        self.config.save()
        
        # Clear config cache
        from core.services.config import invalidate_singleton
        invalidate_singleton(GraphAPIConfiguration)
        
        with self.assertRaises(ServiceDisabled):
            EmailIngestionService()
    
    def test_service_not_configured(self):
        """Test that service raises error when not configured."""
        self.config.default_mail_sender = ""
        self.config.save()
        
        # Clear config cache
        from core.services.config import invalidate_singleton
        invalidate_singleton(GraphAPIConfiguration)
        
        with self.assertRaises(ServiceNotConfigured):
            EmailIngestionService()
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    @patch('core.services.graph.email_ingestion_service.AgentService')
    def test_process_inbox_dry_run(self, mock_agent_service, mock_get_client):
        """Test process_inbox in dry run mode."""
        # Mock client
        mock_client = Mock()
        mock_client.get_inbox_messages.return_value = [
            {
                'id': 'msg1',
                'subject': 'Test Email',
                'from': {
                    'emailAddress': {
                        'address': 'sender@test.com',
                        'name': 'Test Sender',
                    }
                },
                'body': {
                    'content': 'Test body',
                    'contentType': 'text',
                },
            }
        ]
        mock_get_client.return_value = mock_client
        
        # Create service and process
        service = EmailIngestionService()
        stats = service.process_inbox(max_messages=10, dry_run=True)
        
        # Verify stats
        self.assertEqual(stats['fetched'], 1)
        self.assertEqual(stats['processed'], 1)
        self.assertEqual(stats['errors'], 0)
        
        # Verify no item was created
        self.assertEqual(Item.objects.count(), 0)
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    @patch('core.services.graph.email_ingestion_service.AgentService')
    def test_get_or_create_user_existing(self, mock_agent_service, mock_get_client):
        """Test getting existing user."""
        # Create existing user
        existing_user = User.objects.create_user(
            username='testuser',
            email='test@test.com',
            password='testpass123',
            name='Test User',
        )
        
        # Mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        service = EmailIngestionService()
        user, org = service._get_or_create_user_and_org(
            email='test@test.com',
            name='Test User',
        )
        
        # Verify same user is returned
        self.assertEqual(user.id, existing_user.id)
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    @patch('core.services.graph.email_ingestion_service.AgentService')
    def test_get_or_create_user_new(self, mock_agent_service, mock_get_client):
        """Test creating new user."""
        # Mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        service = EmailIngestionService()
        user, org = service._get_or_create_user_and_org(
            email='newuser@test.com',
            name='New User',
        )
        
        # Verify user was created
        self.assertIsNotNone(user)
        self.assertEqual(user.email, 'newuser@test.com')
        self.assertEqual(user.name, 'New User')
        
        # Verify organization was assigned based on domain
        self.assertEqual(org, self.org)
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    @patch('core.services.graph.email_ingestion_service.AgentService')
    def test_find_organisation_by_domain(self, mock_agent_service, mock_get_client):
        """Test finding organization by email domain."""
        # Mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        service = EmailIngestionService()
        
        # Test with matching domain
        org = service._find_organisation_by_domain('test.com')
        self.assertEqual(org, self.org)
        
        # Test with another matching domain
        org = service._find_organisation_by_domain('example.com')
        self.assertEqual(org, self.org)
        
        # Test with non-matching domain
        org = service._find_organisation_by_domain('notfound.com')
        self.assertIsNone(org)
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    @patch('core.services.graph.email_ingestion_service.AgentService')
    def test_classify_email(self, mock_agent_service, mock_get_client):
        """Test email classification."""
        # Mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock agent service
        mock_agent_instance = Mock()
        mock_agent_instance.execute_agent.return_value = json.dumps({
            'project': 'TestProject',
            'type': 'bug',
        })
        mock_agent_service.return_value = mock_agent_instance
        
        service = EmailIngestionService()
        project, item_type = service._classify_email(
            sender_email='test@test.com',
            subject='Bug report',
            body='This is a bug',
        )
        
        # Verify classification
        self.assertEqual(project, self.project)
        self.assertEqual(item_type, self.bug_type)
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    @patch('core.services.graph.email_ingestion_service.AgentService')
    def test_classify_email_fallback_project(self, mock_agent_service, mock_get_client):
        """Test email classification with fallback to Incoming project."""
        # Mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock agent service to return non-existent project
        mock_agent_instance = Mock()
        mock_agent_instance.execute_agent.return_value = json.dumps({
            'project': 'NonExistentProject',
            'type': 'task',
        })
        mock_agent_service.return_value = mock_agent_instance
        
        service = EmailIngestionService()
        project, item_type = service._classify_email(
            sender_email='test@test.com',
            subject='Test',
            body='Test body',
        )
        
        # Verify fallback to Incoming project
        self.assertEqual(project, self.fallback_project)
        self.assertEqual(item_type, self.task_type)
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    @patch('core.services.graph.email_ingestion_service.AgentService')
    def test_classify_email_invalid_type(self, mock_agent_service, mock_get_client):
        """Test email classification with invalid type defaults to task."""
        # Mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock agent service to return invalid type
        mock_agent_instance = Mock()
        mock_agent_instance.execute_agent.return_value = json.dumps({
            'project': 'TestProject',
            'type': 'invalid_type',
        })
        mock_agent_service.return_value = mock_agent_instance
        
        service = EmailIngestionService()
        project, item_type = service._classify_email(
            sender_email='test@test.com',
            subject='Test',
            body='Test body',
        )
        
        # Verify defaults to task type
        self.assertEqual(item_type, self.task_type)
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    @patch('core.services.graph.email_ingestion_service.AgentService')
    def test_convert_html_to_markdown(self, mock_agent_service, mock_get_client):
        """Test HTML to Markdown conversion."""
        # Mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock agent service
        mock_agent_instance = Mock()
        mock_agent_instance.execute_agent.return_value = "# Heading\n\nParagraph"
        mock_agent_service.return_value = mock_agent_instance
        
        service = EmailIngestionService()
        markdown = service._convert_html_to_markdown('<h1>Heading</h1><p>Paragraph</p>')
        
        # Verify conversion
        self.assertEqual(markdown, "# Heading\n\nParagraph")
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    @patch('core.services.graph.email_ingestion_service.AgentService')
    def test_process_message_creates_item(self, mock_agent_service, mock_get_client):
        """Test processing a message creates an item."""
        # Mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Mock agent service
        mock_agent_instance = Mock()
        mock_agent_instance.execute_agent.side_effect = [
            "Test body in markdown",  # HTML to Markdown conversion
            json.dumps({'project': 'TestProject', 'type': 'task'}),  # Classification
        ]
        mock_agent_service.return_value = mock_agent_instance
        
        service = EmailIngestionService()
        
        # Create message
        message = {
            'id': 'msg123',
            'subject': 'Test Subject',
            'from': {
                'emailAddress': {
                    'address': 'sender@test.com',
                    'name': 'Test Sender',
                }
            },
            'body': {
                'content': '<p>Test body</p>',
                'contentType': 'html',
            },
            'isRead': False,
        }
        
        # Process message
        with patch.object(service, '_send_confirmation_email'):
            item = service._process_message(message)
        
        # Verify item was created
        self.assertIsNotNone(item)
        self.assertEqual(item.title, 'Test Subject')
        self.assertEqual(item.description, 'Test body in markdown')
        self.assertEqual(item.status, ItemStatus.INBOX)
        self.assertEqual(item.project, self.project)
        self.assertEqual(item.type, self.task_type)
        
        # Verify message was marked as processed
        mock_client.add_category_to_message.assert_called_once()
        mock_client.mark_message_as_read.assert_called_once()
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    def test_get_project_creates_fallback(self, mock_get_client):
        """Test that fallback project is created if it doesn't exist."""
        # Delete existing fallback project
        Project.objects.filter(name="Incoming").delete()
        
        # Mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        service = EmailIngestionService()
        project = service._get_project(None)
        
        # Verify fallback project was created
        self.assertEqual(project.name, "Incoming")
        self.assertTrue(Project.objects.filter(name="Incoming").exists())
    
    @patch('core.services.graph.email_ingestion_service.get_client')
    def test_get_item_type_creates_if_not_exists(self, mock_get_client):
        """Test that item type is created if it doesn't exist."""
        # Delete existing feature type
        ItemType.objects.filter(key="feature").delete()
        
        # Mock client
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        service = EmailIngestionService()
        item_type = service._get_item_type("feature")
        
        # Verify item type was created
        self.assertEqual(item_type.key, "feature")
        self.assertTrue(ItemType.objects.filter(key="feature").exists())
