"""
Tests for Item responsible field functionality.
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item, UserRole
)

User = get_user_model()


class ItemResponsibleFieldTest(TestCase):
    """Test the item responsible field."""
    
    def setUp(self):
        """Set up test data."""
        # Create agent user
        self.agent = User.objects.create_user(
            username='agent',
            email='agent@example.com',
            password='testpass',
            name='Agent User',
            role=UserRole.AGENT
        )
        
        # Create non-agent user
        self.user = User.objects.create_user(
            username='testuser',
            email='user@example.com',
            password='testpass',
            name='Test User',
            role=UserRole.USER
        )
        
        # Create organisation
        self.org = Organisation.objects.create(name='Test Org')
        UserOrganisation.objects.create(
            user=self.agent,
            organisation=self.org,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        self.project.clients.add(self.org)
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            organisation=self.org
        )
        
        # Create client
        self.client = Client()
    
    def test_item_responsible_default_value(self):
        """Test that new items have responsible=None by default."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        self.assertIsNone(item.responsible)
    
    def test_item_responsible_can_be_set_to_agent(self):
        """Test that responsible can be set to an agent user."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=self.agent
        )
        item.full_clean()  # Should not raise
        self.assertEqual(item.responsible, self.agent)
    
    def test_item_responsible_cannot_be_non_agent(self):
        """Test that responsible cannot be set to a non-agent user."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=self.user  # Non-agent
        )
        with self.assertRaises(ValidationError) as context:
            item.full_clean()
        self.assertIn('responsible', context.exception.message_dict)
    
    def test_item_responsible_can_be_null(self):
        """Test that responsible can be null."""
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=None
        )
        item.full_clean()  # Should not raise
        self.assertIsNone(item.responsible)
    
    def test_take_over_responsible_action_as_agent(self):
        """Test take over action as agent user."""
        self.client.login(username='agent', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        response = self.client.post(
            reverse('item-take-over-responsible', args=[item.id])
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Reload item and check responsible
        item.refresh_from_db()
        self.assertEqual(item.responsible, self.agent)
    
    def test_take_over_responsible_action_as_non_agent(self):
        """Test take over action as non-agent user should fail."""
        self.client.login(username='testuser', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        response = self.client.post(
            reverse('item-take-over-responsible', args=[item.id])
        )
        
        self.assertEqual(response.status_code, 403)
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_take_over_responsible_idempotent(self):
        """Test take over action is idempotent (no change if already responsible)."""
        self.client.login(username='agent', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=self.agent
        )
        
        response = self.client.post(
            reverse('item-take-over-responsible', args=[item.id])
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data.get('no_change', False))
    
    def test_assign_responsible_action(self):
        """Test assign action."""
        self.client.login(username='testuser', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        response = self.client.post(
            reverse('item-assign-responsible', args=[item.id]),
            {'agent_id': self.agent.id}
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Reload item and check responsible
        item.refresh_from_db()
        self.assertEqual(item.responsible, self.agent)
    
    def test_assign_responsible_validates_agent_role(self):
        """Test assign action validates that selected user is an agent."""
        self.client.login(username='testuser', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        response = self.client.post(
            reverse('item-assign-responsible', args=[item.id]),
            {'agent_id': self.user.id}  # Non-agent
        )
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_assign_responsible_idempotent(self):
        """Test assign action is idempotent."""
        self.client.login(username='testuser', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=self.agent
        )
        
        response = self.client.post(
            reverse('item-assign-responsible', args=[item.id]),
            {'agent_id': self.agent.id}
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data.get('no_change', False))


class ItemResponsibleMailNotificationTest(TestCase):
    """Test mail notifications for item responsible assignment."""
    
    def setUp(self):
        """Set up test data."""
        from unittest.mock import patch
        from core.models import MailTemplate
        
        # Create agent users
        self.agent1 = User.objects.create_user(
            username='agent1',
            email='agent1@example.com',
            password='testpass',
            name='Agent One',
            role=UserRole.AGENT
        )
        
        self.agent2 = User.objects.create_user(
            username='agent2',
            email='agent2@example.com',
            password='testpass',
            name='Agent Two',
            role=UserRole.AGENT
        )
        
        # Create organisation
        self.org = Organisation.objects.create(name='Test Org')
        UserOrganisation.objects.create(
            user=self.agent1,
            organisation=self.org,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(
            name='Test Project',
            description='Test description'
        )
        self.project.clients.add(self.org)
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            organisation=self.org
        )
        
        # Create mail template
        MailTemplate.objects.create(
            key='resp',
            subject='Item zugewiesen: {{ issue.title }}',
            message='<p>Hallo {{ issue.responsible }},</p><p>Item: {{ issue.title }}</p>',
            from_name='Agira',
            from_address='',
            cc_address='',
            is_active=True
        )
        
        # Create client
        self.client = Client()
    
    def test_take_over_sends_mail_on_change(self):
        """Test that take over action sends mail when responsible changes."""
        from unittest.mock import patch
        
        self.client.login(username='agent1', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        with patch('core.views._send_responsible_notification') as mock_send:
            response = self.client.post(
                reverse('item-take-over-responsible', args=[item.id])
            )
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data['success'])
            
            # Verify mail function was called
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            self.assertEqual(call_args[0][0].id, item.id)  # First arg is item
            self.assertEqual(call_args[0][1].id, self.agent1.id)  # Second arg is new responsible
    
    def test_take_over_no_mail_when_already_responsible(self):
        """Test that take over action doesn't send mail when already responsible."""
        from unittest.mock import patch
        
        self.client.login(username='agent1', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=self.agent1
        )
        
        with patch('core.views._send_responsible_notification') as mock_send:
            response = self.client.post(
                reverse('item-take-over-responsible', args=[item.id])
            )
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data['success'])
            self.assertTrue(data.get('no_change', False))
            
            # Verify mail function was NOT called
            mock_send.assert_not_called()
    
    def test_assign_sends_mail_on_change(self):
        """Test that assign action sends mail when responsible changes."""
        from unittest.mock import patch
        
        self.client.login(username='agent1', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type
        )
        
        with patch('core.views._send_responsible_notification') as mock_send:
            response = self.client.post(
                reverse('item-assign-responsible', args=[item.id]),
                {'agent_id': self.agent2.id}
            )
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data['success'])
            
            # Verify mail function was called
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            self.assertEqual(call_args[0][0].id, item.id)  # First arg is item
            self.assertEqual(call_args[0][1].id, self.agent2.id)  # Second arg is new responsible
    
    def test_assign_no_mail_when_already_responsible(self):
        """Test that assign action doesn't send mail when already responsible."""
        from unittest.mock import patch
        
        self.client.login(username='agent1', password='testpass')
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            responsible=self.agent2
        )
        
        with patch('core.views._send_responsible_notification') as mock_send:
            response = self.client.post(
                reverse('item-assign-responsible', args=[item.id]),
                {'agent_id': self.agent2.id}
            )
            
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data['success'])
            self.assertTrue(data.get('no_change', False))
            
            # Verify mail function was NOT called
            mock_send.assert_not_called()
    
    def test_mail_notification_function_with_template(self):
        """Test that mail notification function works with template."""
        from unittest.mock import patch, MagicMock
        from core.views import _send_responsible_notification
        from core.models import GlobalSettings
        
        # Create global settings for base_url
        GlobalSettings.objects.create(
            id=1,
            base_url='https://agira.example.com'
        )
        
        item = Item.objects.create(
            project=self.project,
            title='Test Item for Mail',
            type=self.item_type
        )
        
        with patch('core.views.send_email') as mock_send_email:
            _send_responsible_notification(item, self.agent1)
            
            # Verify send_email was called
            mock_send_email.assert_called_once()
            
            # Check the arguments
            call_kwargs = mock_send_email.call_args[1]
            self.assertIn('subject', call_kwargs)
            self.assertIn('body', call_kwargs)
            self.assertIn('to', call_kwargs)
            self.assertEqual(call_kwargs['to'], [self.agent1.email])
            self.assertTrue(call_kwargs['body_is_html'])
            
            # Verify subject contains item title
            self.assertIn('Test Item for Mail', call_kwargs['subject'])
    
    def test_mail_template_exists_in_database(self):
        """Test that the mail template 'resp' exists and is active."""
        from core.models import MailTemplate
        
        template = MailTemplate.objects.filter(key='resp', is_active=True).first()
        self.assertIsNotNone(template)
        self.assertEqual(template.key, 'resp')
        self.assertTrue(template.is_active)
        self.assertIn('{{ issue.title }}', template.subject)
        self.assertIn('{{ issue.responsible }}', template.message)
        self.assertIn('{{ issue.link }}', template.message)
