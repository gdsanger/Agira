"""
Tests for Change approval request sending functionality with error handling
"""

from unittest.mock import patch, Mock, MagicMock
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Change, ChangeApproval, ChangeStatus, Project,
    User, ApprovalStatus, RiskLevel, MailTemplate
)
from core.printing.dto import PdfResult
from core.services.exceptions import ServiceError, ServiceDisabled, ServiceNotConfigured
from core.services.changes.approval_mailer import generate_change_pdf_bytes


class ChangeApprovalRequestsTestCase(TestCase):
    """Test cases for change approval request sending with error handling"""
    
    def setUp(self):
        """Set up test data"""
        # Create users
        self.admin_user = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="testpass",
            name="Admin User"
        )
        
        self.approver_user = User.objects.create_user(
            username="approver",
            email="approver@example.com",
            password="testpass",
            name="Approver User"
        )
        
        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            status="ACTIVE",
            created_by=self.admin_user
        )
        
        # Create change
        self.change = Change.objects.create(
            title="Test Change",
            description="Test change description",
            project=self.project,
            status=ChangeStatus.DRAFT,
            risk_level=RiskLevel.MEDIUM,
            created_by=self.admin_user
        )
        
        # Create approval
        self.approval = ChangeApproval.objects.create(
            change=self.change,
            approver=self.approver_user,
            status=ApprovalStatus.PENDING
        )
        
        # Create mail template
        self.mail_template = MailTemplate.objects.create(
            key="change-approval-request",
            subject="Test Subject",
            message="Test Message",
            is_active=True
        )
        
        # Set up test client
        self.client = Client()
        self.client.login(username="admin", password="testpass")
        
        self.url = reverse('change-send-approval-requests', kwargs={'id': self.change.id})
    
    @patch('core.views.get_graph_config')
    def test_service_disabled_returns_400(self, mock_get_config):
        """Test that disabled Graph API service returns 400 with clear error message"""
        # Mock Graph API as disabled
        mock_config = Mock()
        mock_config.enabled = False
        mock_get_config.return_value = mock_config
        
        response = self.client.post(self.url)
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not enabled', data['error'].lower())
        self.assertIn('Microsoft Graph API', data['error'])
    
    @patch('core.views.get_graph_config')
    def test_service_not_configured_returns_400(self, mock_get_config):
        """Test that misconfigured Graph API service returns 400 with clear error message"""
        # Mock Graph API as enabled but not configured
        mock_config = Mock()
        mock_config.enabled = True
        mock_config.tenant_id = ""
        mock_config.client_id = ""
        mock_config.client_secret = ""
        mock_get_config.return_value = mock_config
        
        response = self.client.post(self.url)
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not properly configured', data['error'].lower())
        self.assertIn('credentials', data['error'].lower())
    
    @patch('core.views.get_graph_config')
    def test_partial_configuration_returns_400(self, mock_get_config):
        """Test that partially configured Graph API service returns 400"""
        # Mock Graph API as enabled but missing some credentials
        mock_config = Mock()
        mock_config.enabled = True
        mock_config.tenant_id = "test-tenant"
        mock_config.client_id = ""
        mock_config.client_secret = "test-secret"
        mock_get_config.return_value = mock_config
        
        response = self.client.post(self.url)
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('not properly configured', data['error'].lower())
    
    @patch('core.services.changes.approval_mailer.send_change_approval_request_emails')
    @patch('core.views.get_graph_config')
    def test_service_error_returns_500_with_message(self, mock_get_config, mock_send_emails):
        """Test that ServiceError during sending returns 500 with error message"""
        # Mock Graph API as properly configured
        mock_config = Mock()
        mock_config.enabled = True
        mock_config.tenant_id = "test-tenant"
        mock_config.client_id = "test-client"
        mock_config.client_secret = "test-secret"
        mock_get_config.return_value = mock_config
        
        # Mock send_emails to raise ServiceError
        mock_send_emails.side_effect = ServiceError("Connection failed")
        
        response = self.client.post(self.url)
        
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Connection failed', data['error'])
    
    @patch('core.services.changes.approval_mailer.send_change_approval_request_emails')
    @patch('core.views.get_graph_config')
    def test_unexpected_error_returns_500(self, mock_get_config, mock_send_emails):
        """Test that unexpected errors are caught and return 500"""
        # Mock Graph API as properly configured
        mock_config = Mock()
        mock_config.enabled = True
        mock_config.tenant_id = "test-tenant"
        mock_config.client_id = "test-client"
        mock_config.client_secret = "test-secret"
        mock_get_config.return_value = mock_config
        
        # Mock send_emails to raise unexpected error
        mock_send_emails.side_effect = RuntimeError("Unexpected error")
        
        response = self.client.post(self.url)
        
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Unexpected error', data['error'])
    
    @patch('core.services.changes.approval_mailer.send_change_approval_request_emails')
    @patch('core.views.get_graph_config')
    def test_successful_send_returns_200(self, mock_get_config, mock_send_emails):
        """Test that successful email sending returns 200 with success message"""
        # Mock Graph API as properly configured
        mock_config = Mock()
        mock_config.enabled = True
        mock_config.tenant_id = "test-tenant"
        mock_config.client_id = "test-client"
        mock_config.client_secret = "test-secret"
        mock_get_config.return_value = mock_config
        
        # Mock successful email sending
        mock_send_emails.return_value = {
            'success': True,
            'sent_count': 1,
            'failed_count': 0,
            'errors': []
        }
        
        response = self.client.post(self.url)
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertIn('sent', data['message'].lower())
        self.assertEqual(data['sent_count'], 1)
    
    @patch('core.services.changes.approval_mailer.send_change_approval_request_emails')
    @patch('core.views.get_graph_config')
    def test_partial_failure_returns_500(self, mock_get_config, mock_send_emails):
        """Test that partial failure returns 500 with error details"""
        # Mock Graph API as properly configured
        mock_config = Mock()
        mock_config.enabled = True
        mock_config.tenant_id = "test-tenant"
        mock_config.client_id = "test-client"
        mock_config.client_secret = "test-secret"
        mock_get_config.return_value = mock_config
        
        # Mock partial failure
        mock_send_emails.return_value = {
            'success': False,
            'sent_count': 0,
            'failed_count': 1,
            'errors': ['approver@example.com: Connection timeout']
        }
        
        response = self.client.post(self.url)
        
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('failed', data['error'].lower())
        self.assertEqual(data['sent_count'], 0)
        self.assertEqual(data['failed_count'], 1)
    
    def test_unauthenticated_user_redirected(self):
        """Test that unauthenticated users are redirected to login"""
        self.client.logout()
        response = self.client.post(self.url)
        
        # Should redirect to login page
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_get_request_not_allowed(self):
        """Test that GET requests are not allowed (only POST)"""
        response = self.client.get(self.url)
        
        # Should return 405 Method Not Allowed
        self.assertEqual(response.status_code, 405)
    
    def test_nonexistent_change_returns_404(self):
        """Test that requesting approval for non-existent change returns 404"""
        url = reverse('change-send-approval-requests', kwargs={'id': 99999})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, 404)


