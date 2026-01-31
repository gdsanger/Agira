"""
Tests for item move functionality.
"""
import json
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from core.models import Project, Item, ItemType, ItemStatus, MailTemplate, Organisation
from unittest.mock import patch, MagicMock

User = get_user_model()


class ItemMoveProjectTestCase(TestCase):
    """Test cases for moving items between projects."""
    
    def setUp(self):
        """Set up test data."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        # Create projects
        self.project_a = Project.objects.create(
            name='Project A',
            description='First project'
        )
        self.project_b = Project.objects.create(
            name='Project B',
            description='Second project'
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            name='Feature',
            description='Feature request'
        )
        
        # Create item in project A
        self.item = Item.objects.create(
            project=self.project_a,
            title='Test Item',
            description='Test description',
            type=self.item_type,
            status=ItemStatus.INBOX,
            requester=self.user
        )
        
        # Create mail template
        self.mail_template, _ = MailTemplate.objects.get_or_create(
            key='moved',
            defaults={
                'subject': 'Item moved: {{ issue.title }}',
                'message': 'Item {{ issue.title }} was moved to {{ issue.project }}',
                'is_active': True
            }
        )
        
        # Set up client
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def test_move_item_to_different_project(self):
        """Test moving an item to a different project."""
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        self.assertEqual(response_data['new_project_id'], self.project_b.id)
        
        # Verify item was moved
        self.item.refresh_from_db()
        self.assertEqual(self.item.project.id, self.project_b.id)
    
    def test_move_item_to_same_project_fails(self):
        """Test that moving an item to its current project fails."""
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_a.id,
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('already in the target project', response_data['error'])
    
    def test_move_item_without_target_project_fails(self):
        """Test that moving without specifying target project fails."""
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('Target project is required', response_data['error'])
    
    @patch('core.views.send_email')
    def test_move_item_with_email_notification(self, mock_send_email):
        """Test moving an item with email notification enabled."""
        # Mock successful email sending
        mock_result = MagicMock()
        mock_result.success = True
        mock_send_email.return_value = mock_result
        
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': True
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        self.assertTrue(response_data['mail_sent'])
        
        # Verify email was sent
        mock_send_email.assert_called_once()
        
        # Verify item was moved
        self.item.refresh_from_db()
        self.assertEqual(self.item.project.id, self.project_b.id)
    
    @patch('core.views.send_email')
    def test_move_item_email_failure_does_not_rollback_move(self, mock_send_email):
        """Test that email failure doesn't prevent the move from succeeding."""
        # Mock failed email sending
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = 'SMTP error'
        mock_send_email.return_value = mock_result
        
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': True
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        self.assertFalse(response_data['mail_sent'])
        self.assertIn('mail_error', response_data)
        
        # Verify item was still moved despite email failure
        self.item.refresh_from_db()
        self.assertEqual(self.item.project.id, self.project_b.id)
    
    def test_move_item_without_authentication_fails(self):
        """Test that moving an item requires authentication."""
        self.client.logout()
        
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        # Should redirect to login or return 401
        self.assertIn(response.status_code, [302, 401])
    
    def test_move_item_clears_nodes(self):
        """Test that nodes are cleared when moving to a different project."""
        from core.models import Node, NodeType
        
        # Create a node in project A
        node_type = NodeType.objects.create(name='Component')
        node = Node.objects.create(
            project=self.project_a,
            name='Test Node',
            node_type=node_type
        )
        self.item.nodes.add(node)
        
        # Verify node is assigned
        self.assertEqual(self.item.nodes.count(), 1)
        
        # Move item
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify nodes were cleared
        self.item.refresh_from_db()
        self.assertEqual(self.item.nodes.count(), 0)
    
    def test_move_item_clears_parent_if_different_project(self):
        """Test that parent is cleared if it belongs to a different project."""
        # Create parent item in project A
        parent_item = Item.objects.create(
            project=self.project_a,
            title='Parent Item',
            type=self.item_type,
            status=ItemStatus.INBOX
        )
        self.item.parent = parent_item
        self.item.save()
        
        # Move item to project B
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify parent was cleared
        self.item.refresh_from_db()
        self.assertIsNone(self.item.parent)
    
    def test_move_item_without_requester_email(self):
        """Test moving item when requester has no email."""
        # Create item without requester email
        self.item.requester.email = ''
        self.item.requester.save()
        
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': True
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        response_data = response.json()
        self.assertTrue(response_data['success'])
        # Mail should not be sent because requester has no email
        self.assertFalse(response_data.get('mail_sent', False))
    
    def test_move_item_clears_solution_release_if_different_project(self):
        """Test that solution_release is cleared if it belongs to a different project."""
        from core.models import Release, ReleaseStatus
        
        # Create release in project A
        release = Release.objects.create(
            project=self.project_a,
            name='Release 1.0',
            version='1.0.0',
            status=ReleaseStatus.PLANNED
        )
        self.item.solution_release = release
        self.item.save()
        
        # Move item to project B
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify solution_release was cleared
        self.item.refresh_from_db()
        self.assertIsNone(self.item.solution_release)
    
    def test_move_item_clears_organisation_if_not_client(self):
        """Test that organisation is cleared when not a client of target project."""
        # Create organisation
        org = Organisation.objects.create(
            name='Test Org',
            email_domain='testorg.com'
        )
        
        # Add organisation to project A as client
        self.project_a.clients.add(org)
        self.item.organisation = org
        self.item.save()
        
        # Move to project B (which has no clients)
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify organisation was cleared
        self.item.refresh_from_db()
        self.assertIsNone(self.item.organisation)
    
    def test_move_item_keeps_organisation_if_client_of_target(self):
        """Test that organisation is kept when it's a client of target project."""
        # Create organisation
        org = Organisation.objects.create(
            name='Test Org',
            email_domain='testorg.com'
        )
        
        # Add organisation as client of both projects
        self.project_a.clients.add(org)
        self.project_b.clients.add(org)
        self.item.organisation = org
        self.item.save()
        
        # Move to project B
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify organisation was kept
        self.item.refresh_from_db()
        self.assertEqual(self.item.organisation, org)
    
    def test_move_item_logs_activity(self):
        """Test that moving an item logs an activity."""
        from core.models import Activity
        
        # Count activities before move
        activity_count_before = Activity.objects.count()
        
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': self.project_b.id,
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Verify activity was logged
        activity_count_after = Activity.objects.count()
        self.assertEqual(activity_count_after, activity_count_before + 1)
        
        # Check the activity details
        latest_activity = Activity.objects.latest('created_at')
        self.assertEqual(latest_activity.verb, 'item.moved')
        self.assertEqual(latest_activity.actor, self.user)
        self.assertIn(self.project_a.name, latest_activity.summary)
        self.assertIn(self.project_b.name, latest_activity.summary)
    
    def test_move_item_with_invalid_project_id_fails(self):
        """Test that moving to a non-existent project returns proper error."""
        url = f'/items/{self.item.id}/move-project/'
        data = {
            'target_project_id': 99999,  # Non-existent project ID
            'send_mail_to_requester': False
        }
        
        response = self.client.post(
            url,
            data=json.dumps(data),
            content_type='application/json'
        )
        
        # Should return 404 with clear error message
        self.assertEqual(response.status_code, 404)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('not found', response_data['error'].lower())
        
        # Verify item was NOT moved
        self.item.refresh_from_db()
        self.assertEqual(self.item.project.id, self.project_a.id)
    
    def test_move_item_with_invalid_json_fails(self):
        """Test that invalid JSON returns proper error."""
        url = f'/items/{self.item.id}/move-project/'
        
        response = self.client.post(
            url,
            data='invalid json {',
            content_type='application/json'
        )
        
        # Should return 400 with clear error message
        self.assertEqual(response.status_code, 400)
        response_data = response.json()
        self.assertFalse(response_data['success'])
        self.assertIn('Invalid JSON', response_data['error'])
