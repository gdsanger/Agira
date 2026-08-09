"""Tests for the item-detail "an Claude übergeben" action (#833)."""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    CLAUDE_CLI_MODEL_IDS,
    ClaudeQueueJob,
    ClaudeQueueJobModel,
    ClaudeQueueJobStatus,
    Item,
    ItemStatus,
    ItemType,
    Project,
    User,
)
from core.services.claude_queue.hint import GIT_WORKFLOW_HINT_MARKER


class ItemClaudeEnqueueViewTestCase(TestCase):
    def setUp(self):
        self.client = Client()

        self.user = User.objects.create_user(
            username='testuser', password='testpass123', email='test@example.com',
        )
        self.user.name = 'Test User'
        self.user.active = True
        self.user.save()

        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.item = Item.objects.create(
            title='Fix the login bug',
            description='Original description.',
            project=self.project,
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )

    def _url(self, item_id=None):
        return reverse('item-claude-enqueue', args=[item_id or self.item.id])

    def test_requires_authentication(self):
        response = self.client.post(self._url())
        self.assertNotEqual(response.status_code, 200)

    def test_requires_post(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 405)

    def test_enqueue_creates_job_appends_hint_sets_working(self):
        self.client.login(username='testuser', password='testpass123')

        response = self.client.post(self._url())

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertNotIn('no_change', data)

        self.assertEqual(ClaudeQueueJob.objects.filter(item=self.item).count(), 1)
        job = ClaudeQueueJob.objects.get(item=self.item)
        self.assertEqual(job.status, ClaudeQueueJobStatus.QUEUED)
        self.assertEqual(job.pk, data['job_id'])

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)
        self.assertEqual(self.item.description.count(GIT_WORKFLOW_HINT_MARKER), 1)

    def test_reenqueue_does_not_duplicate_job_or_hint(self):
        self.client.login(username='testuser', password='testpass123')

        self.client.post(self._url())
        response = self.client.post(self._url())

        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data.get('no_change'))
        self.assertEqual(ClaudeQueueJob.objects.filter(item=self.item).count(), 1)

        self.item.refresh_from_db()
        self.assertEqual(self.item.description.count(GIT_WORKFLOW_HINT_MARKER), 1)

    def test_rejects_closed_item(self):
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        self.client.login(username='testuser', password='testpass123')

        response = self.client.post(self._url())

        self.assertEqual(response.status_code, 400)
        self.assertEqual(ClaudeQueueJob.objects.filter(item=self.item).count(), 0)

    def test_returns_404_for_unknown_item(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(self._url(item_id=999999))
        self.assertEqual(response.status_code, 404)

    def test_rejects_unmapped_suggested_model(self):
        """A stale/unmapped model slug is rejected before a job is created (#1090).

        ``suggested_model`` is a plain CharField — Django's ``choices`` is
        enforced by ``Item.save()`` (via ``full_clean()``) on the normal write
        path, but a bulk ``.update()`` — exactly how migration 0075 rewrote
        this column, and how a future consolidation would too — bypasses it
        and can leave a row carrying a slug the CLI mapping doesn't know.
        That stale value must not reach the worker.
        """
        Item.objects.filter(pk=self.item.pk).update(suggested_model='opus-5-preview')
        self.item.refresh_from_db()
        self.client.login(username='testuser', password='testpass123')

        response = self.client.post(self._url())

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('opus-5-preview', data['error'])

        self.assertEqual(ClaudeQueueJob.objects.filter(item=self.item).count(), 0)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.BACKLOG)

    def test_every_selectable_model_has_a_cli_translation(self):
        """Every UI-offered model choice maps to a known `claude --model` value.

        Guards against #1090's failure mode at the source: a choice added to
        ``ClaudeQueueJobModel`` without a matching ``CLAUDE_CLI_MODEL_IDS``
        entry would otherwise only surface once a job for it actually failed.
        """
        self.assertEqual(set(ClaudeQueueJobModel.values), set(CLAUDE_CLI_MODEL_IDS.keys()))
        for value, cli_model in CLAUDE_CLI_MODEL_IDS.items():
            self.assertTrue(cli_model, f'{value} has no CLI model string')

    def test_enqueue_succeeds_for_every_selectable_model(self):
        self.client.login(username='testuser', password='testpass123')

        for value in ClaudeQueueJobModel.values:
            with self.subTest(model=value):
                item = Item.objects.create(
                    title=f'Item for {value}',
                    project=self.project,
                    type=self.item_type,
                    status=ItemStatus.BACKLOG,
                    suggested_model=value,
                )

                response = self.client.post(self._url(item_id=item.id))

                self.assertEqual(response.status_code, 200)
                job = ClaudeQueueJob.objects.get(item=item)
                self.assertEqual(job.model, value)
