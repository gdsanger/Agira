"""
Tests for Microsoft Graph API mail service.
"""

from unittest.mock import Mock, patch, MagicMock
from io import BytesIO
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache

from core.models import (
    GraphAPIConfiguration, Project, User, ItemType, Item,
    Attachment, ItemComment, CommentKind, EmailDeliveryStatus,
    AttachmentLink, AttachmentRole
)
from core.services.graph.mail_service import (
    send_email, GraphSendResult, _build_email_payload,
    _process_attachment, MAX_ATTACHMENT_SIZE_V1
)
from core.services.exceptions import ServiceDisabled, ServiceNotConfigured, ServiceError


class SendEmailTestCase(TestCase):
    """Test cases for send_email function."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Clear any existing configuration
        GraphAPIConfiguration.objects.all().delete()
        # Clear cache
        cache.clear()
        
        # Create test data
        self.project = Project.objects.create(
            name='Test Project',
            github_owner='test',
            github_repo='test-repo'
        )
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            name='Test User'
        )
        
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug'
        )
        
        self.item = Item.objects.create(
            project=self.project,
            type=self.item_type,
            title='Test Item',
            description='Test description'
        )
    
    def test_send_email_raises_disabled_when_not_enabled(self):
        """Test that send_email raises ServiceDisabled when Graph API is not enabled."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=False
        )
        
        with self.assertRaises(ServiceDisabled):
            send_email(
                subject='Test',
                body='Test body',
                to=['user@example.com']
            )
    
    def test_send_email_raises_error_on_empty_subject(self):
        """Test that send_email raises ServiceError when subject is empty."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='sender@test.com',
            enabled=True
        )
        
        with self.assertRaises(ServiceError) as context:
            send_email(
                subject='',
                body='Test body',
                to=['user@example.com']
            )
        
        self.assertIn('subject', str(context.exception).lower())
    
    def test_send_email_raises_error_on_no_recipients(self):
        """Test that send_email raises ServiceError when no recipients."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='sender@test.com',
            enabled=True
        )
        
        with self.assertRaises(ServiceError) as context:
            send_email(
                subject='Test',
                body='Test body',
                to=[]
            )
        
        self.assertIn('recipient', str(context.exception).lower())
    
    def test_send_email_uses_default_sender_when_not_specified(self):
        """Test that send_email uses default_mail_sender when sender is None."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='default@test.com',
            enabled=True
        )
        
        with patch('core.services.graph.mail_service.get_client') as mock_get_client:
            mock_client = Mock()
            mock_get_client.return_value = mock_client
            
            result = send_email(
                subject='Test',
                body='Test body',
                to=['user@example.com']
            )
            
            # Verify send_mail was called with default sender
            mock_client.send_mail.assert_called_once()
            call_kwargs = mock_client.send_mail.call_args
            # Use args attribute or kwargs
            if call_kwargs.args:
                self.assertEqual(call_kwargs.args[0], 'default@test.com')  # sender_upn
            else:
                self.assertEqual(call_kwargs.kwargs['sender_upn'], 'default@test.com')
    
    def test_send_email_raises_not_configured_when_no_sender_and_no_default(self):
        """Test that send_email raises error when no sender and no default."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            enabled=True
        )
        
        with self.assertRaises(ServiceNotConfigured) as context:
            send_email(
                subject='Test',
                body='Test body',
                to=['user@example.com']
            )
        
        self.assertIn('sender', str(context.exception).lower())
    
    @patch('core.services.graph.mail_service.get_client')
    def test_send_email_sends_successfully(self, mock_get_client):
        """Test that send_email sends email successfully."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='sender@test.com',
            enabled=True
        )
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        result = send_email(
            subject='Test Subject',
            body='Test body',
            to=['user@example.com'],
            sender='custom@test.com'
        )
        
        self.assertTrue(result.success)
        self.assertEqual(result.subject, 'Test Subject')
        self.assertEqual(result.to, ['user@example.com'])
        self.assertEqual(result.sender, 'custom@test.com')
        self.assertIsNone(result.error)
    
    @patch('core.services.graph.mail_service.get_client')
    def test_send_email_handles_client_error(self, mock_get_client):
        """Test that send_email handles client errors gracefully."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='sender@test.com',
            enabled=True
        )
        
        # Mock client to raise error
        mock_client = Mock()
        mock_client.send_mail.side_effect = ServiceError('Test error')
        mock_get_client.return_value = mock_client
        
        result = send_email(
            subject='Test Subject',
            body='Test body',
            to=['user@example.com']
        )
        
        self.assertFalse(result.success)
        self.assertIsNotNone(result.error)
        self.assertIn('Test error', result.error)
    
    @patch('core.services.graph.mail_service.get_client')
    def test_send_email_with_cc_and_bcc(self, mock_get_client):
        """Test that send_email includes CC and BCC recipients."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='sender@test.com',
            enabled=True
        )
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        result = send_email(
            subject='Test',
            body='Test body',
            to=['user@example.com'],
            cc=['cc@example.com'],
            bcc=['bcc@example.com']
        )
        
        self.assertTrue(result.success)
        
        # Verify payload includes CC and BCC
        call_kwargs = mock_client.send_mail.call_args
        if call_kwargs.args and len(call_kwargs.args) > 1:
            payload = call_kwargs.args[1]
        else:
            payload = call_kwargs.kwargs['payload']
        
        self.assertIn('ccRecipients', payload['message'])
        self.assertIn('bccRecipients', payload['message'])
    
    @patch('core.services.graph.mail_service.get_client')
    def test_send_email_creates_item_comment_when_item_provided(self, mock_get_client):
        """Test that send_email creates ItemComment when item is provided."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='sender@test.com',
            enabled=True
        )
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Before sending, no comments exist
        self.assertEqual(ItemComment.objects.count(), 0)
        
        result = send_email(
            subject='Test Email',
            body='<p>Test body</p>',
            to=['user@example.com'],
            item=self.item,
            author=self.user
        )
        
        self.assertTrue(result.success)
        
        # Verify comment was created
        self.assertEqual(ItemComment.objects.count(), 1)
        comment = ItemComment.objects.first()
        
        self.assertEqual(comment.item, self.item)
        self.assertEqual(comment.author, self.user)
        self.assertEqual(comment.kind, CommentKind.EMAIL_OUT)
        self.assertEqual(comment.subject, 'Test Email')
        self.assertEqual(comment.body_html, '<p>Test body</p>')
        self.assertEqual(comment.delivery_status, EmailDeliveryStatus.SENT)
        self.assertIsNotNone(comment.sent_at)
    
    @patch('core.services.graph.mail_service.get_client')
    def test_send_email_sets_comment_to_failed_on_error(self, mock_get_client):
        """Test that send_email sets ItemComment to Failed on error."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='sender@test.com',
            enabled=True
        )
        
        # Mock client to raise error
        mock_client = Mock()
        mock_client.send_mail.side_effect = ServiceError('Send failed')
        mock_get_client.return_value = mock_client
        
        result = send_email(
            subject='Test',
            body='Test body',
            to=['user@example.com'],
            item=self.item
        )
        
        self.assertFalse(result.success)
        
        # Verify comment status is Failed
        comment = ItemComment.objects.first()
        self.assertEqual(comment.delivery_status, EmailDeliveryStatus.FAILED)
        self.assertIsNone(comment.sent_at)


class BuildEmailPayloadTestCase(TestCase):
    """Test cases for _build_email_payload function."""
    
    def test_build_email_payload_basic(self):
        """Test basic email payload construction."""
        payload = _build_email_payload(
            subject='Test Subject',
            body='Test body',
            body_is_html=False,
            to=['user@example.com']
        )
        
        self.assertEqual(payload['message']['subject'], 'Test Subject')
        self.assertEqual(payload['message']['body']['content'], 'Test body')
        self.assertEqual(payload['message']['body']['contentType'], 'Text')
        self.assertEqual(len(payload['message']['toRecipients']), 1)
        self.assertEqual(
            payload['message']['toRecipients'][0]['emailAddress']['address'],
            'user@example.com'
        )
    
    def test_build_email_payload_with_html(self):
        """Test email payload with HTML body."""
        payload = _build_email_payload(
            subject='Test',
            body='<p>HTML body</p>',
            body_is_html=True,
            to=['user@example.com']
        )
        
        self.assertEqual(payload['message']['body']['contentType'], 'HTML')
    
    def test_build_email_payload_with_cc_and_bcc(self):
        """Test email payload with CC and BCC recipients."""
        payload = _build_email_payload(
            subject='Test',
            body='Body',
            body_is_html=False,
            to=['to@example.com'],
            cc=['cc@example.com'],
            bcc=['bcc@example.com']
        )
        
        self.assertIn('ccRecipients', payload['message'])
        self.assertIn('bccRecipients', payload['message'])
        self.assertEqual(len(payload['message']['ccRecipients']), 1)
        self.assertEqual(len(payload['message']['bccRecipients']), 1)
    
    def test_build_email_payload_multiple_recipients(self):
        """Test email payload with multiple recipients."""
        payload = _build_email_payload(
            subject='Test',
            body='Body',
            body_is_html=False,
            to=['user1@example.com', 'user2@example.com', 'user3@example.com']
        )
        
        self.assertEqual(len(payload['message']['toRecipients']), 3)


class ProcessAttachmentTestCase(TestCase):
    """Test cases for _process_attachment function."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.project = Project.objects.create(
            name='Test Project',
            github_owner='test',
            github_repo='test-repo'
        )
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            name='Test User'
        )
    
    def test_process_attachment_basic(self):
        """Test basic attachment processing."""
        # Create a small test file
        file_content = b'Test file content'
        test_file = SimpleUploadedFile(
            'test.txt',
            file_content,
            content_type='text/plain'
        )
        
        attachment = Attachment.objects.create(
            project=self.project,
            uploaded_by=self.user,
            file=test_file,
            original_name='test.txt',
            content_type='text/plain',
            size=len(file_content)
        )
        
        result = _process_attachment(attachment)
        
        self.assertEqual(result['@odata.type'], '#microsoft.graph.fileAttachment')
        self.assertEqual(result['name'], 'test.txt')
        self.assertEqual(result['contentType'], 'text/plain')
        self.assertIn('contentBytes', result)
    
    def test_process_attachment_raises_on_large_file(self):
        """Test that _process_attachment raises error for large files."""
        # Create an attachment with size > MAX_ATTACHMENT_SIZE_V1
        large_size = MAX_ATTACHMENT_SIZE_V1 + 1
        
        # Don't actually create the large file, just set the size
        test_file = SimpleUploadedFile(
            'large.pdf',
            b'content',
            content_type='application/pdf'
        )
        
        attachment = Attachment.objects.create(
            project=self.project,
            uploaded_by=self.user,
            file=test_file,
            original_name='large.pdf',
            content_type='application/pdf',
            size=large_size  # Manually set large size
        )
        
        with self.assertRaises(ServiceError) as context:
            _process_attachment(attachment)
        
        self.assertIn('too large', str(context.exception).lower())


class GraphSendResultTestCase(TestCase):
    """Test cases for GraphSendResult dataclass."""
    
    def test_graph_send_result_success(self):
        """Test GraphSendResult for successful send."""
        result = GraphSendResult(
            sender='sender@test.com',
            to=['user@example.com'],
            subject='Test',
            success=True
        )
        
        self.assertTrue(result.success)
        self.assertIsNone(result.error)
    
    def test_graph_send_result_failure(self):
        """Test GraphSendResult for failed send."""
        result = GraphSendResult(
            sender='sender@test.com',
            to=['user@example.com'],
            subject='Test',
            success=False,
            error='Connection failed'
        )
        
        self.assertFalse(result.success)
        self.assertEqual(result.error, 'Connection failed')
