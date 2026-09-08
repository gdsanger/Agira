"""
Tests for visible item IDs and mail-free inline status editing in item lists (#1249).

Covers the two lists named in the issue - ``/items/{status}/`` and the items list in
``/projects/{id}/`` - plus the shared endpoint they both post to.
"""
from django.core import mail
from django.test import Client, TestCase
from django.urls import reverse

from core.models import (
    Activity,
    Item,
    ItemStatus,
    ItemType,
    MailActionMapping,
    MailTemplate,
    Organisation,
    Project,
    ProjectStatus,
    User,
)


class ItemListStatusInlineTestCase(TestCase):
    """Item ID visibility and inline status editing across the item lists."""

    def setUp(self):
        self.client = Client()

        self.org = Organisation.objects.create(name="Test Organisation")

        self.user = User.objects.create(
            username="listuser",
            email="listuser@example.com",
            active=True,
        )
        self.user.set_password("testpass123")
        self.user.save()

        self.project = Project.objects.create(
            name="Status Project",
            status=ProjectStatus.WORKING,
        )
        # Lists are scoped to the projects assigned to the user (#1248).
        self.project.members.add(self.user)

        self.item_type = ItemType.objects.create(name="Bug", is_active=True)

        self.item = Item.objects.create(
            title="Inline status item",
            description="An item to switch status on",
            status=ItemStatus.INBOX,
            type=self.item_type,
            project=self.project,
            organisation=self.org,
        )

        self.client.login(username="listuser", password="testpass123")

    # ------------------------------------------------------------------
    # 1 + 2: ID and status are visible in the lists
    # ------------------------------------------------------------------

    def test_status_list_shows_item_id_and_status_select(self):
        """`/items/inbox/` shows the ID as text and the status as an inline select."""
        response = self.client.get(reverse('items-inbox'))
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'#{self.item.id}', content)
        self.assertIn(f'id="item-status-cell-{self.item.id}"', content)
        self.assertIn(
            f'hx-post="{reverse("item-list-status", kwargs={"item_id": self.item.id})}"',
            content,
        )
        self.assertIn('<option value="Inbox" selected>', content)

    def test_project_items_tab_shows_item_id_and_status_select(self):
        """The items list in the project detail shows the same ID and status cell."""
        response = self.client.get(
            reverse('project-items-tab', kwargs={'id': self.project.id})
        )
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'#{self.item.id}', content)
        self.assertIn(f'id="item-status-cell-{self.item.id}"', content)
        self.assertIn(
            f'hx-post="{reverse("item-list-status", kwargs={"item_id": self.item.id})}"',
            content,
        )
        self.assertIn('<option value="Inbox" selected>', content)

    def test_lists_offer_every_model_status(self):
        """The select is built from ItemStatus - no hardcoded subset, no new values."""
        response = self.client.get(reverse('items-inbox'))
        content = response.content.decode()

        for value, _label in ItemStatus.choices:
            self.assertIn(f'<option value="{value}"', content)

    # ------------------------------------------------------------------
    # 3: the status can be changed from the list
    # ------------------------------------------------------------------

    def test_status_update_persists_and_returns_refreshed_cell(self):
        response = self.client.post(
            reverse('item-list-status', kwargs={'item_id': self.item.id}),
            {'status': ItemStatus.WORKING},
        )
        content = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)
        self.assertIn('<option value="Working" selected>', content)
        self.assertNotIn('<option value="Inbox" selected>', content)

    def test_status_update_logs_activity(self):
        """The list path keeps the workflow guard's activity log."""
        self.client.post(
            reverse('item-list-status', kwargs={'item_id': self.item.id}),
            {'status': ItemStatus.BACKLOG},
        )

        self.assertTrue(
            Activity.objects.filter(verb='item.status_changed').exists(),
            "Status change from a list must still be logged as an activity",
        )

    def test_status_bound_list_drops_the_item_after_the_change(self):
        """After moving out of Inbox the item is gone from `/items/inbox/` on refresh."""
        self.client.post(
            reverse('item-list-status', kwargs={'item_id': self.item.id}),
            {'status': ItemStatus.BACKLOG},
        )

        inbox = self.client.get(reverse('items-inbox')).content.decode()
        backlog = self.client.get(reverse('items-backlog')).content.decode()

        self.assertNotIn(f'id="item-status-cell-{self.item.id}"', inbox)
        self.assertIn(f'id="item-status-cell-{self.item.id}"', backlog)

    # ------------------------------------------------------------------
    # 4: no mail flow
    # ------------------------------------------------------------------

    def test_status_update_does_not_send_or_offer_mail(self):
        """A configured mail trigger must not fire and must not open a mail modal.

        The same status change through `item-change-status` (the DetailView path)
        answers with a `mail_preview` JSON payload; the list endpoint must not.
        """
        template = MailTemplate.objects.create(
            key='status-working',
            subject='Item {{ issue.title }} is being worked on',
            message='Status: {{ issue.status }}',
        )
        MailActionMapping.objects.create(
            is_active=True,
            item_status=ItemStatus.WORKING,
            item_type=self.item_type,
            mail_template=template,
        )

        mail.outbox = []
        response = self.client.post(
            reverse('item-list-status', kwargs={'item_id': self.item.id}),
            {'status': ItemStatus.WORKING},
        )
        content = response.content.decode()

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)
        self.assertEqual(len(mail.outbox), 0)
        self.assertNotIn('mail_preview', content)
        self.assertIn(f'id="item-status-cell-{self.item.id}"', content)

    # ------------------------------------------------------------------
    # 5: errors, validation and permissions
    # ------------------------------------------------------------------

    def test_invalid_status_is_rejected_and_cell_stays_consistent(self):
        response = self.client.post(
            reverse('item-list-status', kwargs={'item_id': self.item.id}),
            {'status': 'NotAStatus'},
        )
        content = response.content.decode()

        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.INBOX)
        # The cell is re-rendered from the stored status, not from the rejected pick.
        self.assertIn('<option value="Inbox" selected>', content)
        self.assertIn('item-status-feedback-error', content)
        self.assertNotIn('<option value="NotAStatus"', content)

    def test_missing_status_is_rejected(self):
        response = self.client.post(
            reverse('item-list-status', kwargs={'item_id': self.item.id}),
            {},
        )

        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.INBOX)
        self.assertIn('item-status-feedback-error', response.content.decode())

    def test_get_is_not_allowed(self):
        response = self.client.get(
            reverse('item-list-status', kwargs={'item_id': self.item.id})
        )
        self.assertEqual(response.status_code, 405)

    def test_login_required(self):
        self.client.logout()
        response = self.client.post(
            reverse('item-list-status', kwargs={'item_id': self.item.id}),
            {'status': ItemStatus.WORKING},
        )

        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.INBOX)

    def test_unknown_item_returns_404(self):
        response = self.client.post(
            reverse('item-list-status', kwargs={'item_id': 999999}),
            {'status': ItemStatus.WORKING},
        )
        self.assertEqual(response.status_code, 404)