class GenerateChangePdfBytesTestCase(TestCase):
    """Test generate_change_pdf_bytes uses correct PdfResult attributes"""

    def setUp(self):
        self.user = User.objects.create_user(
            username="pdfuser",
            email="pdfuser@example.com",
            password="testpass",
            name="PDF User"
        )
        self.project = Project.objects.create(
            name="PDF Test Project",
            status="ACTIVE"
        )
        self.change = Change.objects.create(
            title="PDF Test Change",
            description="PDF test description",
            project=self.project,
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            created_by=self.user
        )

    @patch('core.services.changes.approval_mailer.PdfRenderService')
    def test_returns_pdf_bytes(self, mock_service_class):
        """generate_change_pdf_bytes should return PdfResult.pdf_bytes"""
        expected_bytes = b"%PDF-1.4 fake pdf content"
        mock_result = PdfResult(
            pdf_bytes=expected_bytes,
            filename="change-1.pdf",
        )
        mock_service_class.return_value.render.return_value = mock_result

        result = generate_change_pdf_bytes(self.change, "http://testserver")

        self.assertEqual(result, expected_bytes)

    @patch('core.services.changes.approval_mailer.PdfRenderService')
    def test_raises_service_error_when_pdf_too_large(self, mock_service_class):
        """generate_change_pdf_bytes should raise ServiceError when PDF exceeds 3 MB"""
        oversized_bytes = b"x" * (3 * 1024 * 1024 + 1)
        mock_result = PdfResult(
            pdf_bytes=oversized_bytes,
            filename="change-1.pdf",
        )
        mock_service_class.return_value.render.return_value = mock_result

        with self.assertRaises(ServiceError) as ctx:
            generate_change_pdf_bytes(self.change, "http://testserver")

        self.assertIn("too large", str(ctx.exception).lower())


