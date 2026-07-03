"""Tests for wiring the suggested_model classifier (#834) into the item
create/update views."""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import Item, ItemType, Project

User = get_user_model()


class ItemSuggestedModelViewTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            name='Test User',
            role='Agent',
        )
        self.client.login(username='testuser', password='testpass')

        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')

    def test_create_classifies_security_sensitive_item_as_opus(self):
        response = self.client.post(reverse('item-create'), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Fix auth bug',
            'description': 'Fix an authentication bypass vulnerability in the login form.',
        })

        self.assertEqual(response.status_code, 200)
        item = Item.objects.get(id=response.json()['item_id'])
        self.assertEqual(item.suggested_model, 'opus')

    def test_create_classifies_well_scoped_item_as_sonnet(self):
        response = self.client.post(reverse('item-create'), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Rename export button',
            'description': 'Change the label on the export button from "Export" to "Download CSV".',
        })

        self.assertEqual(response.status_code, 200)
        item = Item.objects.get(id=response.json()['item_id'])
        self.assertEqual(item.suggested_model, 'sonnet')

    def test_create_respects_manual_override(self):
        response = self.client.post(reverse('item-create'), {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Rename export button',
            'description': 'Change the label on the export button from "Export" to "Download CSV".',
            'suggested_model': 'opus',
        })

        self.assertEqual(response.status_code, 200)
        item = Item.objects.get(id=response.json()['item_id'])
        self.assertEqual(item.suggested_model, 'opus')

    def test_update_without_suggested_model_field_leaves_it_unchanged(self):
        item = Item.objects.create(
            title='Existing item', description='Some description.',
            project=self.project, type=self.item_type, suggested_model='opus',
        )

        response = self.client.post(reverse('item-update', args=[item.id]), {
            'title': 'Existing item (renamed)',
        })

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.suggested_model, 'opus')

    def test_update_with_explicit_override_changes_it(self):
        item = Item.objects.create(
            title='Existing item', description='Some description.',
            project=self.project, type=self.item_type, suggested_model='sonnet',
        )

        response = self.client.post(reverse('item-update', args=[item.id]), {
            'title': item.title,
            'suggested_model': 'opus',
        })

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.suggested_model, 'opus')

    def test_update_with_auto_detect_reclassifies(self):
        item = Item.objects.create(
            title='Existing item',
            description='Fix an authentication bypass vulnerability in the login form.',
            project=self.project, type=self.item_type, suggested_model='sonnet',
        )

        response = self.client.post(reverse('item-update', args=[item.id]), {
            'title': item.title,
            'suggested_model': '',
        })

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.suggested_model, 'opus')
