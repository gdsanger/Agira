"""
Tests for the generic inline field-update endpoint / service (Issue #996).

Covers the consolidated ``item-update-field`` endpoint: whitelist enforcement,
per-field validation & FK-resolution, activity logging, the responsible e-mail hook,
and preservation of model-level side effects (requester -> organisation auto-update).
"""
from unittest.mock import patch

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import (
    Organisation, UserOrganisation, Project, ItemType, Item,
    ItemStatus, Release, Activity,
)
from core.services.item_field_update import (
    apply_field_update,
    FieldUpdateError,
    FIELD_SPECS,
    is_editable_field,
)

User = get_user_model()


class GenericFieldUpdateTestBase(TestCase):
    def setUp(self):
        self.agent = User.objects.create_user(
            username='agent', email='agent@example.com', password='pw',
            name='Agent One', role='Agent',
        )
        self.plain_user = User.objects.create_user(
            username='plain', email='plain@example.com', password='pw',
            name='Plain User', role='User',
        )
        self.org = Organisation.objects.create(name='Org A', short='ORGA')
        self.org_b = Organisation.objects.create(name='Org B', short='ORGB')
        UserOrganisation.objects.create(user=self.plain_user, organisation=self.org_b, is_primary=True)

        self.project = Project.objects.create(name='Proj', description='d')
        self.item_type = ItemType.objects.create(key='bug', name='Bug', is_active=True)
        self.item_type_feature = ItemType.objects.create(key='feature', name='Feature', is_active=True)
        self.release = Release.objects.create(project=self.project, name='R1', version='1.0.0')

        self.item = Item.objects.create(
            project=self.project, title='Original Title', type=self.item_type,
            organisation=self.org, status=ItemStatus.WORKING,
        )

        self.client = Client()
        self.client.login(username='agent', password='pw')

    def url(self):
        return reverse('item-update-field', args=[self.item.id])


class WhitelistTest(GenericFieldUpdateTestBase):
    def test_status_field_is_not_editable(self):
        self.assertFalse(is_editable_field('status'))
        response = self.client.post(self.url(), {'field': 'status', 'value': 'Closed'})
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

    def test_description_field_is_not_editable(self):
        self.assertFalse(is_editable_field('description'))
        response = self.client.post(self.url(), {'field': 'description', 'value': 'hacked'})
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.description, '')

    def test_unknown_field_rejected(self):
        response = self.client.post(self.url(), {'field': 'id', 'value': '999'})
        self.assertEqual(response.status_code, 400)

    def test_service_raises_for_non_whitelisted_field(self):
        with self.assertRaises(FieldUpdateError):
            apply_field_update(self.item, 'status', 'Closed', actor=self.agent)


class TextFieldTest(GenericFieldUpdateTestBase):
    def test_title_updates(self):
        response = self.client.post(self.url(), {'field': 'title', 'value': 'New Title'})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'New Title')

    def test_title_rejects_empty(self):
        response = self.client.post(self.url(), {'field': 'title', 'value': '   '})
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'Original Title')

    def test_short_description_allows_empty(self):
        response = self.client.post(self.url(), {'field': 'short_description', 'value': ''})
        self.assertEqual(response.status_code, 200)


class BoolFieldTest(GenericFieldUpdateTestBase):
    def test_intern_true_then_false(self):
        self.client.post(self.url(), {'field': 'intern', 'value': 'true'})
        self.item.refresh_from_db()
        self.assertTrue(self.item.intern)
        self.client.post(self.url(), {'field': 'intern', 'value': 'false'})
        self.item.refresh_from_db()
        self.assertFalse(self.item.intern)


class ForeignKeyFieldTest(GenericFieldUpdateTestBase):
    def test_type_updates(self):
        response = self.client.post(self.url(), {'field': 'type', 'value': self.item_type_feature.id})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.type, self.item_type_feature)

    def test_organisation_can_be_cleared(self):
        response = self.client.post(self.url(), {'field': 'organisation', 'value': ''})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.organisation)

    def test_assigned_to_updates(self):
        response = self.client.post(self.url(), {'field': 'assigned_to', 'value': self.plain_user.id})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.assigned_to, self.plain_user)

    def test_invalid_fk_id_rejected(self):
        response = self.client.post(self.url(), {'field': 'organisation', 'value': '999999'})
        self.assertEqual(response.status_code, 400)


