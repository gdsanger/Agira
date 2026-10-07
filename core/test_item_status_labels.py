"""
The 'Testing' and 'Review' statuses are shown as "Implemented" and
"Clarification"; their stored values must stay unchanged because REST, MCP,
mail mappings, status history and the search index rely on them.
"""
from django.test import TestCase
from django.urls import reverse

from core.models import ItemStatus, User


class ItemStatusLabelTests(TestCase):

    def test_stored_values_unchanged(self):
        self.assertEqual(ItemStatus.TESTING.value, 'Testing')
        self.assertEqual(ItemStatus.REVIEW.value, 'Review')

    def test_labels(self):
        self.assertEqual(ItemStatus.TESTING.label, '🏁 Implemented')
        self.assertEqual(ItemStatus.REVIEW.label, '❓ Clarification')

    def test_clarification_still_excluded_from_mail_triggers(self):
        values = [value for value, _ in ItemStatus.mail_triggerable_choices()]
        self.assertNotIn(ItemStatus.REVIEW, values)
        self.assertIn(ItemStatus.TESTING, values)

    def test_sidebar_and_list_pages_use_new_names(self):
        user = User.objects.create_user(username='u', email='u@example.com', password='x', name='U')
        self.client.force_login(user)
        response = self.client.get(reverse('items-testing'))
        self.assertContains(response, 'Items - Implemented')
        self.assertContains(response, '>Clarification<')
        self.assertNotContains(response, '>Testing<')
        response = self.client.get(reverse('items-review'))
        self.assertContains(response, 'Items - Clarification')
