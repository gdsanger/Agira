"""
Tests for Organisation short field and requester quick-create functionality
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, User, UserOrganisation, UserRole,
    Item, ItemType, Project, ProjectStatus
)


class OrganisationShortFieldTestCase(TestCase):
    """Test cases for Organisation short field"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            name="Test User"
        )
        self.client.login(username="testuser", password="testpass123")
    
    def test_create_organisation_with_short_field(self):
        """Test creating an organisation with short field"""
        org = Organisation.objects.create(
            name="Test Organisation",
            short="TEST"
        )
        
        self.assertEqual(org.name, "Test Organisation")
        self.assertEqual(org.short, "TEST")
    
    def test_create_organisation_without_short_field(self):
        """Test creating an organisation without short field (optional)"""
        org = Organisation.objects.create(
            name="Test Organisation"
        )
        
        self.assertEqual(org.name, "Test Organisation")
        self.assertEqual(org.short, "")
    
    def test_short_field_max_length_validation(self):
        """Test that short field is limited to 10 characters"""
        # This test validates at the view level
        response = self.client.post(
            reverse('organisation-create'),
            {
                'name': 'Test Organisation',
                'short': 'THISISTOOLONG'  # 13 characters
            }
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('10 characters', data['error'])
    
    def test_organisation_create_with_valid_short(self):
        """Test creating organisation via view with valid short code"""
        response = self.client.post(
            reverse('organisation-create'),
            {
                'name': 'New Organisation',
                'short': 'NEWORG'
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify organisation was created
        org = Organisation.objects.get(name='New Organisation')
        self.assertEqual(org.short, 'NEWORG')
    
    def test_organisation_update_with_short(self):
        """Test updating organisation short field"""
        org = Organisation.objects.create(
            name="Test Organisation",
            short="TEST"
        )
        
        response = self.client.post(
            reverse('organisation-update', args=[org.id]),
            {
                'name': 'Test Organisation',
                'short': 'UPDATED'
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify organisation was updated
        org.refresh_from_db()
        self.assertEqual(org.short, 'UPDATED')


class RequesterDisplayTestCase(TestCase):
    """Test cases for requester display with org short code"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            name="Test User"
        )
        self.client.login(username="testuser", password="testpass123")
        
        # Create organisations
        self.org_with_short = Organisation.objects.create(
            name="Org With Short",
            short="OWS"
        )
        
        self.org_without_short = Organisation.objects.create(
            name="Org Without Short",
            short=""
        )
        
        # Create requester users
        self.requester_with_org_short = User.objects.create_user(
            username="requester1",
            email="requester1@example.com",
            password="testpass123",
            name="Requester One"
        )
        
        self.requester_without_org_short = User.objects.create_user(
            username="requester2",
            email="requester2@example.com",
            password="testpass123",
            name="Requester Two"
        )
        
        self.requester_without_org = User.objects.create_user(
            username="requester3",
            email="requester3@example.com",
            password="testpass123",
            name="Requester Three"
        )
        
        # Set up primary organisations
        UserOrganisation.objects.create(
            user=self.requester_with_org_short,
            organisation=self.org_with_short,
            is_primary=True,
            role=UserRole.USER
        )
        
        UserOrganisation.objects.create(
            user=self.requester_without_org_short,
            organisation=self.org_without_short,
            is_primary=True,
            role=UserRole.USER
        )
        
        # Create project and item type
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
        
        self.item_type = ItemType.objects.create(
            key="bug",
            name="Bug"
        )
    
    def test_requester_display_with_org_short(self):
        """Test that requester with org short displays correctly"""
        item = Item.objects.create(
            title="Test Item",
            project=self.project,
            type=self.item_type,
            requester=self.requester_with_org_short
        )
        
        response = self.client.get(reverse('item-detail', args=[item.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['requester_org_short'], 'OWS')
    
    def test_requester_display_with_org_no_short(self):
        """Test that requester with org but no short code displays N/A"""
        item = Item.objects.create(
            title="Test Item",
            project=self.project,
            type=self.item_type,
            requester=self.requester_without_org_short
        )
        
        response = self.client.get(reverse('item-detail', args=[item.id]))
        self.assertEqual(response.status_code, 200)
        # When org exists but short is empty, it should be None
        self.assertIsNone(response.context['requester_org_short'])
    
    def test_requester_display_without_org(self):
        """Test that requester without org displays N/A"""
        item = Item.objects.create(
            title="Test Item",
            project=self.project,
            type=self.item_type,
            requester=self.requester_without_org
        )
        
        response = self.client.get(reverse('item-detail', args=[item.id]))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['requester_org_short'])


class QuickCreateUserTestCase(TestCase):
    """Test cases for quick create user functionality"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            name="Test User"
        )
        self.client.login(username="testuser", password="testpass123")
        
        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation",
            short="TEST"
        )
        
        # Create project and item type
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
        
        self.item_type = ItemType.objects.create(
            key="bug",
            name="Bug"
        )
        
        # Create item
        self.item = Item.objects.create(
            title="Test Item",
            project=self.project,
            type=self.item_type
        )
    
    def test_quick_create_user_success(self):
        """Test successfully creating a user via quick create"""
        response = self.client.post(
            reverse('item-quick-create-user', args=[self.item.id]),
            {
                'name': 'New User',
                'email': 'newuser@example.com',
                'organization_id': self.org.id
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify user was created
        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.name, 'New User')
        self.assertEqual(user.username, 'newuser')
        
        # Verify primary organisation was set
        user_org = UserOrganisation.objects.get(user=user, is_primary=True)
        self.assertEqual(user_org.organisation, self.org)
        
        # Verify user was set as requester
        self.item.refresh_from_db()
        self.assertEqual(self.item.requester, user)
    
    def test_quick_create_user_missing_name(self):
        """Test quick create fails when name is missing"""
        response = self.client.post(
            reverse('item-quick-create-user', args=[self.item.id]),
            {
                'email': 'newuser@example.com',
                'organization_id': self.org.id
            }
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Name is required', data['error'])
    
    def test_quick_create_user_missing_email(self):
        """Test quick create fails when email is missing"""
        response = self.client.post(
            reverse('item-quick-create-user', args=[self.item.id]),
            {
                'name': 'New User',
                'organization_id': self.org.id
            }
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Email is required', data['error'])
    
    def test_quick_create_user_missing_organization(self):
        """Test quick create fails when organization is missing"""
        response = self.client.post(
            reverse('item-quick-create-user', args=[self.item.id]),
            {
                'name': 'New User',
                'email': 'newuser@example.com'
            }
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Organization is required', data['error'])
    
    def test_quick_create_user_duplicate_email(self):
        """Test quick create fails when email already exists"""
        # Create existing user
        User.objects.create_user(
            username="existing",
            email="existing@example.com",
            password="testpass123",
            name="Existing User"
        )
        
        response = self.client.post(
            reverse('item-quick-create-user', args=[self.item.id]),
            {
                'name': 'New User',
                'email': 'existing@example.com',
                'organization_id': self.org.id
            }
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('already exists', data['error'])
    
    def test_quick_create_user_generates_unique_username(self):
        """Test that username is auto-generated and made unique"""
        # Create user with username 'newuser'
        User.objects.create_user(
            username="newuser",
            email="other@example.com",
            password="testpass123",
            name="Other User"
        )
        
        response = self.client.post(
            reverse('item-quick-create-user', args=[self.item.id]),
            {
                'name': 'New User',
                'email': 'newuser@example.com',
                'organization_id': self.org.id
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify user was created with modified username
        user = User.objects.get(email='newuser@example.com')
        self.assertEqual(user.username, 'newuser1')