class ResponsibleFieldTest(GenericFieldUpdateTestBase):
    def test_responsible_must_be_agent(self):
        response = self.client.post(self.url(), {'field': 'responsible', 'value': self.plain_user.id})
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.responsible)

    @patch('core.views._send_responsible_notification')
    def test_responsible_agent_assigned_sends_email(self, mock_mail):
        response = self.client.post(self.url(), {'field': 'responsible', 'value': self.agent.id})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.responsible, self.agent)
        mock_mail.assert_called_once()

    @patch('core.views._send_responsible_notification')
    def test_no_email_when_unchanged(self, mock_mail):
        self.item.responsible = self.agent
        self.item.save()
        response = self.client.post(self.url(), {'field': 'responsible', 'value': self.agent.id})
        self.assertEqual(response.status_code, 200)
        mock_mail.assert_not_called()


class RequesterOrganisationSideEffectTest(GenericFieldUpdateTestBase):
    def test_requester_change_autofills_organisation(self):
        # plain_user's primary org is org_b -> item.organisation should follow
        response = self.client.post(self.url(), {'field': 'requester', 'value': self.plain_user.id})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.requester, self.plain_user)
        self.assertEqual(self.item.organisation, self.org_b)


class SuggestedModelFieldTest(GenericFieldUpdateTestBase):
    """Inline HTMX editing of the manually overridable suggested_model (#1072)."""

    def test_suggested_model_updates_to_opus_4_8(self):
        response = self.client.post(self.url(), {'field': 'suggested_model', 'value': 'opus-4-8'})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.suggested_model, 'opus-4-8')

    def test_suggested_model_updates_to_opus_5(self):
        response = self.client.post(self.url(), {'field': 'suggested_model', 'value': 'opus-5'})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.suggested_model, 'opus-5')

    def test_suggested_model_updates_to_fable_5(self):
        response = self.client.post(self.url(), {'field': 'suggested_model', 'value': 'fable-5'})
        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.suggested_model, 'fable-5')

    def test_legacy_opus_value_rejected(self):
        """The pre-#1082 generic slug is gone; it must not slip through."""
        response = self.client.post(self.url(), {'field': 'suggested_model', 'value': 'opus'})
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertNotEqual(self.item.suggested_model, 'opus')

    def test_response_fragment_reports_success(self):
        response = self.client.post(self.url(), {'field': 'suggested_model', 'value': 'opus-5'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Gespeichert')

    def test_invalid_value_rejected(self):
        self.item.suggested_model = 'sonnet'
        self.item.save()
        response = self.client.post(self.url(), {'field': 'suggested_model', 'value': 'fable'})
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.suggested_model, 'sonnet')

    def test_empty_value_rejected(self):
        response = self.client.post(self.url(), {'field': 'suggested_model', 'value': ''})
        self.assertEqual(response.status_code, 400)


class ActivityLoggingTest(GenericFieldUpdateTestBase):
    def test_change_creates_activity(self):
        before = Activity.objects.count()
        self.client.post(self.url(), {'field': 'title', 'value': 'Logged Title'})
        self.assertEqual(Activity.objects.count(), before + 1)

    def test_no_activity_when_value_unchanged(self):
        before = Activity.objects.count()
        # title already 'Original Title'
        self.client.post(self.url(), {'field': 'title', 'value': 'Original Title'})
        self.assertEqual(Activity.objects.count(), before)


class FieldSpecRegistryTest(TestCase):
    def test_excluded_fields_absent(self):
        self.assertNotIn('status', FIELD_SPECS)
        self.assertNotIn('description', FIELD_SPECS)

    def test_expected_fields_present(self):
        for name in ['title', 'short_description', 'intern', 'type', 'organisation',
                     'requester', 'assigned_to', 'responsible', 'parent', 'solution_release',
                     'suggested_model']:
            self.assertIn(name, FIELD_SPECS)
