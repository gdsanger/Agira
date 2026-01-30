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
    _process_attachment, MAX_ATTACHMENT_SIZE_V1,
    _normalize_email, _is_blocked_system_recipient
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
            # Check the sender_upn argument (first positional arg)
            call = mock_client.send_mail.call_args_list[0]
            sender_upn = call.args[0] if call.args else call.kwargs.get('sender_upn')
            self.assertEqual(sender_upn, 'default@test.com')
    
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
        call = mock_client.send_mail.call_args_list[0]
        payload = call.args[1] if len(call.args) > 1 else call.kwargs.get('payload')
        
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
        # Subject should include issue ID prefix
        self.assertEqual(comment.subject, f'[AGIRA-{self.item.id}] Test Email')
        # Body should store plain text (HTML tags stripped for display)
        self.assertEqual(comment.body, 'Test body')
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
    
    @patch('core.services.graph.mail_service.get_client')
    def test_send_email_adds_issue_id_to_subject_when_item_provided(self, mock_get_client):
        """Test that send_email adds [AGIRA-{id}] prefix to subject when item is provided."""
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
            subject='Test Email',
            body='<p>Test body</p>',
            to=['user@example.com'],
            item=self.item
        )
        
        self.assertTrue(result.success)
        
        # Verify payload has modified subject
        call = mock_client.send_mail.call_args_list[0]
        payload = call.args[1] if len(call.args) > 1 else call.kwargs.get('payload')
        
        # Subject should be [AGIRA-{item.id}] Test Email
        expected_subject = f"[AGIRA-{self.item.id}] Test Email"
        self.assertEqual(payload['message']['subject'], expected_subject)
        
        # Verify ItemComment also has the modified subject
        comment = ItemComment.objects.first()
        self.assertEqual(comment.subject, expected_subject)
    
    @patch('core.services.graph.mail_service.get_client')
    def test_send_email_does_not_modify_subject_without_item(self, mock_get_client):
        """Test that send_email does not modify subject when no item is provided."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='sender@test.com',
            enabled=True
        )
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        original_subject = 'Test Email'
        result = send_email(
            subject=original_subject,
            body='<p>Test body</p>',
            to=['user@example.com']
        )
        
        self.assertTrue(result.success)
        
        # Verify payload has unmodified subject
        call = mock_client.send_mail.call_args_list[0]
        payload = call.args[1] if len(call.args) > 1 else call.kwargs.get('payload')
        
        # Subject should be unchanged
        self.assertEqual(payload['message']['subject'], original_subject)


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


class MailLoopProtectionTestCase(TestCase):
    """Test cases for mail loop protection (blocking emails to system default address)."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Clear any existing configuration
        GraphAPIConfiguration.objects.all().delete()
        # Clear cache
        cache.clear()
    
    def test_normalize_email_lowercase(self):
        """Test that _normalize_email converts to lowercase."""
        self.assertEqual(_normalize_email('USER@EXAMPLE.COM'), 'user@example.com')
        self.assertEqual(_normalize_email('User@Example.Com'), 'user@example.com')
    
    def test_normalize_email_strips_whitespace(self):
        """Test that _normalize_email strips whitespace."""
        self.assertEqual(_normalize_email('  user@example.com  '), 'user@example.com')
        self.assertEqual(_normalize_email('\tuser@example.com\n'), 'user@example.com')
    
    def test_is_blocked_system_recipient_no_config(self):
        """Test that _is_blocked_system_recipient returns False when no config."""
        # No configuration exists
        result = _is_blocked_system_recipient(['test@example.com'])
        self.assertFalse(result)
    
    def test_is_blocked_system_recipient_empty_list(self):
        """Test that _is_blocked_system_recipient handles empty lists."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        result = _is_blocked_system_recipient([])
        self.assertFalse(result)
    
    def test_is_blocked_system_recipient_matches(self):
        """Test that _is_blocked_system_recipient detects matching addresses."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        # Test various matching scenarios
        self.assertTrue(_is_blocked_system_recipient(['system@example.com']))
        self.assertTrue(_is_blocked_system_recipient(['SYSTEM@EXAMPLE.COM']))
        self.assertTrue(_is_blocked_system_recipient(['  system@example.com  ']))
        self.assertTrue(_is_blocked_system_recipient(['other@example.com', 'system@example.com']))
    
    def test_is_blocked_system_recipient_no_match(self):
        """Test that _is_blocked_system_recipient returns False for non-matching addresses."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        self.assertFalse(_is_blocked_system_recipient(['user@example.com']))
        self.assertFalse(_is_blocked_system_recipient(['other@example.com', 'another@test.com']))
    
    def test_blocks_email_to_default_address_in_to_field(self):
        """Test that emails to the default address in 'to' field are blocked."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        result = send_email(
            subject='Test Subject',
            body='Test body',
            to=['system@example.com', 'other@example.com']
        )
        
        # Email should be blocked
        self.assertFalse(result.success)
        self.assertIn('mail loop protection', result.error.lower())
        self.assertIn('blocked', result.error.lower())
    
    def test_blocks_email_to_default_address_in_cc_field(self):
        """Test that emails with default address in 'cc' field are blocked."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        result = send_email(
            subject='Test Subject',
            body='Test body',
            to=['user@example.com'],
            cc=['system@example.com']
        )
        
        # Email should be blocked
        self.assertFalse(result.success)
        self.assertIn('mail loop protection', result.error.lower())
    
    def test_blocks_email_to_default_address_in_bcc_field(self):
        """Test that emails with default address in 'bcc' field are blocked."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        result = send_email(
            subject='Test Subject',
            body='Test body',
            to=['user@example.com'],
            bcc=['system@example.com']
        )
        
        # Email should be blocked
        self.assertFalse(result.success)
        self.assertIn('mail loop protection', result.error.lower())
    
    def test_blocks_email_case_insensitive(self):
        """Test that blocking is case-insensitive."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        # Try different case variations
        for address in ['SYSTEM@EXAMPLE.COM', 'System@Example.Com', 'SyStEm@ExAmPlE.cOm']:
            result = send_email(
                subject='Test Subject',
                body='Test body',
                to=[address]
            )
            
            self.assertFalse(result.success, f"Should block {address}")
            self.assertIn('mail loop protection', result.error.lower())
    
    def test_blocks_email_with_whitespace(self):
        """Test that blocking handles email addresses with whitespace."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        result = send_email(
            subject='Test Subject',
            body='Test body',
            to=['  system@example.com  ']
        )
        
        # Email should be blocked
        self.assertFalse(result.success)
        self.assertIn('mail loop protection', result.error.lower())
    
    @patch('core.services.graph.mail_service.get_client')
    def test_allows_email_to_different_address(self, mock_get_client):
        """Test that emails to different addresses are allowed."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        result = send_email(
            subject='Test Subject',
            body='Test body',
            to=['user@example.com'],
            cc=['other@example.com'],
            bcc=['another@example.com']
        )
        
        # Email should be sent successfully
        self.assertTrue(result.success)
        mock_client.send_mail.assert_called_once()
    
    @patch('core.services.graph.mail_service.get_client')
    def test_allows_email_when_no_default_configured(self, mock_get_client):
        """Test that emails are allowed when no default address is configured."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='',  # No default configured
            enabled=True
        )
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        result = send_email(
            subject='Test Subject',
            body='Test body',
            to=['system@example.com'],
            sender='custom@example.com'
        )
        
        # Email should be sent successfully
        self.assertTrue(result.success)
        mock_client.send_mail.assert_called_once()
    
    def test_blocked_email_logs_details(self):
        """Test that blocked emails are logged with appropriate details."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        with self.assertLogs('core.services.graph.mail_service', level='WARNING') as log_context:
            result = send_email(
                subject='Important Email',
                body='Test body',
                to=['user@example.com', 'system@example.com'],
                cc=['cc@example.com']
            )
            
            # Check that warning was logged
            self.assertTrue(
                any('Agira self-mail protection' in msg for msg in log_context.output),
                "Should log 'Agira self-mail protection'"
            )
            self.assertTrue(
                any('system@example.com' in msg for msg in log_context.output),
                "Should log the default address"
            )
            self.assertTrue(
                any('Important Email' in msg for msg in log_context.output),
                "Should log the subject"
            )
    
    @patch('core.services.graph.mail_service.get_client')
    def test_multiple_recipients_with_mixed_addresses(self, mock_get_client):
        """Test blocking works correctly with multiple recipients including blocked ones."""
        GraphAPIConfiguration.objects.create(
            tenant_id='test-tenant',
            client_id='test-client',
            client_secret='test-secret',
            default_mail_sender='system@example.com',
            enabled=True
        )
        
        mock_client = Mock()
        mock_get_client.return_value = mock_client
        
        # Even one blocked address should prevent sending
        result = send_email(
            subject='Test Subject',
            body='Test body',
            to=['user1@example.com', 'system@example.com', 'user2@example.com']
        )
        
        # Email should be blocked
        self.assertFalse(result.success)
        # Client should NOT be called
        mock_client.send_mail.assert_not_called()