class ChangeUpdateReminderServiceTestCase(TestCase):
    """Tests for send_change_update_reminder_emails service function"""

    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin_ur",
            email="admin_ur@example.com",
            password="testpass",
            name="Admin UR"
        )
        self.pending_approver = User.objects.create_user(
            username="pending_ur",
            email="pending_ur@example.com",
            password="testpass",
            name="Pending Approver UR"
        )
        self.accept_approver = User.objects.create_user(
            username="accept_ur",
            email="accept_ur@example.com",
            password="testpass",
            name="Accept Approver UR"
        )
        self.reject_approver = User.objects.create_user(
            username="reject_ur",
            email="reject_ur@example.com",
            password="testpass",
            name="Reject Approver UR"
        )
        self.project = Project.objects.create(
            name="UR Test Project",
            status="ACTIVE",
            created_by=self.admin_user
        )
        self.change = Change.objects.create(
            title="UR Test Change",
            description="desc",
            project=self.project,
            status=ChangeStatus.DRAFT,
            risk_level=RiskLevel.MEDIUM,
            created_by=self.admin_user
        )
        self.pending_approval = ChangeApproval.objects.create(
            change=self.change,
            approver=self.pending_approver,
            status=ApprovalStatus.PENDING
        )
        self.accept_approval = ChangeApproval.objects.create(
            change=self.change,
            approver=self.accept_approver,
            status=ApprovalStatus.ACCEPT
        )
        self.reject_approval = ChangeApproval.objects.create(
            change=self.change,
            approver=self.reject_approver,
            status=ApprovalStatus.REJECT
        )
        MailTemplate.objects.create(
            key="change-update-reminder",
            subject="Update-Erinnerung: {{ change_title }} ({{ change_id }})",
            message="<p>Erinnerung: {{ change_id }} - {{ change_title }}</p>",
            is_active=True
        )

    @patch('core.services.changes.approval_mailer.send_email')
    @patch('core.services.changes.approval_mailer.create_attachment_from_bytes')
    @patch('core.services.changes.approval_mailer.generate_change_pdf_bytes')
    def test_sends_to_pending_and_accept_not_reject(self, mock_pdf, mock_attach, mock_send):
        """PENDING and ACCEPT approvers receive mail; REJECT does not."""
        from core.services.changes.approval_mailer import send_change_update_reminder_emails
        mock_pdf.return_value = b"pdf"
        mock_attach.return_value = Mock()
        mock_result = Mock()
        mock_result.success = True
        mock_send.return_value = mock_result

        result = send_change_update_reminder_emails(self.change, "http://testserver")

        self.assertEqual(result['sent_count'], 2)
        self.assertEqual(result['failed_count'], 0)
        sent_emails = [call.kwargs['to'][0] for call in mock_send.call_args_list]
        self.assertIn(self.pending_approver.email, sent_emails)
        self.assertIn(self.accept_approver.email, sent_emails)
        self.assertNotIn(self.reject_approver.email, sent_emails)

    @patch('core.services.changes.approval_mailer.generate_change_pdf_bytes')
    def test_missing_template_raises_service_error(self, mock_pdf):
        """Missing or inactive template raises ServiceError."""
        from core.services.changes.approval_mailer import send_change_update_reminder_emails
        MailTemplate.objects.filter(key='change-update-reminder').delete()
        with self.assertRaises(ServiceError) as ctx:
            send_change_update_reminder_emails(self.change, "http://testserver")
        self.assertIn("change-update-reminder", str(ctx.exception))

    @patch('core.services.changes.approval_mailer.generate_change_pdf_bytes')
    def test_inactive_template_raises_service_error(self, mock_pdf):
        """Inactive template raises ServiceError."""
        from core.services.changes.approval_mailer import send_change_update_reminder_emails
        MailTemplate.objects.filter(key='change-update-reminder').update(is_active=False)
        with self.assertRaises(ServiceError):
            send_change_update_reminder_emails(self.change, "http://testserver")

    @patch('core.services.changes.approval_mailer.generate_change_pdf_bytes')
    def test_oversized_pdf_raises_service_error(self, mock_pdf):
        """PDF exceeding 3 MB raises ServiceError."""
        from core.services.changes.approval_mailer import send_change_update_reminder_emails
        mock_pdf.side_effect = ServiceError("PDF too large")
        with self.assertRaises(ServiceError) as ctx:
            send_change_update_reminder_emails(self.change, "http://testserver")
        self.assertIn("PDF", str(ctx.exception))

    @patch('core.services.changes.approval_mailer.send_email')
    @patch('core.services.changes.approval_mailer.create_attachment_from_bytes')
    @patch('core.services.changes.approval_mailer.generate_change_pdf_bytes')
    def test_attachment_passed_to_send_email(self, mock_pdf, mock_attach, mock_send):
        """PDF attachment is passed to send_email."""
        from core.services.changes.approval_mailer import send_change_update_reminder_emails
        mock_pdf.return_value = b"pdf"
        fake_attachment = Mock()
        mock_attach.return_value = fake_attachment
        mock_result = Mock()
        mock_result.success = True
        mock_send.return_value = mock_result

        send_change_update_reminder_emails(self.change, "http://testserver")

        for call in mock_send.call_args_list:
            self.assertIn(fake_attachment, call.kwargs['attachments'])


