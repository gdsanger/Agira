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
from core.services.exceptions import ServiceError, ServiceDisabled, ServiceNotConfigured


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
