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
    
    def test_all_approvers_from_all_orgs_with_same_role(self):
        """
        Test that ALL users with the required role from ALL organizations are assigned.
        
        Scenario: Change has 6 organizations, each with at least one APPROVER.
        Expected: ALL approvers from ALL organizations should be assigned.
        """
        # Create 6 organizations (using range(3, 9) which generates 3, 4, 5, 6, 7, 8)
        # This avoids conflict with existing Org 1 and Org 2 from setUp()
        orgs = []
        for i in range(3, 9):  # Creates: Org 3, Org 4, Org 5, Org 6, Org 7, Org 8
            org = Organisation.objects.create(name=f"Org {i}")
            orgs.append(org)
        
        # Create users - at least one APPROVER per organization
        approvers = []
        for org in orgs:
            org_num = org.name.split()[-1]  # Extract number from "Org 3", "Org 4", etc.
            # Create 2 approvers per org to make it more realistic
            for j in range(2):
                user = User.objects.create_user(
                    username=f"approver_org{org_num}_{j+1}",
                    email=f"approver_org{org_num}_{j+1}@example.com",
                    password="testpass",
                    name=f"Approver Org{org_num}-{j+1}",
                    role=UserRole.USER  # Global role is USER
                )
                UserOrganisation.objects.create(
                    user=user,
                    organisation=org,
                    role=UserRole.APPROVER,  # Org-specific role is APPROVER
                    is_primary=(j == 0)
                )
                approvers.append(user)
        
        # Also create INFO and DEV users for each org to satisfy mandatory roles
        info_users = []
        dev_users = []
        for org in orgs:
            org_num = org.name.split()[-1]  # Extract number from "Org 3", "Org 4", etc.
            info_user = User.objects.create_user(
                username=f"info_org{org_num}",
                email=f"info_org{org_num}@example.com",
                password="testpass",
                name=f"Info Org{org_num}",
                role=UserRole.USER
            )
            UserOrganisation.objects.create(
                user=info_user,
                organisation=org,
                role=UserRole.INFO,
                is_primary=True
            )
            info_users.append(info_user)
            
            dev_user = User.objects.create_user(
                username=f"dev_org{org_num}",
                email=f"dev_org{org_num}@example.com",
                password="testpass",
                name=f"Dev Org{org_num}",
                role=UserRole.USER
            )
            UserOrganisation.objects.create(
                user=dev_user,
                organisation=org,
                role=UserRole.DEV,
                is_primary=True
            )
            dev_users.append(dev_user)
        
        # Create a change policy that requires APPROVER role
        policy = ChangePolicy.objects.create(
            risk_level=RiskLevel.NORMAL,
            security_relevant=False,
            release_type=None
        )
        ChangePolicyRole.objects.create(
            policy=policy,
            role=UserRole.APPROVER
        )
        
        # Create change with all 6 organizations
        change = Change.objects.create(
            project=self.project,
            title="Change with 6 Organizations",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            is_safety_relevant=False,
            created_by=approvers[0]
        )
        change.organisations.add(*orgs)
        
        # Sync approvers
        result = ChangePolicyService.sync_change_approvers(change)
        
        # Check that approvers were added
        self.assertGreater(result['approvers_added'], 0)
        
        # Get all approvals
        approvals = ChangeApproval.objects.filter(change=change)
        assigned_approvers = [a.approver for a in approvals]
        
        # ALL approvers from ALL organizations should be assigned (12 total: 2 per org)
        for approver in approvers:
            self.assertIn(
                approver, 
                assigned_approvers,
                f"Approver {approver.username} should be assigned but is missing"
            )
        
        # ALL INFO users should be assigned (6 total: 1 per org)
        for info_user in info_users:
            self.assertIn(
                info_user,
                assigned_approvers,
                f"INFO user {info_user.username} should be assigned but is missing"
            )
        
        # ALL DEV users should be assigned (6 total: 1 per org)
        for dev_user in dev_users:
            self.assertIn(
                dev_user,
                assigned_approvers,
                f"DEV user {dev_user.username} should be assigned but is missing"
            )
        
        # Total: 12 approvers + 6 INFO + 6 DEV = 24 approvals
        self.assertEqual(
            len(approvals), 
            24,
            f"Expected 24 approvals (12 APPROVER + 6 INFO + 6 DEV), but got {len(approvals)}"
        )


