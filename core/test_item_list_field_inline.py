"""
Tests for the inline responsible / suggested-model columns in the item lists.

The lists drop the Organisation and Assigned To columns in favour of Responsible and
Suggested Model, both editable in the row via HTMX (endpoint ``item-list-field``),
the same way the status is.
"""
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from core.models import (
    Activity,
    ClaudeQueueJobModel,
    Item,
    ItemStatus,
    ItemType,
    Project,
    ProjectStatus,
    User,
    UserRole,
)


class ItemListFieldInlineTestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create(
            username="listuser", email="listuser@example.com", active=True,
        )
        self.user.set_password("testpass123")
        self.user.save()
        self.agent = User.objects.create(
            username="agent", email="agent@example.com", name="Agent Smith",
            role=UserRole.AGENT, active=True,
        )
        self.project = Project.objects.create(name="P", status=ProjectStatus.WORKING)
        self.project.members.add(self.user)
        self.item_type = ItemType.objects.create(name="Bug", is_active=True)
        self.item = Item.objects.create(
            title="Inline field item",
            status=ItemStatus.TESTING,
            type=self.item_type,
            project=self.project,
            suggested_model=ClaudeQueueJobModel.SONNET,
        )
        self.url = reverse('item-list-field', kwargs={'item_id': self.item.id})
        self.client.login(username="listuser", password="testpass123")

    def test_list_shows_new_columns_instead_of_organisation_and_assigned_to(self):
        response = self.client.get(reverse('items-testing'))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        columns = [column.name for column in response.context['table'].columns]
        self.assertIn('responsible', columns)
        self.assertIn('suggested_model', columns)
        self.assertNotIn('organisation', columns)
        self.assertNotIn('assigned_to', columns)
        self.assertIn(f'id="item-responsible-cell-{self.item.id}"', content)
        self.assertIn(f'id="item-suggested_model-cell-{self.item.id}"', content)
        self.assertIn(f'hx-post="{self.url}"', content)
        self.assertIn(f'<option value="{self.agent.id}">Agent Smith</option>', content)

    @patch('core.views._send_responsible_notification')
    def test_set_responsible(self, mock_notify):
        response = self.client.post(self.url, {'field': 'responsible', 'value': self.agent.id})

        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.responsible, self.agent)
        self.assertIn('Gespeichert', response.content.decode())
        self.assertIn(f'<option value="{self.agent.id}" selected>', response.content.decode())
        mock_notify.assert_called_once()
        self.assertTrue(Activity.objects.filter(verb='item.responsible_changed').exists())

    @patch('core.views._send_responsible_notification')
    def test_clear_responsible(self, mock_notify):
        self.item.responsible = self.agent
        self.item.save()

        response = self.client.post(self.url, {'field': 'responsible', 'value': ''})

        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.responsible)
        mock_notify.assert_not_called()

    def test_non_agent_responsible_is_rejected(self):
        response = self.client.post(self.url, {'field': 'responsible', 'value': self.user.id})

        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.responsible)
        self.assertIn('role="alert"', response.content.decode())

    def test_set_suggested_model(self):
        response = self.client.post(
            self.url, {'field': 'suggested_model', 'value': ClaudeQueueJobModel.OPUS_5}
        )

        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.suggested_model, ClaudeQueueJobModel.OPUS_5)

    def test_invalid_suggested_model_is_rejected(self):
        response = self.client.post(self.url, {'field': 'suggested_model', 'value': 'gpt'})

        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.suggested_model, ClaudeQueueJobModel.SONNET)
        self.assertIn(
            f'<option value="{ClaudeQueueJobModel.SONNET}" selected>',
            response.content.decode(),
        )

    def test_other_fields_are_not_editable_here(self):
        response = self.client.post(self.url, {'field': 'title', 'value': 'Hacked'})

        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'Inline field item')

    def test_get_is_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_login_required(self):
        self.client.logout()
        response = self.client.post(self.url, {'field': 'suggested_model', 'value': 'opus'})
        self.assertEqual(response.status_code, 302)
