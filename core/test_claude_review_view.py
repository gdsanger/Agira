"""Tests for the item "Review durch Claude" action (#1286)."""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobKind,
    ClaudeQueueJobStatus,
    ExternalIssueKind,
    ExternalIssueMapping,
    Item,
    ItemStatus,
    ItemType,
    Project,
    User,
)
from core.services.claude_queue.hint import GIT_WORKFLOW_HINT_MARKER


class ItemClaudeReviewViewTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser', password='testpass123', email='test@example.com',
        )
        self.user.name = 'Test User'
        self.user.active = True
        self.user.save()
        self.client.login(username='testuser', password='testpass123')

        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.item = self._item(ItemStatus.TESTING)
        self._pr(self.item, 1)

    def _item(self, status, **kw):
        return Item.objects.create(
            title='Item', description='Original description.',
            project=self.project, type=self.item_type, status=status, **kw,
        )

    def _pr(self, item, number):
        return ExternalIssueMapping.objects.create(
            item=item, github_id=1000 + number, number=number,
            kind=ExternalIssueKind.PR, state='open',
            html_url=f'https://github.com/o/r/pull/{number}',
        )

    def _post(self, item=None):
        return self.client.post(reverse('item-claude-review', args=[(item or self.item).id]))

    def test_requires_authentication(self):
        self.client.logout()
        self.assertNotEqual(self._post().status_code, 200)

    def test_requires_post(self):
        url = reverse('item-claude-review', args=[self.item.id])
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_success_for_testing_and_integrated(self):
        sub = self._item(ItemStatus.INTEGRATED)
        self._pr(sub, 2)
        for item in (self.item, sub):
            response = self._post(item)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json()['success'])
            job = ClaudeQueueJob.objects.get(item=item)
            self.assertEqual(job.kind, ClaudeQueueJobKind.REVIEW)
            self.assertEqual(job.status, ClaudeQueueJobStatus.QUEUED)
            self.assertIsNone(job.parent_job)

    def test_status_and_description_unchanged(self):
        self._post()
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.TESTING)
        self.assertEqual(self.item.description, 'Original description.')
        self.assertNotIn(GIT_WORKFLOW_HINT_MARKER, self.item.description)

    def test_status_guard_rejects_other_statuses(self):
        for n, status in enumerate((ItemStatus.WORKING, ItemStatus.BACKLOG, ItemStatus.CLOSED)):
            item = self._item(status)
            self._pr(item, 100 + n)
            response = self._post(item)
            self.assertEqual(response.status_code, 400, status)
            self.assertIn('Integrated', response.json()['error'])
            self.assertFalse(ClaudeQueueJob.objects.filter(item=item).exists())

    def test_pr_guard_rejects_item_without_pr(self):
        item = self._item(ItemStatus.TESTING)
        response = self._post(item)
        self.assertEqual(response.status_code, 400)
        self.assertIn('kein PR verknüpft', response.json()['error'])
        self.assertFalse(ClaudeQueueJob.objects.filter(item=item).exists())

    def test_double_click_creates_no_second_job(self):
        first = self._post().json()
        second = self._post().json()
        self.assertTrue(second['success'])
        self.assertTrue(second['no_change'])
        self.assertEqual(second['job_id'], first['job_id'])
        self.assertEqual(ClaudeQueueJob.objects.filter(item=self.item).count(), 1)

    def test_new_review_allowed_after_previous_finished(self):
        first = self._post().json()
        ClaudeQueueJob.objects.filter(pk=first['job_id']).update(
            status=ClaudeQueueJobStatus.DONE,
        )
        second = self._post().json()
        self.assertNotEqual(second['job_id'], first['job_id'])
