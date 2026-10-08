"""Tests for the Closed items list view (``/items/closed/``)."""
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Item, ItemStatus, ItemType, Project, ProjectStatus, User


class ItemsClosedViewTestCase(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create(
            username="closeduser", email="closeduser@example.com", active=True,
        )
        self.user.set_password("testpass123")
        self.user.save()
        self.project = Project.objects.create(name="P", status=ProjectStatus.WORKING)
        self.project.members.add(self.user)
        item_type = ItemType.objects.create(name="Bug", is_active=True)
        self.closed = Item.objects.create(
            title="Closed item", status=ItemStatus.CLOSED, type=item_type, project=self.project,
        )
        self.open = Item.objects.create(
            title="Open item", status=ItemStatus.WORKING, type=item_type, project=self.project,
        )
        self.client.login(username="closeduser", password="testpass123")

    def test_shows_only_closed_items(self):
        response = self.client.get(reverse('items-closed'))

        self.assertEqual(response.status_code, 200)
        ids = [item.id for item in response.context['table'].data]
        self.assertEqual(ids, [self.closed.id])
        self.assertEqual(response.context['page_title'], 'Items - Closed')

    def test_sidebar_links_to_closed_view(self):
        response = self.client.get(reverse('items-closed'))
        self.assertContains(response, f'href="{reverse("items-closed")}"')

    def test_login_required(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse('items-closed')).status_code, 302)

    def test_delete_from_closed_list_rerenders_closed_list(self):
        response = self.client.post(
            reverse('item-list-delete', kwargs={'item_id': self.closed.id}),
            HTTP_REFERER='/items/closed/',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Item.objects.filter(id=self.closed.id).exists())
        self.assertIn('items-list-container', response.content.decode())
