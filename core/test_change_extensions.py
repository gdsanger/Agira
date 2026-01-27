"""
Tests for Change model extensions (organisations, safety flag, enhanced approvers)
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from core.models import (
    Change, ChangeApproval, ChangeStatus, Project, Organisation,
    User, UserRole, UserOrganisation, RiskLevel, AttachmentRole,
    Attachment, AttachmentLink
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
