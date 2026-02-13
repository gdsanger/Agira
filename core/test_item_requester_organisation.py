"""
Tests for automatic organisation population when requester is changed.

This test module validates that when an Item's requester is changed,
the Item's organisation is automatically updated to the new requester's
primary organisation (if one exists).

Test cases cover:
- TF1: Requester change updates organisation
- TF2: No requester change keeps organisation unchanged
- Edge cases: requester with no primary organisation
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item, 
    ItemStatus
)

User = get_user_model()


class ItemRequesterOrganisationChangeTest(TestCase):
    """Test automatic organisation update when requester changes."""
    
    def setUp(self):
        """Set up test data."""
        # Create organisations
        self.org1 = Organisation.objects.create(name='Organisation 1', short='ORG1')
        self.org2 = Organisation.objects.create(name='Organisation 2', short='ORG2')
        self.org3 = Organisation.objects.create(name='Organisation 3', short='ORG3')
        
        # Create requester A with primary organisation = org1
        self.requester_a = User.objects.create_user(
            username='requester_a',
            email='requester_a@example.com',
            password='testpass',
            name='Requester A',
            role='User'
        )
        UserOrganisation.objects.create(
            user=self.requester_a,
            organisation=self.org1,
            is_primary=True
        )
        
        # Create requester B with primary organisation = org2
        self.requester_b = User.objects.create_user(
            username='requester_b',
            email='requester_b@example.com',
            password='testpass',
            name='Requester B',
            role='User'
        )
        UserOrganisation.objects.create(
            user=self.requester_b,
            organisation=self.org2,
            is_primary=True
        )
        
        # Create requester C with NO primary organisation
        self.requester_c = User.objects.create_user(
            username='requester_c',
            email='requester_c@example.com',
            password='testpass',
            name='Requester C (No Primary Org)',
            role='User'
        )
        # Add requester_c to org1 and org3 but NEITHER as primary
        UserOrganisation.objects.create(
            user=self.requester_c,
            organisation=self.org1,
            is_primary=False
        )
        UserOrganisation.objects.create(
            user=self.requester_c,
            organisation=self.org3,
            is_primary=False
        )
        
        # Create admin user for testing
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='testpass',
            name='Admin User',
            role='Admin'
        )
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        self.project.clients.add(self.org1, self.org2, self.org3)
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='task',
            name='Task',
            is_active=True
        )
        
        self.client = Client()
        self.client.login(username='admin', password='testpass')
    
    def test_tf1_requester_change_updates_organisation(self):
        """
        TF1: Change requester from A (Org1) to B (Org2).
        Expected: item.organisation changes to Org2.
        """
        # Setup: Create item with requester A and organisation Org1
        item = Item.objects.create(
            project=self.project,
            title='Test Item TF1',
            type=self.item_type,
            requester=self.requester_a,
            organisation=self.org1,
            status=ItemStatus.INBOX
        )
        
        # Verify initial state
        self.assertEqual(item.requester, self.requester_a)
        self.assertEqual(item.organisation, self.org1)
        
        # Action: Change requester to B
        item.requester = self.requester_b
        item.save()
        
        # Refresh from database
        item.refresh_from_db()
        
        # Expectation: organisation should now be Org2 (requester B's primary org)
        self.assertEqual(item.requester, self.requester_b)
        self.assertEqual(item.organisation, self.org2,
                        "Organisation should update to new requester's primary organisation")
    
    def test_tf2_no_requester_change_keeps_organisation(self):
        """
        TF2: Save item without changing requester.
        Expected: item.organisation remains unchanged.
        """
        # Setup: Create item with requester A and organisation Org1
        item = Item.objects.create(
            project=self.project,
            title='Test Item TF2',
            type=self.item_type,
            requester=self.requester_a,
            organisation=self.org1,
            status=ItemStatus.INBOX
        )
        
        # Verify initial state
        self.assertEqual(item.requester, self.requester_a)
        self.assertEqual(item.organisation, self.org1)
        
        # Action: Save without changing requester
        item.title = 'Updated Title'
        item.save()
        
        # Refresh from database
        item.refresh_from_db()
        
        # Expectation: organisation should still be Org1
        self.assertEqual(item.requester, self.requester_a)
        self.assertEqual(item.organisation, self.org1,
                        "Organisation should remain unchanged when requester is not changed")
    
    def test_requester_change_no_primary_org_keeps_organisation(self):
        """
        Test: Change requester to user with NO primary organisation.
        Expected: item.organisation remains unchanged (as per requirements).
        """
        # Setup: Create item with requester A and organisation Org1
        item = Item.objects.create(
            project=self.project,
            title='Test Item No Primary Org',
            type=self.item_type,
            requester=self.requester_a,
            organisation=self.org1,
            status=ItemStatus.INBOX
        )
        
        # Verify initial state
        self.assertEqual(item.requester, self.requester_a)
        self.assertEqual(item.organisation, self.org1)
        
        # Action: Change requester to C (who has NO primary organisation)
        item.requester = self.requester_c
        item.save()
        
        # Refresh from database
        item.refresh_from_db()
        
        # Expectation: organisation should remain Org1 (unchanged)
        # because new requester has no primary organisation
        self.assertEqual(item.requester, self.requester_c)
        self.assertEqual(item.organisation, self.org1,
                        "Organisation should remain unchanged when new requester has no primary organisation")
    
    def test_requester_change_from_none_sets_organisation(self):
        """
        Test: Change requester from None to a user with primary organisation.
        Expected: item.organisation is set to new requester's primary organisation.
        """
        # Setup: Create item with NO requester and organisation Org3
        item = Item.objects.create(
            project=self.project,
            title='Test Item No Requester',
            type=self.item_type,
            requester=None,
            organisation=self.org3,
            status=ItemStatus.INBOX
        )
        
        # Verify initial state
        self.assertIsNone(item.requester)
        self.assertEqual(item.organisation, self.org3)
        
        # Action: Set requester to B (who has Org2 as primary)
        item.requester = self.requester_b
        item.save()
        
        # Refresh from database
        item.refresh_from_db()
        
        # Expectation: organisation should now be Org2
        self.assertEqual(item.requester, self.requester_b)
        self.assertEqual(item.organisation, self.org2,
                        "Organisation should update when requester changes from None to a user with primary org")
    
    def test_requester_change_to_none_keeps_organisation(self):
        """
        Test: Change requester from a user to None.
        Expected: item.organisation remains unchanged.
        """
        # Setup: Create item with requester A and organisation Org1
        item = Item.objects.create(
            project=self.project,
            title='Test Item Clear Requester',
            type=self.item_type,
            requester=self.requester_a,
            organisation=self.org1,
            status=ItemStatus.INBOX
        )
        
        # Verify initial state
        self.assertEqual(item.requester, self.requester_a)
        self.assertEqual(item.organisation, self.org1)
        
        # Action: Clear requester (set to None)
        item.requester = None
        item.save()
        
        # Refresh from database
        item.refresh_from_db()
        
        # Expectation: organisation should remain Org1
        self.assertIsNone(item.requester)
        self.assertEqual(item.organisation, self.org1,
                        "Organisation should remain unchanged when requester is cleared")
    
    def test_multiple_requester_changes(self):
        """
        Test: Multiple requester changes in sequence.
        Expected: organisation updates each time to new requester's primary org.
        """
        # Setup: Create item with requester A and organisation Org1
        item = Item.objects.create(
            project=self.project,
            title='Test Item Multiple Changes',
            type=self.item_type,
            requester=self.requester_a,
            organisation=self.org1,
            status=ItemStatus.INBOX
        )
        
        # First change: A -> B
        item.requester = self.requester_b
        item.save()
        item.refresh_from_db()
        self.assertEqual(item.organisation, self.org2)
        
        # Second change: B -> A
        item.requester = self.requester_a
        item.save()
        item.refresh_from_db()
        self.assertEqual(item.organisation, self.org1)
        
        # Third change: A -> B again
        item.requester = self.requester_b
        item.save()
        item.refresh_from_db()
        self.assertEqual(item.organisation, self.org2)


class ItemRequesterOrganisationChangeViaEndpointTest(TestCase):
    """Test automatic organisation update when requester changes via HTTP endpoints."""
    
    def setUp(self):
        """Set up test data."""
        # Create organisations
        self.org1 = Organisation.objects.create(name='Organisation 1', short='ORG1')
        self.org2 = Organisation.objects.create(name='Organisation 2', short='ORG2')
        
        # Create requester A with primary organisation = org1
        self.requester_a = User.objects.create_user(
            username='requester_a',
            email='requester_a@example.com',
            password='testpass',
            name='Requester A',
            role='User'
        )
        UserOrganisation.objects.create(
            user=self.requester_a,
            organisation=self.org1,
            is_primary=True
        )
        
        # Create requester B with primary organisation = org2
        self.requester_b = User.objects.create_user(
            username='requester_b',
            email='requester_b@example.com',
            password='testpass',
            name='Requester B',
            role='User'
        )
        UserOrganisation.objects.create(
            user=self.requester_b,
            organisation=self.org2,
            is_primary=True
        )
        
        # Create admin user for testing
        self.admin = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='testpass',
            name='Admin User',
            role='Admin'
        )
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        self.project.clients.add(self.org1, self.org2)
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='task',
            name='Task',
            is_active=True
        )
        
        self.client = Client()
        self.client.login(username='admin', password='testpass')
    
    def test_requester_change_via_item_update_endpoint(self):
        """
        Test: Change requester via item_update endpoint.
        Expected: organisation is automatically updated.
        """
        # Setup: Create item with requester A and organisation Org1
        item = Item.objects.create(
            project=self.project,
            title='Test Item Endpoint',
            type=self.item_type,
            requester=self.requester_a,
            organisation=self.org1,
            status=ItemStatus.INBOX
        )
        
        # Verify initial state
        self.assertEqual(item.requester, self.requester_a)
        self.assertEqual(item.organisation, self.org1)
        
        # Action: Update item with new requester via endpoint
        url = reverse('item-update', args=[item.id])
        data = {
            'title': item.title,
            'project': self.project.id,
            'type': self.item_type.id,
            'requester': self.requester_b.id,  # Change to requester B
            'status': item.status,
        }
        response = self.client.post(url, data)
        
        # Verify response
        self.assertEqual(response.status_code, 200)
        
        # Refresh from database
        item.refresh_from_db()
        
        # Expectation: organisation should now be Org2
        self.assertEqual(item.requester, self.requester_b)
        self.assertEqual(item.organisation, self.org2,
                        "Organisation should update when requester changes via endpoint")
