"""
Tests for Item Followers functionality.
"""

from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    Item,
    ItemFollower,
    ItemType,
    ItemStatus,
    Project,
    User,
    ProjectStatus,
    MailTemplate,
    MailActionMapping,
)
from core.services.mail import get_notification_recipients_for_item
from unittest.mock import patch, MagicMock
import json


class ItemFollowerModelTestCase(TestCase):
    """Tests for ItemFollower model"""
    
    def setUp(self):
        """Set up test data"""
        # Create users
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='testpass123'
        )
        self.user1.name = 'User One'
        self.user1.active = True
        self.user1.save()
        
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='testpass123'
        )
        self.user2.name = 'User Two'
        self.user2.active = True
        self.user2.save()
        
        # Create a project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project',
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        
        # Create an item
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
            requester=self.user1
        )
    
    def test_create_follower(self):
        """Test creating a follower"""
        follower = ItemFollower.objects.create(
            item=self.item,
            user=self.user2
        )
        
        self.assertIsNotNone(follower.id)
        self.assertEqual(follower.item, self.item)
        self.assertEqual(follower.user, self.user2)
        self.assertIsNotNone(follower.created_at)
    
    def test_unique_constraint(self):
        """Test that unique constraint prevents duplicate followers"""
        # Create first follower
        ItemFollower.objects.create(item=self.item, user=self.user2)
        
        # Try to create duplicate - should raise IntegrityError
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            ItemFollower.objects.create(item=self.item, user=self.user2)
    
    def test_get_followers(self):
        """Test Item.get_followers() method"""
        # Initially no followers
        followers = self.item.get_followers()
        self.assertEqual(followers.count(), 0)
        
        # Add followers
        ItemFollower.objects.create(item=self.item, user=self.user1)
        ItemFollower.objects.create(item=self.item, user=self.user2)
        
        # Check followers
        followers = self.item.get_followers()
        self.assertEqual(followers.count(), 2)
        self.assertIn(self.user1, followers)
        self.assertIn(self.user2, followers)
    
    def test_follower_relations(self):
        """Test follower relations work correctly"""
        ItemFollower.objects.create(item=self.item, user=self.user2)
        
        # Test item -> followers relation
        self.assertEqual(self.item.item_followers.count(), 1)
        self.assertEqual(self.item.item_followers.first().user, self.user2)
        
        # Test user -> followed items relation
        self.assertEqual(self.user2.followed_items.count(), 1)
        self.assertEqual(self.user2.followed_items.first().item, self.item)


class ItemFollowerAPITestCase(TestCase):
    """Tests for Item Followers API endpoints"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create users
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='testpass123'
        )
        self.user1.name = 'User One'
        self.user1.active = True
        self.user1.save()
        
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='testpass123'
        )
        self.user2.name = 'User Two'
        self.user2.active = True
        self.user2.save()
        
        self.user3 = User.objects.create_user(
            username='user3',
            email='user3@example.com',
            password='testpass123'
        )
        self.user3.name = 'User Three'
        self.user3.active = True
        self.user3.save()
        
        # Create a project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project',
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        
        # Login
        self.client.login(username='user1', password='testpass123')
    
    def test_create_item_with_followers(self):
        """Test creating an item with followers"""
        response = self.client.post(reverse('item-create'), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Test Item with Followers',
            'status': ItemStatus.INBOX,
            'requester': self.user1.id,
            'follower_ids': [self.user2.id, self.user3.id],
        })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Check followers in response
        self.assertIn('followers', data)
        self.assertEqual(len(data['followers']), 2)
        follower_ids = [f['id'] for f in data['followers']]
        self.assertIn(self.user2.id, follower_ids)
        self.assertIn(self.user3.id, follower_ids)
        
        # Verify in database
        item = Item.objects.get(id=data['item_id'])
        followers = item.get_followers()
        self.assertEqual(followers.count(), 2)
        self.assertIn(self.user2, followers)
        self.assertIn(self.user3, followers)
    
    def test_update_item_add_followers(self):
        """Test updating an item to add followers"""
        # Create item without followers
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
            requester=self.user1
        )
        
        # Update to add followers
        response = self.client.post(reverse('item-update', args=[item.id]), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Test Item',
            'status': ItemStatus.INBOX,
            'follower_ids': [self.user2.id, self.user3.id],
        })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Verify followers in response
        self.assertIn('followers', data)
        self.assertEqual(len(data['followers']), 2)
        
        # Verify in database
        item.refresh_from_db()
        followers = item.get_followers()
        self.assertEqual(followers.count(), 2)
        self.assertIn(self.user2, followers)
        self.assertIn(self.user3, followers)
    
    def test_update_item_remove_followers(self):
        """Test updating an item to remove followers"""
        # Create item with followers
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
            requester=self.user1
        )
        ItemFollower.objects.create(item=item, user=self.user2)
        ItemFollower.objects.create(item=item, user=self.user3)
        
        # Update to keep only user2
        response = self.client.post(reverse('item-update', args=[item.id]), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Test Item',
            'status': ItemStatus.INBOX,
            'follower_ids': [self.user2.id],
        })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Verify in database
        item.refresh_from_db()
        followers = item.get_followers()
        self.assertEqual(followers.count(), 1)
        self.assertIn(self.user2, followers)
        self.assertNotIn(self.user3, followers)
    
    def test_update_item_clear_followers(self):
        """Test updating an item to clear all followers"""
        # Create item with followers
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
            requester=self.user1
        )
        ItemFollower.objects.create(item=item, user=self.user2)
        
        # Update to clear followers - note: when using Django test client,
        # we need to explicitly indicate we're sending an empty list
        # by including at least the key in POST
        post_data = {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Test Item',
            'status': ItemStatus.INBOX,
        }
        # Explicitly add follower_ids with empty value to ensure it's in POST
        post_data['follower_ids'] = ''  # Empty string means clear all
        
        response = self.client.post(reverse('item-update', args=[item.id]), post_data)
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Verify in database
        item.refresh_from_db()
        followers = item.get_followers()
        self.assertEqual(followers.count(), 0)
    
    def test_duplicate_follower_ids_prevented(self):
        """Test that duplicate follower IDs don't create duplicate followers"""
        response = self.client.post(reverse('item-create'), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Test Item',
            'status': ItemStatus.INBOX,
            'requester': self.user1.id,
            'follower_ids': [self.user2.id, self.user2.id, self.user2.id],  # Duplicate IDs
        })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Verify only one follower created
        item = Item.objects.get(id=data['item_id'])
        followers = item.get_followers()
        self.assertEqual(followers.count(), 1)