class ChangeUpdateCompletedServiceTestCase(TestCase):
    """Tests for send_change_update_completed_emails service function"""

    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin_uc",
            email="admin_uc@example.com",
            password="testpass",
            name="Admin UC"
        )
        self.pending_approver = User.objects.create_user(
            username="pending_uc",
            email="pending_uc@example.com",
            password="testpass",
            name="Pending Approver UC"
        )
        self.reject_approver = User.objects.create_user(
            username="reject_uc",
            email="reject_uc@example.com",
            password="testpass",
            name="Reject Approver UC"
        )
        self.project = Project.objects.create(
            name="UC Test Project",
            status="ACTIVE",
            created_by=self.admin_user
        )
        self.change = Change.objects.create(
            title="UC Test Change",
            description="desc",
            project=self.project,
            status=ChangeStatus.DRAFT,
            risk_level=RiskLevel.MEDIUM,
            created_by=self.admin_user
        )
        ChangeApproval.objects.create(
            change=self.change,
            approver=self.pending_approver,
            status=ApprovalStatus.PENDING
        )
        ChangeApproval.objects.create(
            change=self.change,
            approver=self.reject_approver,
            status=ApprovalStatus.REJECT
        )
        MailTemplate.objects.create(
            key="change-update-completed",
            subject="Update abgeschlossen: {{ change_title }} ({{ change_id }})",
            message="<p>Abgeschlossen: {{ change_id }} - {{ change_title }}</p>",
            is_active=True
        )

    @patch('core.services.changes.approval_mailer.send_email')
    @patch('core.services.changes.approval_mailer.create_attachment_from_bytes')
    @patch('core.services.changes.approval_mailer.generate_change_pdf_bytes')
    def test_sets_executed_at(self, mock_pdf, mock_attach, mock_send):
        """executed_at is always set/overwritten when action is triggered."""
        from core.services.changes.approval_mailer import send_change_update_completed_emails
        mock_pdf.return_value = b"pdf"
        mock_attach.return_value = Mock()
        mock_result = Mock()
        mock_result.success = True
        mock_send.return_value = mock_result

        before = timezone.now()
        send_change_update_completed_emails(self.change, "http://testserver")
        after = timezone.now()

        self.change.refresh_from_db()
        self.assertIsNotNone(self.change.executed_at)
        self.assertGreaterEqual(self.change.executed_at, before)
        self.assertLessEqual(self.change.executed_at, after)

    @patch('core.services.changes.approval_mailer.send_email')
    @patch('core.services.changes.approval_mailer.create_attachment_from_bytes')
    @patch('core.services.changes.approval_mailer.generate_change_pdf_bytes')
    def test_overwrites_existing_executed_at(self, mock_pdf, mock_attach, mock_send):
        """executed_at is overwritten even when already set."""
        from core.services.changes.approval_mailer import send_change_update_completed_emails
        old_time = timezone.now() - timezone.timedelta(days=10)
        self.change.executed_at = old_time
        self.change.save(update_fields=['executed_at'])

        mock_pdf.return_value = b"pdf"
        mock_attach.return_value = Mock()
        mock_result = Mock()
        mock_result.success = True
        mock_send.return_value = mock_result

        send_change_update_completed_emails(self.change, "http://testserver")
        self.change.refresh_from_db()
        self.assertGreater(self.change.executed_at, old_time)

    @patch('core.services.changes.approval_mailer.send_email')
    @patch('core.services.changes.approval_mailer.create_attachment_from_bytes')
    @patch('core.services.changes.approval_mailer.generate_change_pdf_bytes')
    def test_reject_approver_does_not_receive_mail(self, mock_pdf, mock_attach, mock_send):
        """REJECT approvers do not receive mail."""
        from core.services.changes.approval_mailer import send_change_update_completed_emails
        mock_pdf.return_value = b"pdf"
        mock_attach.return_value = Mock()
        mock_result = Mock()
        mock_result.success = True
        mock_send.return_value = mock_result

        result = send_change_update_completed_emails(self.change, "http://testserver")

        sent_emails = [call.kwargs['to'][0] for call in mock_send.call_args_list]
        self.assertNotIn(self.reject_approver.email, sent_emails)
        self.assertIn(self.pending_approver.email, sent_emails)

    @patch('core.services.changes.approval_mailer.generate_change_pdf_bytes')
    def test_missing_template_raises_service_error(self, mock_pdf):
        """Missing template raises ServiceError."""
        from core.services.changes.approval_mailer import send_change_update_completed_emails
        MailTemplate.objects.filter(key='change-update-completed').delete()
        with self.assertRaises(ServiceError):
            send_change_update_completed_emails(self.change, "http://testserver")