class ChangePolicyInfoDevAttributesTestCase(TestCase):
    """Tests for correct attributes on INFO/DEV ChangeApproval records."""

    def setUp(self):
        self.org = Organisation.objects.create(name="Org A")
        self.project = Project.objects.create(name="Project A")
        self.creator = User.objects.create_user(
            username="creator", email="creator@example.com", password="testpass",
            name="Creator", role=UserRole.USER
        )
        self.info_user = User.objects.create_user(
            username="info_user", email="info@example.com", password="testpass",
            name="Info User", role=UserRole.USER
        )
        self.dev_user = User.objects.create_user(
            username="dev_user", email="dev@example.com", password="testpass",
            name="Dev User", role=UserRole.USER
        )
        UserOrganisation.objects.create(
            user=self.info_user, organisation=self.org, role=UserRole.INFO, is_primary=True
        )
        UserOrganisation.objects.create(
            user=self.dev_user, organisation=self.org, role=UserRole.DEV, is_primary=True
        )
        self.change = Change.objects.create(
            project=self.project,
            title="Info/Dev Test Change",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            is_safety_relevant=False,
            created_by=self.creator,
        )
        self.change.organisations.add(self.org)

    def test_info_approval_attributes(self):
        """INFO ChangeApproval must have is_required=False, notes, status=INFO, approved_at set."""
        ChangePolicyService.sync_change_approvers(self.change)
        approval = ChangeApproval.objects.get(change=self.change, approver=self.info_user, role=UserRole.INFO)
        self.assertFalse(approval.is_required)
        self.assertEqual(approval.notes, "Nur zur Info")
        self.assertEqual(approval.status, ApprovalStatus.INFO)
        self.assertIsNotNone(approval.approved_at)

    def test_dev_approval_attributes(self):
        """DEV ChangeApproval must have is_required=False, notes, status=INFO, approved_at set."""
        ChangePolicyService.sync_change_approvers(self.change)
        approval = ChangeApproval.objects.get(change=self.change, approver=self.dev_user, role=UserRole.DEV)
        self.assertFalse(approval.is_required)
        self.assertEqual(approval.notes, "Nur zur Info")
        self.assertEqual(approval.status, ApprovalStatus.INFO)
        self.assertIsNotNone(approval.approved_at)

    def test_info_dev_always_assigned_without_policy(self):
        """INFO and DEV must be assigned even when no ChangePolicy matches."""
        # No policy created → find_matching_policy returns None
        result = ChangePolicyService.sync_change_approvers(self.change)
        self.assertFalse(result['policy_found'])
        approvers = list(ChangeApproval.objects.filter(change=self.change).values_list('approver_id', flat=True))
        self.assertIn(self.info_user.id, approvers)
        self.assertIn(self.dev_user.id, approvers)

    def test_idempotency(self):
        """Calling sync twice must not create duplicate ChangeApproval rows."""
        ChangePolicyService.sync_change_approvers(self.change)
        count_first = ChangeApproval.objects.filter(change=self.change).count()
        ChangePolicyService.sync_change_approvers(self.change)
        count_second = ChangeApproval.objects.filter(change=self.change).count()
        self.assertEqual(count_first, count_second)

    def test_removal_skipped_when_approved_at_set(self):
        """ChangeApproval with approved_at set must NOT be removed even if no longer in target."""
        from django.utils import timezone
        # Manually create an approval for an org-less user (will be out of target)
        other_user = User.objects.create_user(
            username="other", email="other@example.com", password="testpass",
            name="Other", role=UserRole.USER
        )
        # Give other_user an INFO role in a different org not on the change
        other_org = Organisation.objects.create(name="Org B")
        UserOrganisation.objects.create(
            user=other_user, organisation=other_org, role=UserRole.INFO, is_primary=True
        )
        approval = ChangeApproval.objects.create(
            change=self.change,
            approver=other_user,
            role=UserRole.INFO,
            is_required=False,
            status=ApprovalStatus.INFO,
            notes="Nur zur Info",
            approved_at=timezone.now(),
        )
        # Sync – other_user is not in target, but approved_at is set → must be kept
        result = ChangePolicyService.sync_change_approvers(self.change)
        self.assertEqual(result['approvers_removed'], 0)
        self.assertTrue(ChangeApproval.objects.filter(id=approval.id).exists())

    def test_approver_role_only_when_in_required_roles(self):
        """APPROVER users are only synced when APPROVER is in required_roles (policy-dependent)."""
        approver_user = User.objects.create_user(
            username="approver2", email="approver2@example.com", password="testpass",
            name="Approver2", role=UserRole.USER
        )
        UserOrganisation.objects.create(
            user=approver_user, organisation=self.org, role=UserRole.APPROVER, is_primary=True
        )
        # No policy → APPROVER NOT in required_roles
        result = ChangePolicyService.sync_change_approvers(self.change)
        self.assertNotIn(UserRole.APPROVER, result['required_roles'])
        approver_ids = list(
            ChangeApproval.objects.filter(change=self.change, role=UserRole.APPROVER)
            .values_list('approver_id', flat=True)
        )
        self.assertNotIn(approver_user.id, approver_ids)


class ChangePolicyOrganisationScopeTestCase(TestCase):
    """Ensure role resolution is strictly scoped to change organisations."""

    def setUp(self):
        self.org_on_change = Organisation.objects.create(name="Scoped Org")
        self.org_off_change = Organisation.objects.create(name="Outside Org")
        self.project = Project.objects.create(name="Project Scope")
        self.creator = User.objects.create_user(
            username="scope_creator", email="scope_creator@example.com", password="testpass",
            name="Scope Creator", role=UserRole.USER
        )
        self.info_user = User.objects.create_user(
            username="scope_info", email="scope_info@example.com", password="testpass",
            name="Scope Info", role=UserRole.USER
        )
        UserOrganisation.objects.create(
            user=self.info_user,
            organisation=self.org_off_change,
            role=UserRole.INFO,
            is_primary=True,
        )

    def test_no_organisations_means_no_auto_assignment(self):
        """Without change organisations, no UserOrganisation role may be used for assignment."""
        change = Change.objects.create(
            project=self.project,
            title="No org change",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            is_safety_relevant=False,
            created_by=self.creator,
        )

        result = ChangePolicyService.sync_change_approvers(change)

        self.assertEqual(result['approvers_added'], 0)
        self.assertEqual(ChangeApproval.objects.filter(change=change).count(), 0)

    def test_users_outside_change_orgs_not_assigned(self):
        """Users with matching role outside of change organisations must not be assigned."""
        change = Change.objects.create(
            project=self.project,
            title="Scoped org change",
            status=ChangeStatus.DRAFT,
            risk=RiskLevel.NORMAL,
            is_safety_relevant=False,
            created_by=self.creator,
        )
        change.organisations.add(self.org_on_change)

        result = ChangePolicyService.sync_change_approvers(change)

        self.assertEqual(result['approvers_added'], 0)
        self.assertFalse(
            ChangeApproval.objects.filter(
                change=change,
                approver=self.info_user,
                role=UserRole.INFO,
            ).exists()
        )