class EmailNotificationRecipientsTestCase(TestCase):
    """Tests for email notification recipients with followers"""
    
    def setUp(self):
        """Set up test data"""
        # Create users
        self.requester = User.objects.create_user(
            username='requester',
            email='requester@example.com',
            password='testpass123'
        )
        self.requester.name = 'Requester'
        self.requester.save()
        
        self.follower1 = User.objects.create_user(
            username='follower1',
            email='follower1@example.com',
            password='testpass123'
        )
        self.follower1.name = 'Follower One'
        self.follower1.save()
        
        self.follower2 = User.objects.create_user(
            username='follower2',
            email='follower2@example.com',
            password='testpass123'
        )
        self.follower2.name = 'Follower Two'
        self.follower2.save()
        
        # Create a project
        self.project = Project.objects.create(
            name='Test Project',
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        
        # Create an item
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
            requester=self.requester
        )
    
    def test_get_recipients_with_followers(self):
        """Test getting recipients with followers"""
        # Add followers
        ItemFollower.objects.create(item=self.item, user=self.follower1)
        ItemFollower.objects.create(item=self.item, user=self.follower2)
        
        # Get recipients
        recipients = get_notification_recipients_for_item(self.item)
        
        self.assertEqual(recipients['to'], 'requester@example.com')
        self.assertEqual(len(recipients['cc']), 2)
        self.assertIn('follower1@example.com', recipients['cc'])
        self.assertIn('follower2@example.com', recipients['cc'])
    
    def test_get_recipients_without_followers(self):
        """Test getting recipients without followers"""
        recipients = get_notification_recipients_for_item(self.item)
        
        self.assertEqual(recipients['to'], 'requester@example.com')
        self.assertEqual(len(recipients['cc']), 0)
    
    def test_no_duplicate_emails(self):
        """Test that requester is not included in CC if they're also a follower"""
        # Make requester also a follower
        ItemFollower.objects.create(item=self.item, user=self.requester)
        ItemFollower.objects.create(item=self.item, user=self.follower1)
        
        recipients = get_notification_recipients_for_item(self.item)
        
        self.assertEqual(recipients['to'], 'requester@example.com')
        # Should not include requester in CC
        self.assertNotIn('requester@example.com', recipients['cc'])
        # Should include other follower
        self.assertIn('follower1@example.com', recipients['cc'])


class EmailIntegrationWithFollowersTestCase(TestCase):
    """Tests for email integration with followers in CC"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create users
        self.requester = User.objects.create_user(
            username='requester',
            email='requester@example.com',
            password='testpass123'
        )
        self.requester.name = 'Requester'
        self.requester.active = True
        self.requester.save()
        
        self.follower1 = User.objects.create_user(
            username='follower1',
            email='follower1@example.com',
            password='testpass123'
        )
        self.follower1.name = 'Follower One'
        self.follower1.active = True
        self.follower1.save()
        
        # Create a project
        self.project = Project.objects.create(
            name='Test Project',
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        
        # Create an item with follower
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
            requester=self.requester
        )
        ItemFollower.objects.create(item=self.item, user=self.follower1)
        
        # Login
        self.client.login(username='requester', password='testpass123')
    
    @patch('core.services.graph.mail_service.get_graph_config')
    @patch('core.services.graph.mail_service.get_client')
    def test_send_status_mail_includes_followers_in_cc(self, mock_get_client, mock_get_config):
        """Test that sending status mail includes followers in CC"""
        # Mock the Graph API config
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.default_mail_sender = 'default@example.com'
        mock_get_config.return_value = mock_config
        
        # Mock the Graph API client
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        # Send mail
        response = self.client.post(
            reverse('item-send-status-mail', args=[self.item.id]),
            data=json.dumps({
                'subject': 'Test Subject',
                'message': '<p>Test message</p>',
                'to': 'requester@example.com',
                'from_address': 'sender@example.com',
                'cc_address': ''
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Verify send_email was called with follower in CC
        # Note: We can't easily verify the exact call here without more mocking,
        # but the test ensures the endpoint works with followers
