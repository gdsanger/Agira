"""
Tests for ChangePolicyService and organization-specific role handling.
Tests requirement AC1: Organization-specific roles for approver assignment.
"""

from datetime import date, datetime
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Change, ChangeApproval, ChangePolicy, ChangePolicyRole, ChangeStatus,
    Project, Organisation, User, UserRole, UserOrganisation, RiskLevel,
    ApprovalStatus, Release, ReleaseType
)
from core.services.change_policy_service import ChangePolicyService


class ChangePolicyServiceRoleResolutionTestCase(TestCase):
    """Test cases for organization-specific role resolution in ChangePolicyService"""
    
    def setUp(self):
        """Set up test data"""
        # Create organisations
        self.org1 = Organisation.objects.create(name="Org 1")
        self.org2 = Organisation.objects.create(name="Org 2")
        
        # Create users with different global roles
        self.user1 = User.objects.create_user(
            username="user1",
            email="user1@example.com",
            password="testpass",
            name="User 1",
            role=UserRole.USER  # Global role is USER
        )
        
        self.user2 = User.objects.create_user(
            username="user2",
            email="user2@example.com",
            password="testpass",
            name="User 2",
            role=UserRole.USER  # Global role is USER
        )
        
        self.user3 = User.objects.create_user(
            username="user3",
            email="user3@example.com",
            password="testpass",
            name="User 3",
            role=UserRole.APPROVER  # Global role is APPROVER
        )
        
        # Create user organisations with organization-specific roles
        # user1 is APPROVER in org1, USER in org2
        UserOrganisation.objects.create(
            user=self.user1,
            organisation=self.org1,
            role=UserRole.APPROVER,
            is_primary=True
        )
        UserOrganisation.objects.create(
            user=self.user1,
            organisation=self.org2,
            role=UserRole.USER,
            is_primary=False
        )
        
        # user2 is INFO in org1
        UserOrganisation.objects.create(
            user=self.user2,
            organisation=self.org1,
            role=UserRole.INFO,
            is_primary=True
        )
        
        # user3 is DEV in org1 (global role is APPROVER but org role is DEV)
        UserOrganisation.objects.create(
            user=self.user3,
            organisation=self.org1,
            role=UserRole.DEV,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(name="Test Project")
        
        # Create change
        self.change = Change.objects.create(
            project=self.project,
            title="Test Change",
            description="Test description",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            is_safety_relevant=False,
            created_by=self.user1
        )
        self.change.organisations.add(self.org1)
    
    def test_get_users_with_role_in_change_orgs(self):
        """Test getting users with specific role in change organizations"""
        # Should find user1 (APPROVER in org1)
        approvers = ChangePolicyService.get_users_with_role_in_change_orgs(
            self.change, UserRole.APPROVER
        )
        self.assertEqual(len(approvers), 1)
        self.assertIn(self.user1, approvers)
        
        # Should find user2 (INFO in org1)
        info_users = ChangePolicyService.get_users_with_role_in_change_orgs(
            self.change, UserRole.INFO
        )
        self.assertEqual(len(info_users), 1)
        self.assertIn(self.user2, info_users)
        
        # Should find user3 (DEV in org1)
        dev_users = ChangePolicyService.get_users_with_role_in_change_orgs(
            self.change, UserRole.DEV
        )
        self.assertEqual(len(dev_users), 1)
        self.assertIn(self.user3, dev_users)
    
    def test_get_users_ignores_global_role(self):
        """Test that organization-specific role is used, not global role"""
        # user3 has global role APPROVER but org role DEV
        # Should NOT be found when searching for APPROVERs
        approvers = ChangePolicyService.get_users_with_role_in_change_orgs(
            self.change, UserRole.APPROVER
        )
        self.assertNotIn(self.user3, approvers)
        
        # But should be found when searching for DEVs
        dev_users = ChangePolicyService.get_users_with_role_in_change_orgs(
            self.change, UserRole.DEV
        )
        self.assertIn(self.user3, dev_users)
    
    def test_get_approver_role_in_change_context(self):
        """Test getting approver's role in change context"""
        # user1 is APPROVER in org1
        role = ChangePolicyService.get_approver_role_in_change_context(
            self.change, self.user1
        )
        self.assertEqual(role, UserRole.APPROVER)
        
        # user2 is INFO in org1
        role = ChangePolicyService.get_approver_role_in_change_context(
            self.change, self.user2
        )
        self.assertEqual(role, UserRole.INFO)
        
        # user3 is DEV in org1 (despite global role being APPROVER)
        role = ChangePolicyService.get_approver_role_in_change_context(
            self.change, self.user3
        )
        self.assertEqual(role, UserRole.DEV)
    
    def test_sync_change_approvers_uses_org_roles(self):
        """Test that sync_change_approvers uses organization-specific roles"""
        # Create a simple policy that requires INFO and DEV (always added)
        # No additional roles needed beyond the defaults
        
        # Run sync
        result = ChangePolicyService.sync_change_approvers(self.change)
        
        # Should have added approvers
        self.assertGreater(result['approvers_added'], 0)
        
        # Check that INFO and DEV roles were assigned
        approvals = ChangeApproval.objects.filter(change=self.change)
        
        # Get roles of assigned approvers in change context
        assigned_roles = set()
        for approval in approvals:
            role = ChangePolicyService.get_approver_role_in_change_context(
                self.change, approval.approver
            )
            assigned_roles.add(role)
        
        # INFO and DEV should be present (mandatory roles)
        self.assertIn(UserRole.INFO, assigned_roles)
        self.assertIn(UserRole.DEV, assigned_roles)
    
    def test_sync_does_not_remove_decided_approvers(self):
        """Test that approvers with decisions are not removed during sync"""
        # Add an approval with a decision date
        approval = ChangeApproval.objects.create(
            change=self.change,
            approver=self.user1,
            is_required=True,
            status=ApprovalStatus.ACCEPT,
            approved_at=timezone.now()  # Decision made
        )
        
        # Change the change's risk level so policy might change
        self.change.risk = RiskLevel.HIGH
        self.change.save()
        
        # Sync approvers
        result = ChangePolicyService.sync_change_approvers(self.change)
        
        # The approval with decision should still exist
        self.assertTrue(
            ChangeApproval.objects.filter(id=approval.id).exists()
        )
        
        # No removals should have happened
        self.assertEqual(result['approvers_removed'], 0)


class ChangeApprovalDecisionDateTestCase(TestCase):
    """Test cases for decision date requirement in approval actions"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(name="Test Org")
        
        # Create users
        self.approver = User.objects.create_user(
            username="approver",
            email="approver@example.com",
            password="testpass",
            name="Approver User",
            role=UserRole.APPROVER
        )
        
        UserOrganisation.objects.create(
            user=self.approver,
            organisation=self.org,
            role=UserRole.APPROVER,
            is_primary=True
        )
        
        # Create project and change
        self.project = Project.objects.create(name="Test Project")
        self.change = Change.objects.create(
            project=self.project,
            title="Test Change",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            is_safety_relevant=False,
            created_by=self.approver
        )
        self.change.organisations.add(self.org)
        
        # Create approval
        self.approval = ChangeApproval.objects.create(
            change=self.change,
            approver=self.approver,
            is_required=True,
            status=ApprovalStatus.PENDING
        )
        
        # Login
        self.client.login(username="approver", password="testpass")
    
    def test_approve_requires_decision_date(self):
        """Test that approve action requires decision date"""
        url = reverse('change-approve', args=[self.change.id, self.approval.id])
        
        # Try to approve without decision_date
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        
        # Check error message
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Decision date is required', data['error'])
        
        # Approval should still be pending
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, ApprovalStatus.PENDING)
        self.assertIsNone(self.approval.approved_at)
    
    def test_approve_with_decision_date_succeeds(self):
        """Test that approve action succeeds with decision date"""
        url = reverse('change-approve', args=[self.change.id, self.approval.id])
        
        # Approve with decision_date
        decision_date = '2024-03-15'
        response = self.client.post(url, {'decision_date': decision_date})
        self.assertEqual(response.status_code, 200)
        
        # Check success
        data = response.json()
        self.assertTrue(data['success'])
        
        # Approval should be accepted with date
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, ApprovalStatus.ACCEPT)
        self.assertIsNotNone(self.approval.approved_at)
        
        # Check that date is stored correctly (date only, with timezone)
        from datetime import time
        expected_date = timezone.make_aware(datetime(2024, 3, 15, 0, 0, 0))
        self.assertEqual(self.approval.approved_at, expected_date)
    
    def test_reject_requires_decision_date(self):
        """Test that reject action requires decision date"""
        url = reverse('change-reject', args=[self.change.id, self.approval.id])
        
        # Try to reject with comment but without decision_date
        response = self.client.post(url, {'comment': 'Not ready'})
        self.assertEqual(response.status_code, 400)
        
        # Check error message
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Decision date is required', data['error'])
    
    def test_reject_with_decision_date_succeeds(self):
        """Test that reject action succeeds with decision date"""
        url = reverse('change-reject', args=[self.change.id, self.approval.id])
        
        # Reject with decision_date and comment
        decision_date = '2024-03-16'
        response = self.client.post(url, {
            'decision_date': decision_date,
            'comment': 'Not ready yet'
        })
        self.assertEqual(response.status_code, 200)
        
        # Check success
        data = response.json()
        self.assertTrue(data['success'])
        
        # Approval should be rejected with date
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, ApprovalStatus.REJECT)
        self.assertIsNotNone(self.approval.approved_at)
        self.assertEqual(self.approval.comment, 'Not ready yet')
        
        # Check that date is stored correctly
        expected_date = timezone.make_aware(datetime(2024, 3, 16, 0, 0, 0))
        self.assertEqual(self.approval.approved_at, expected_date)
    
    def test_abstain_requires_decision_date(self):
        """Test that abstain action requires decision date"""
        url = reverse('change-abstain', args=[self.change.id, self.approval.id])
        
        # Try to abstain without decision_date
        response = self.client.post(url)
        self.assertEqual(response.status_code, 400)
        
        # Check error message
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Decision date is required', data['error'])
    
    def test_abstain_with_decision_date_succeeds(self):
        """Test that abstain action succeeds with decision date"""
        url = reverse('change-abstain', args=[self.change.id, self.approval.id])
        
        # Abstain with decision_date (comment optional)
        decision_date = '2024-03-17'
        response = self.client.post(url, {
            'decision_date': decision_date,
            'comment': 'Cannot decide at this time'
        })
        self.assertEqual(response.status_code, 200)
        
        # Check success
        data = response.json()
        self.assertTrue(data['success'])
        
        # Approval should be abstained with date
        self.approval.refresh_from_db()
        self.assertEqual(self.approval.status, ApprovalStatus.ABSTAINED)
        self.assertIsNotNone(self.approval.approved_at)
        self.assertEqual(self.approval.comment, 'Cannot decide at this time')
        
        # Check that date is stored correctly
        expected_date = timezone.make_aware(datetime(2024, 3, 17, 0, 0, 0))
        self.assertEqual(self.approval.approved_at, expected_date)
    
    def test_invalid_date_format_returns_error(self):
        """Test that invalid date format returns error"""
        url = reverse('change-approve', args=[self.change.id, self.approval.id])
        
        # Try with invalid date format
        response = self.client.post(url, {'decision_date': '15/03/2024'})
        self.assertEqual(response.status_code, 400)
        
        # Check error message
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid date format', data['error'])


class ChangePolicyMultiOrgTestCase(TestCase):
    """Test cases for change policy with multiple organizations"""
    
    def setUp(self):
        """Set up test data"""
        # Create organisations
        self.org1 = Organisation.objects.create(name="Org 1")
        self.org2 = Organisation.objects.create(name="Org 2")
        
        # Create users with roles in different orgs
        self.user1 = User.objects.create_user(
            username="user1",
            email="user1@example.com",
            password="testpass",
            name="User 1",
            role=UserRole.USER
        )
        
        self.user2 = User.objects.create_user(
            username="user2",
            email="user2@example.com",
            password="testpass",
            name="User 2",
            role=UserRole.USER
        )
        
        # user1 is INFO in org1 only
        UserOrganisation.objects.create(
            user=self.user1,
            organisation=self.org1,
            role=UserRole.INFO,
            is_primary=True
        )
        
        # user2 is DEV in org2 only
        UserOrganisation.objects.create(
            user=self.user2,
            organisation=self.org2,
            role=UserRole.DEV,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(name="Test Project")
    
    def test_change_with_multiple_orgs_finds_all_approvers(self):
        """Test that change with multiple orgs finds approvers from all orgs"""
        # Create change with both orgs
        change = Change.objects.create(
            project=self.project,
            title="Multi-Org Change",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            is_safety_relevant=False,
            created_by=self.user1
        )
        change.organisations.add(self.org1, self.org2)
        
        # Sync approvers
        result = ChangePolicyService.sync_change_approvers(change)
        
        # Should have added approvers
        self.assertGreater(result['approvers_added'], 0)
        
        # Check approvals
        approvals = ChangeApproval.objects.filter(change=change)
        approvers = [a.approver for a in approvals]
        
        # Both users should be found because they have required roles in their orgs
        # user1 has INFO in org1, user2 has DEV in org2
        self.assertIn(self.user1, approvers)
        self.assertIn(self.user2, approvers)
