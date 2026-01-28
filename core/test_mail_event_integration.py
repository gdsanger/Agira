"""
Integration tests for mail event handling on item status changes.
"""

from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    Item,
    ItemType,
    ItemStatus,
    Project,
    User,
    MailTemplate,
    MailActionMapping,
    ProjectStatus,
    ItemComment,
    CommentKind,
    EmailDeliveryStatus,
)
from unittest.mock import patch, MagicMock
import json


class ItemStatusMailTriggerIntegrationTestCase(TestCase):
    """Integration tests for mail triggering on item status changes"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create a user
        self.user = User.objects.create_user(
            username='testuser',
            email='testuser@example.com',
            password='testpass123'
        )
        self.user.name = 'Test User'
        self.user.active = True
        self.user.save()
        
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
        
        # Create mail template
        self.template = MailTemplate.objects.create(
            key='status-changed-working',
            subject='Status changed to Working: {{ issue.title }}',
            message='<p>Your issue <strong>{{ issue.title }}</strong> is now in <strong>{{ issue.status }}</strong> status.</p>',
            from_name='Support Team',
            from_address='support@example.com',
            is_active=True
        )
        
        # Create mail action mapping for Bug + Working status
        self.mapping = MailActionMapping.objects.create(
            is_active=True,
            item_status=ItemStatus.WORKING,
            item_type=self.item_type,
            mail_template=self.template
        )
        
        # Login
        self.client.login(username='testuser', password='testpass123')
    
    def test_item_create_with_mail_trigger(self):
        """Test that creating an item with WORKING status triggers mail preview"""
        response = self.client.post(reverse('item-create'), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'New Bug Item',
            'description': 'Bug description',
            'status': ItemStatus.WORKING,
            'requester': self.user.id,
        })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        # Should be successful
        self.assertTrue(data['success'])
        
        # Should include mail_preview
        self.assertIn('mail_preview', data)
        
        # Check mail preview content
        mail_preview = data['mail_preview']
        self.assertIn('New Bug Item', mail_preview['subject'])
        self.assertIn('Working', mail_preview['subject'])
        self.assertIn('New Bug Item', mail_preview['message'])
        self.assertIn('Working', mail_preview['message'])
        self.assertEqual(mail_preview['from_name'], 'Support Team')
        self.assertEqual(mail_preview['from_address'], 'support@example.com')
    
    def test_item_create_without_mail_trigger(self):
        """Test that creating an item with INBOX status does not trigger mail"""
        response = self.client.post(reverse('item-create'), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'New Inbox Item',
            'description': 'Item description',
            'status': ItemStatus.INBOX,  # No mapping for this status
            'requester': self.user.id,
        })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        # Should be successful
        self.assertTrue(data['success'])
        
        # Should NOT include mail_preview
        self.assertNotIn('mail_preview', data)
    
    def test_item_update_with_status_change_triggers_mail(self):
        """Test that updating item status triggers mail preview"""
        # Create an item with INBOX status
        item = Item.objects.create(
            project=self.project,
            title='Inbox Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
            requester=self.user
        )
        
        # Update status to WORKING (should trigger mail)
        response = self.client.post(reverse('item-update', args=[item.id]), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Inbox Item',
            'status': ItemStatus.WORKING,  # Changed status
        })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        # Should be successful
        self.assertTrue(data['success'])
        
        # Should include mail_preview
        self.assertIn('mail_preview', data)
        
        # Check mail preview content
        mail_preview = data['mail_preview']
        self.assertIn('Inbox Item', mail_preview['subject'])
        self.assertIn('Working', mail_preview['subject'])
    
    def test_item_update_without_status_change_no_mail(self):
        """Test that updating item without changing status does not trigger mail"""
        # Create an item with WORKING status
        item = Item.objects.create(
            project=self.project,
            title='Working Item',
            type=self.item_type,
            status=ItemStatus.WORKING,
            requester=self.user
        )
        
        # Update title but keep same status
        response = self.client.post(reverse('item-update', args=[item.id]), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Updated Working Item',  # Changed title
            'status': ItemStatus.WORKING,  # Same status
        })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        # Should be successful
        self.assertTrue(data['success'])
        
        # Should NOT include mail_preview (status didn't change)
        self.assertNotIn('mail_preview', data)
    
    def test_item_create_with_inactive_mapping_no_mail(self):
        """Test that inactive mail mappings are not triggered"""
        # Make mapping inactive
        self.mapping.is_active = False
        self.mapping.save()
        
        response = self.client.post(reverse('item-create'), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'New Bug Item',
            'description': 'Bug description',
            'status': ItemStatus.WORKING,
            'requester': self.user.id,
        })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        # Should be successful
        self.assertTrue(data['success'])
        
        # Should NOT include mail_preview (mapping is inactive)
        self.assertNotIn('mail_preview', data)
    
    @patch('core.services.graph.mail_service.get_graph_config')
    @patch('core.services.graph.mail_service.get_client')
    def test_send_status_mail_endpoint(self, mock_get_client, mock_get_config):
        """Test the send-status-mail endpoint"""
        # Create an item
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.WORKING,
            requester=self.user
        )
        
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
            reverse('item-send-status-mail', args=[item.id]),
            data=json.dumps({
                'subject': 'Test Subject',
                'message': '<p>Test message</p>',
                'to': 'recipient@example.com',
                'from_address': 'sender@example.com',
                'cc_address': ''
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        # Should be successful
        self.assertTrue(data['success'])
        
        # Verify Graph client was called
        mock_client.send_mail.assert_called_once()
        
        # Verify ItemComment was created
        comments = ItemComment.objects.filter(
            item=item,
            kind=CommentKind.EMAIL_OUT
        )
        self.assertEqual(comments.count(), 1)
        
        comment = comments.first()
        self.assertEqual(comment.subject, 'Test Subject')
        self.assertEqual(comment.body_html, '<p>Test message</p>')
        self.assertEqual(comment.delivery_status, EmailDeliveryStatus.SENT)
        self.assertIsNotNone(comment.sent_at)
    
    @patch('core.services.graph.mail_service.get_graph_config')
    @patch('core.services.graph.mail_service.get_client')
    def test_send_status_mail_uses_requester_email(self, mock_get_client, mock_get_config):
        """Test that send-status-mail uses requester email when no 'to' provided"""
        # Create an item with requester
        requester = User.objects.create_user(
            username='requester',
            email='requester@example.com',
            password='pass'
        )
        requester.name = 'Requester User'
        requester.save()
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.WORKING,
            requester=requester
        )
        
        # Mock the Graph API config
        mock_config = MagicMock()
        mock_config.enabled = True
        mock_config.default_mail_sender = 'default@example.com'
        mock_get_config.return_value = mock_config
        
        # Mock the Graph API client
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        
        # Send mail without 'to' field
        response = self.client.post(
            reverse('item-send-status-mail', args=[item.id]),
            data=json.dumps({
                'subject': 'Test Subject',
                'message': '<p>Test message</p>',
                'to': '',  # Empty, should use requester email
                'from_address': 'sender@example.com',
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        
        # Verify Graph client was called with requester email
        call_args = mock_client.send_mail.call_args
        payload = call_args[1]['payload']
        to_recipients = payload['message']['toRecipients']
        self.assertEqual(len(to_recipients), 1)
        self.assertEqual(to_recipients[0]['emailAddress']['address'], 'requester@example.com')
    
    def test_send_status_mail_requires_recipient(self):
        """Test that send-status-mail requires a recipient"""
        # Create an item without requester
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.WORKING,
            # No requester
        )
        
        # Try to send mail without recipient
        response = self.client.post(
            reverse('item-send-status-mail', args=[item.id]),
            data=json.dumps({
                'subject': 'Test Subject',
                'message': '<p>Test message</p>',
                'to': '',  # Empty and no requester
                'from_address': 'sender@example.com',
            }),
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertIn('recipient', data['error'].lower())
    
    def test_template_variables_replaced_correctly(self):
        """Test that all template variables are replaced correctly in preview"""
        # Create user for assignment
        assignee = User.objects.create_user(
            username='assignee',
            email='assignee@example.com',
            password='pass'
        )
        assignee.name = 'Assignee User'
        assignee.save()
        
        # Create template with all variables
        full_template = MailTemplate.objects.create(
            key='full-template',
            subject='{{ issue.title }} - {{ issue.status }} - {{ issue.type }}',
            message='Project: {{ issue.project }}, Requester: {{ issue.requester }}, Assigned: {{ issue.assigned_to }}',
            is_active=True
        )
        
        # Create mapping
        MailActionMapping.objects.create(
            is_active=True,
            item_status=ItemStatus.TESTING,
            item_type=self.item_type,
            mail_template=full_template
        )
        
        # Create item with all fields
        response = self.client.post(reverse('item-create'), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Full Item',
            'description': 'Description',
            'status': ItemStatus.TESTING,
            'requester': self.user.id,
            'assigned_to': assignee.id,
        })
        
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        
        # Check all variables are replaced
        mail_preview = data['mail_preview']
        self.assertIn('Full Item', mail_preview['subject'])
        self.assertIn('Testing', mail_preview['subject'])
        self.assertIn('Bug', mail_preview['subject'])
        self.assertIn('Test Project', mail_preview['message'])
        self.assertIn('Test User', mail_preview['message'])
        self.assertIn('Assignee User', mail_preview['message'])
    
    def test_item_change_status_triggers_mail(self):
        """Test that item_change_status endpoint triggers mail preview when status changes"""
        # Login
        self.client.login(username='testuser', password='testpass123')
        
        # Create an item with INBOX status
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Test description',
            type=self.item_type,
            status=ItemStatus.INBOX,
            requester=self.user
        )
        
        # Change status to WORKING (which has a mail mapping)
        response = self.client.post(
            reverse('item-change-status', args=[item.id]),
            {'status': ItemStatus.WORKING}
        )
        
        # Should return JSON with mail preview
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertIn('mail_preview', data)
        self.assertEqual(data['item_id'], item.id)
        self.assertEqual(data['new_status'], ItemStatus.WORKING)
        
        # Verify mail preview content
        mail_preview = data['mail_preview']
        self.assertIn('Test Item', mail_preview['subject'])
        self.assertIn('Working', mail_preview['subject'])
    
    def test_item_change_status_without_mail_trigger(self):
        """Test that item_change_status returns HTML when no mail trigger exists"""
        # Login
        self.client.login(username='testuser', password='testpass123')
        
        # Create an item with INBOX status
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            description='Test description',
            type=self.item_type,
            status=ItemStatus.INBOX,
            requester=self.user
        )
        
        # Change status to BACKLOG (which has no mail mapping)
        response = self.client.post(
            reverse('item-change-status', args=[item.id]),
            {'status': ItemStatus.BACKLOG}
        )
        
        # Should return HTML (status badge)
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response['Content-Type'])
        
        # Refresh item from DB
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.BACKLOG)