class ChangeUpdateReminderEndpointTestCase(TestCase):
    """Smoke tests for /changes/<id>/send-update-reminder/ endpoint"""

    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin_ep_ur",
            email="admin_ep_ur@example.com",
            password="testpass",
            name="Admin EP UR"
        )
        self.project = Project.objects.create(
            name="EP UR Project",
            status="ACTIVE",
            created_by=self.admin_user
        )
        self.change = Change.objects.create(
            title="EP UR Change",
            description="desc",
            project=self.project,
            status=ChangeStatus.DRAFT,
            risk_level=RiskLevel.MEDIUM,
            created_by=self.admin_user
        )
        self.client = Client()
        self.client.login(username="admin_ep_ur", password="testpass")
        self.url = reverse('change-send-update-reminder', kwargs={'id': self.change.id})

    def test_unauthenticated_redirected(self):
        self.client.logout()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_nonexistent_change_404(self):
        url = reverse('change-send-update-reminder', kwargs={'id': 99999})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    @patch('core.views.get_graph_config')
    def test_disabled_service_returns_400(self, mock_get_config):
        mock_config = Mock()
        mock_config.enabled = False
        mock_get_config.return_value = mock_config
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

    @patch('core.services.changes.approval_mailer.send_change_update_reminder_emails')
    @patch('core.views.get_graph_config')
    def test_successful_send_returns_200(self, mock_get_config, mock_send):
        mock_config = Mock()
        mock_config.enabled = True
        mock_config.tenant_id = "t"
        mock_config.client_id = "c"
        mock_config.client_secret = "s"
        mock_get_config.return_value = mock_config
        mock_send.return_value = {'success': True, 'sent_count': 1, 'failed_count': 0, 'errors': []}
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['sent_count'], 1)


class ChangeUpdateCompletedEndpointTestCase(TestCase):
    """Smoke tests for /changes/<id>/send-update-completed/ endpoint"""

    def setUp(self):
        self.admin_user = User.objects.create_user(
            username="admin_ep_uc",
            email="admin_ep_uc@example.com",
            password="testpass",
            name="Admin EP UC"
        )
        self.project = Project.objects.create(
            name="EP UC Project",
            status="ACTIVE",
            created_by=self.admin_user
        )
        self.change = Change.objects.create(
            title="EP UC Change",
            description="desc",
            project=self.project,
            status=ChangeStatus.DRAFT,
            risk_level=RiskLevel.MEDIUM,
            created_by=self.admin_user
        )
        self.client = Client()
        self.client.login(username="admin_ep_uc", password="testpass")
        self.url = reverse('change-send-update-completed', kwargs={'id': self.change.id})

    def test_unauthenticated_redirected(self):
        self.client.logout()
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 405)

    def test_nonexistent_change_404(self):
        url = reverse('change-send-update-completed', kwargs={'id': 99999})
        response = self.client.post(url)
        self.assertEqual(response.status_code, 404)

    @patch('core.views.get_graph_config')
    def test_disabled_service_returns_400(self, mock_get_config):
        mock_config = Mock()
        mock_config.enabled = False
        mock_get_config.return_value = mock_config
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

    @patch('core.services.changes.approval_mailer.send_change_update_completed_emails')
    @patch('core.views.get_graph_config')
    def test_successful_send_returns_200(self, mock_get_config, mock_send):
        mock_config = Mock()
        mock_config.enabled = True
        mock_config.tenant_id = "t"
        mock_config.client_id = "c"
        mock_config.client_secret = "s"
        mock_get_config.return_value = mock_config
        mock_send.return_value = {'success': True, 'sent_count': 1, 'failed_count': 0, 'errors': []}
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['sent_count'], 1)
