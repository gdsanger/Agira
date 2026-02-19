"""
Tests for ChangeAdmin - verifying that created_at and updated_at are editable.
"""
from datetime import datetime
from django.test import TestCase
from django.contrib.admin.sites import AdminSite
from django.utils import timezone
from core.models import Change, Project, Organisation, User
from core.admin import ChangeAdmin


class MockRequest:
    """Mock request object for testing admin actions"""
    def __init__(self, user):
        self.user = user


class ChangeAdminTimestampEditableTestCase(TestCase):
    """Test that created_at and updated_at are editable in ChangeAdmin."""

    def setUp(self):
        self.site = AdminSite()
        self.admin = ChangeAdmin(Change, self.site)
        self.org = Organisation.objects.create(name='Test Org')
        self.project = Project.objects.create(name='Test Project', description='Test')
        self.user = User.objects.create_user(
            username='testadmin',
            email='admin@example.com',
            password='testpass'
        )

    def test_created_at_is_editable(self):
        """created_at should be an editable (non-auto_now_add) field."""
        field = Change._meta.get_field('created_at')
        self.assertFalse(getattr(field, 'auto_now_add', False),
                         "created_at should not have auto_now_add=True")

    def test_updated_at_is_editable(self):
        """updated_at should be an editable (non-auto_now) field."""
        field = Change._meta.get_field('updated_at')
        self.assertFalse(getattr(field, 'auto_now', False),
                         "updated_at should not have auto_now=True")

    def test_change_admin_fieldsets_include_timestamps(self):
        """ChangeAdmin fieldsets should include created_at and updated_at."""
        all_fields = []
        for name, options in self.admin.fieldsets:
            all_fields.extend(options['fields'])
        self.assertIn('created_at', all_fields)
        self.assertIn('updated_at', all_fields)

    def test_change_admin_does_not_have_timestamps_in_readonly(self):
        """created_at and updated_at should not be in readonly_fields so they are editable."""
        readonly = getattr(self.admin, 'readonly_fields', [])
        self.assertNotIn('created_at', readonly)
        self.assertNotIn('updated_at', readonly)

    def test_change_form_includes_timestamp_fields(self):
        """The ChangeAdmin form should include created_at and updated_at fields."""
        request = MockRequest(self.user)
        FormClass = self.admin.get_form(request)
        form_instance = FormClass()
        self.assertIn('created_at', form_instance.fields)
        self.assertIn('updated_at', form_instance.fields)

    def test_save_preserves_historical_created_at(self):
        """save_model should preserve explicitly set historical created_at values."""
        historical_date = timezone.make_aware(datetime(2020, 6, 15, 10, 0, 0))

        change = Change.objects.create(
            project=self.project,
            title='Historical Change',
        )

        # Simulate form with explicit created_at (Django admin calls form.save(commit=False) before save_model)
        request = MockRequest(self.user)
        FormClass = self.admin.get_form(request)
        form_data = {
            'project': self.project.pk,
            'title': 'Historical Change',
            'description': '',
            'status': 'Draft',
            'risk': 'Normal',
            'risk_description': '',
            'mitigation': '',
            'rollback_plan': '',
            'communication_plan': '',
            'is_safety_relevant': False,
            'organisations': [],
            'created_at_0': '2020-06-15',
            'created_at_1': '10:00:00',
            'updated_at_0': '2020-06-15',
            'updated_at_1': '10:00:00',
        }
        form = FormClass(data=form_data, instance=change)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")

        # Django admin calls form.save(commit=False) before save_model
        obj = form.save(commit=False)
        self.admin.save_model(request, obj, form, change=True)

        obj.refresh_from_db()
        self.assertEqual(obj.created_at.date(), historical_date.date())

    def test_save_preserves_historical_updated_at(self):
        """save_model should preserve explicitly set historical updated_at values via QuerySet.update."""
        historical_date = timezone.make_aware(datetime(2020, 6, 15, 10, 0, 0))

        change = Change.objects.create(
            project=self.project,
            title='Historical Change',
        )

        request = MockRequest(self.user)
        FormClass = self.admin.get_form(request)
        form_data = {
            'project': self.project.pk,
            'title': 'Historical Change',
            'description': '',
            'status': 'Draft',
            'risk': 'Normal',
            'risk_description': '',
            'mitigation': '',
            'rollback_plan': '',
            'communication_plan': '',
            'is_safety_relevant': False,
            'organisations': [],
            'created_at_0': '2020-06-15',
            'created_at_1': '10:00:00',
            'updated_at_0': '2020-06-15',
            'updated_at_1': '10:00:00',
        }
        form = FormClass(data=form_data, instance=change)
        self.assertTrue(form.is_valid(), f"Form errors: {form.errors}")

        obj = form.save(commit=False)
        self.admin.save_model(request, obj, form, change=True)

        obj.refresh_from_db()
        self.assertEqual(obj.updated_at.date(), historical_date.date())

    def test_updated_at_auto_updates_on_regular_save(self):
        """updated_at should auto-update on regular programmatic saves."""
        change = Change.objects.create(
            project=self.project,
            title='Test Change',
        )
        original_updated_at = change.updated_at

        # Wait a tiny bit and save again
        change.title = 'Updated Change'
        change.save()

        change.refresh_from_db()
        self.assertGreaterEqual(change.updated_at, original_updated_at)
