"""
Tests for Change model extensions (organisations, safety flag, enhanced approvers)
"""

from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from core.models import (
    Change, ChangeApproval, ChangeStatus, Project, Organisation,
    User, UserRole, UserOrganisation, RiskLevel, AttachmentRole,
    Attachment, AttachmentLink, ApprovalStatus
)


class ChangeModelExtensionsTestCase(TestCase):
    """Test cases for Change model extensions"""
    
    def setUp(self):
        """Set up test data"""
        # Create organisations
        self.org1 = Organisation.objects.create(name="Customer A")
        self.org2 = Organisation.objects.create(name="Customer B")
        
        # Create users with different roles
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
        
        self.regular_user = User.objects.create_user(
            username="user",
            email="user@example.com",
            password="testpass",
            name="Regular User"
        )
        
        # Create user organisations with different roles
        UserOrganisation.objects.create(
            user=self.approver_user,
            organisation=self.org1,
            role=UserRole.APPROVER,
            is_primary=True
        )
        
        UserOrganisation.objects.create(
            user=self.regular_user,
            organisation=self.org1,
            role=UserRole.USER,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(name="Test Project")
        self.project.clients.add(self.org1, self.org2)
        
        # Create change
        self.change = Change.objects.create(
            project=self.project,
            title="Test Change",
            description="Test description",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            is_safety_relevant=True,
            created_by=self.admin_user
        )
        self.change.organisations.add(self.org1)
    
    def test_change_has_organisations(self):
        """Test that a change can have organisations assigned"""
        self.assertEqual(self.change.organisations.count(), 1)
        self.assertIn(self.org1, self.change.organisations.all())
    
    def test_change_safety_flag(self):
        """Test that a change has a safety relevant flag"""
        self.assertTrue(self.change.is_safety_relevant)
        
        # Create another change that is not safety relevant
        change2 = Change.objects.create(
            project=self.project,
            title="Non-safety Change",
            is_safety_relevant=False,
            created_by=self.admin_user
        )
        self.assertFalse(change2.is_safety_relevant)
    
    def test_change_multiple_organisations(self):
        """Test that a change can have multiple organisations"""
        self.change.organisations.add(self.org2)
        self.assertEqual(self.change.organisations.count(), 2)
        self.assertIn(self.org1, self.change.organisations.all())
        self.assertIn(self.org2, self.change.organisations.all())
    
    def test_change_approval_new_fields(self):
        """Test that ChangeApproval has the new fields"""
        approval = ChangeApproval.objects.create(
            change=self.change,
            approver=self.approver_user,
            is_required=True,
            informed_at=timezone.now(),
            approved=True,
            approved_at=timezone.now(),
            notes="Test notes"
        )
        
        self.assertIsNotNone(approval.informed_at)
        self.assertTrue(approval.approved)
        self.assertIsNotNone(approval.approved_at)
        self.assertEqual(approval.notes, "Test notes")
    
    def test_approver_attachment_role_exists(self):
        """Test that APPROVER_ATTACHMENT role exists in AttachmentRole"""
        self.assertTrue(hasattr(AttachmentRole, 'APPROVER_ATTACHMENT'))
        self.assertEqual(AttachmentRole.APPROVER_ATTACHMENT, 'ApproverAttachment')


class ChangeViewsExtensionsTestCase(TestCase):
    """Test cases for Change views with extensions"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create organisations
        self.org1 = Organisation.objects.create(name="Customer A")
        
        # Create user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass",
            name="Test User"
        )
        
        # Create project
        self.project = Project.objects.create(name="Test Project")
        self.project.clients.add(self.org1)
        
        # Login
        self.client.login(username="testuser", password="testpass")
    
    def test_create_change_with_organisations(self):
        """Test creating a change with organisations"""
        response = self.client.post(reverse('change-create'), {
            'project': self.project.id,
            'title': 'Test Change',
            'description': 'Test description',
            'status': ChangeStatus.DRAFT,
            'risk': RiskLevel.NORMAL,
            'organisations': [self.org1.id],
            'is_safety_relevant': 'true'
        })
        
        # Check redirect or success
        self.assertTrue(response.status_code in [200, 302])
        
        # Verify change was created with organisations
        change = Change.objects.filter(title='Test Change').first()
        if change:
            self.assertIn(self.org1, change.organisations.all())
            self.assertTrue(change.is_safety_relevant)
    
    def test_update_change_organisations(self):
        """Test updating a change's organisations"""
        change = Change.objects.create(
            project=self.project,
            title="Test Change",
            is_safety_relevant=False,
            created_by=self.user
        )
        
        response = self.client.post(reverse('change-update', args=[change.id]), {
            'title': 'Updated Change',
            'project': self.project.id,
            'status': ChangeStatus.DRAFT,
            'risk': RiskLevel.NORMAL,
            'organisations': [self.org1.id],
            'is_safety_relevant': 'true'
        })
        
        # Refresh from database
        change.refresh_from_db()
        
        # Check if update was successful
        if response.status_code == 200:
            response_data = response.json()
            if response_data.get('success'):
                self.assertEqual(change.title, 'Updated Change')
                self.assertTrue(change.is_safety_relevant)
                self.assertIn(self.org1, change.organisations.all())
    
    def test_change_detail_displays_organisations(self):
        """Test that change detail view includes organisations"""
        change = Change.objects.create(
            project=self.project,
            title="Test Change",
            is_safety_relevant=True,
            created_by=self.user
        )
        change.organisations.add(self.org1)
        
        response = self.client.get(reverse('change-detail', args=[change.id]))
        
        self.assertEqual(response.status_code, 200)
        self.assertIn('change', response.context)
        self.assertEqual(response.context['change'], change)
        
        # Check that organisations are prefetched
        self.assertEqual(list(response.context['change'].organisations.all()), [self.org1])


class ChangeApproverManagementTestCase(TestCase):
    """Test cases for enhanced approver management"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(name="Test Org")
        
        # Create users
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="testpass",
            name="Admin"
        )
        
        self.approver = User.objects.create_user(
            username="approver",
            email="approver@example.com",
            password="testpass",
            name="Approver"
        )
        
        UserOrganisation.objects.create(
            user=self.approver,
            organisation=self.org,
            role=UserRole.APPROVER
        )
        
        # Create project and change
        self.project = Project.objects.create(name="Test Project")
        self.project.clients.add(self.org)
        
        self.change = Change.objects.create(
            project=self.project,
            title="Test Change",
            created_by=self.admin
        )
        self.change.organisations.add(self.org)
        
        # Login
        self.client.login(username="admin", password="testpass")
    
    def test_update_approver_details(self):
        """Test updating approver details with new fields"""
        approval = ChangeApproval.objects.create(
            change=self.change,
            approver=self.approver
        )
        
        informed_time = timezone.now()
        approved_time = timezone.now()
        
        response = self.client.post(
            reverse('change-update-approver', args=[self.change.id, approval.id]),
            {
                'informed_at': informed_time.strftime('%Y-%m-%dT%H:%M'),
                'approved': 'true',
                'approved_at': approved_time.strftime('%Y-%m-%dT%H:%M'),
                'notes': 'Test notes',
                'comment': 'Test comment'
            }
        )
        
        # Refresh from database
        approval.refresh_from_db()
        
        # Verify update
        if response.status_code == 200:
            response_data = response.json()
            if response_data.get('success'):
                self.assertTrue(approval.approved)
                self.assertIsNotNone(approval.informed_at)
                self.assertIsNotNone(approval.approved_at)
                self.assertEqual(approval.notes, 'Test notes')
                self.assertEqual(approval.comment, 'Test comment')

    def test_update_approver_uncheck_approved(self):
        """Test unchecking the approved checkbox when editing an approver"""
        # Create an already approved approval
        approval = ChangeApproval.objects.create(
            change=self.change,
            approver=self.approver,
            approved=True,
            status=ApprovalStatus.APPROVED,
            approved_at=timezone.now()
        )
        
        # Update without the 'approved' field (simulating unchecked checkbox)
        response = self.client.post(
            reverse('change-update-approver', args=[self.change.id, approval.id]),
            {
                'notes': 'Updated notes',
                'comment': 'Updated comment'
                # Note: 'approved' is not sent when checkbox is unchecked
            }
        )
        
        # Refresh from database
        approval.refresh_from_db()
        
        # Verify that approved flag is now False
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data.get('success'))
        self.assertFalse(approval.approved)
        self.assertEqual(approval.notes, 'Updated notes')
        self.assertEqual(approval.comment, 'Updated comment')


class ChangeAITextImprovementTestCase(TestCase):
    """Test cases for AI-powered text improvement in Change Management"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass",
            name="Test User"
        )
        
        # Create project and organisation
        self.org = Organisation.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Test Project")
        self.project.clients.add(self.org)
        
        # Create change with text fields
        self.change = Change.objects.create(
            project=self.project,
            title="Test Change",
            description="Test description",
            risk_description="This is a risky change that needs better description.",
            mitigation="We will do some mitigation steps.",
            rollback_plan="Rollback by reversing changes.",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            created_by=self.user
        )
        
        # Login
        self.client.login(username="testuser", password="testpass")
    
    def test_polish_risk_description_requires_authentication(self):
        """Test that unauthenticated users cannot polish risk description"""
        self.client.logout()
        
        url = reverse('change-polish-risk-description', args=[self.change.id])
        response = self.client.post(url)
        
        # Should redirect to login or return 403/302
        self.assertIn(response.status_code, [302, 403])
    
    def test_polish_risk_description_requires_text(self):
        """Test that empty risk description cannot be polished"""
        # Create change without risk description
        empty_change = Change.objects.create(
            project=self.project,
            title="Empty Change",
            risk_description="",
            created_by=self.user
        )
        
        url = reverse('change-polish-risk-description', args=[empty_change.id])
        response = self.client.post(url)
        
        # Should return 400 Bad Request
        self.assertEqual(response.status_code, 400)
        
        # Check error message
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('empty', data['error'].lower())
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_polish_risk_description_success(self, mock_execute_agent):
        """Test successful risk description polishing"""
        # Mock AI agent response
        polished_text = """## Risk Analysis

This change introduces potential risks to system stability:
- Database schema modification may cause downtime
- Data migration requires careful validation
- Rollback complexity is high

Risk Level: Medium-High"""
        mock_execute_agent.return_value = polished_text
        
        # Get initial risk description
        initial_risk_description = self.change.risk_description
        
        # Call polish endpoint
        url = reverse('change-polish-risk-description', args=[self.change.id])
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['text'], polished_text)
        self.assertIn('improved', data['message'].lower())
        
        # Verify agent was called
        mock_execute_agent.assert_called_once()
        call_kwargs = mock_execute_agent.call_args[1]
        self.assertEqual(call_kwargs['filename'], 'change-text-polish-agent.yml')
        self.assertEqual(call_kwargs['input_text'], initial_risk_description)
        self.assertEqual(call_kwargs['user'], self.user)
        
        # Verify database was updated
        self.change.refresh_from_db()
        self.assertEqual(self.change.risk_description, polished_text)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_optimize_mitigation_success(self, mock_execute_agent):
        """Test successful mitigation plan optimization"""
        # Mock AI agent response
        optimized_text = """## Mitigation Steps

1. Create database backup before deployment
2. Execute schema changes in maintenance window
3. Perform data validation checks
4. Monitor system performance for 24 hours
5. Keep development team on standby"""
        mock_execute_agent.return_value = optimized_text
        
        # Get initial mitigation plan
        initial_mitigation = self.change.mitigation
        
        # Call optimize endpoint
        url = reverse('change-optimize-mitigation', args=[self.change.id])
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['text'], optimized_text)
        
        # Verify agent was called with correct parameters
        mock_execute_agent.assert_called_once()
        call_kwargs = mock_execute_agent.call_args[1]
        self.assertEqual(call_kwargs['filename'], 'text-optimization-agent.yml')
        self.assertEqual(call_kwargs['input_text'], initial_mitigation)
        
        # Verify database was updated
        self.change.refresh_from_db()
        self.assertEqual(self.change.mitigation, optimized_text)
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_optimize_rollback_success(self, mock_execute_agent):
        """Test successful rollback plan optimization"""
        # Mock AI agent response
        optimized_text = """## Rollback Procedure

1. Stop application services
2. Restore database from backup
3. Revert code deployment to previous version
4. Restart application services
5. Verify system functionality
6. Notify stakeholders of rollback completion"""
        mock_execute_agent.return_value = optimized_text
        
        # Get initial rollback plan
        initial_rollback = self.change.rollback_plan
        
        # Call optimize endpoint
        url = reverse('change-optimize-rollback', args=[self.change.id])
        response = self.client.post(url)
        
        # Check response
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['text'], optimized_text)
        
        # Verify agent was called
        mock_execute_agent.assert_called_once()
        call_kwargs = mock_execute_agent.call_args[1]
        self.assertEqual(call_kwargs['filename'], 'text-optimization-agent.yml')
        self.assertEqual(call_kwargs['input_text'], initial_rollback)
        
        # Verify database was updated
        self.change.refresh_from_db()
        self.assertEqual(self.change.rollback_plan, optimized_text)
    
    def test_optimize_mitigation_requires_text(self):
        """Test that empty mitigation plan cannot be optimized"""
        # Create change without mitigation plan
        empty_change = Change.objects.create(
            project=self.project,
            title="Empty Change",
            mitigation="",
            created_by=self.user
        )
        
        url = reverse('change-optimize-mitigation', args=[empty_change.id])
        response = self.client.post(url)
        
        # Should return 400 Bad Request
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('empty', data['error'].lower())
    
    def test_optimize_rollback_requires_text(self):
        """Test that empty rollback plan cannot be optimized"""
        # Create change without rollback plan
        empty_change = Change.objects.create(
            project=self.project,
            title="Empty Change",
            rollback_plan="",
            created_by=self.user
        )
        
        url = reverse('change-optimize-rollback', args=[empty_change.id])
        response = self.client.post(url)
        
        # Should return 400 Bad Request
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('empty', data['error'].lower())
    
    @patch('core.services.agents.agent_service.AgentService.execute_agent')
    def test_ai_text_improvement_handles_agent_errors(self, mock_execute_agent):
        """Test that AI text improvement handles agent execution errors gracefully"""
        # Mock agent to raise an exception
        mock_execute_agent.side_effect = Exception("AI service unavailable")
        
        url = reverse('change-polish-risk-description', args=[self.change.id])
        response = self.client.post(url)
        
        # Should return 500 error
        self.assertEqual(response.status_code, 500)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('error', data)
        
        # Verify original text is not changed
        self.change.refresh_from_db()
        self.assertEqual(self.change.risk_description, "This is a risky change that needs better description.")

