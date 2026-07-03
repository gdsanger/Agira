"""Tests for the item-detail "an Claude übergeben" action (#833)."""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    ClaudeQueueJob,
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
