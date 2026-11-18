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


class ItemsClaudeReviewBulkViewTestCase(TestCase):
    """Bulk review from the list views."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='bulkuser', password='testpass123', email='bulk@example.com',
        )
        self.user.name = 'Bulk User'
        self.user.active = True
        self.user.save()
        self.client.login(username='bulkuser', password='testpass123')
        self.project = Project.objects.create(name='Bulk Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.url = reverse('items-claude-review-bulk')

    def _item(self, status, with_pr=True, n=[0]):
        item = Item.objects.create(
            title='Item', project=self.project, type=self.item_type, status=status,
        )
        if with_pr:
            n[0] += 1
            ExternalIssueMapping.objects.create(
                item=item, github_id=5000 + n[0], number=n[0],
                kind=ExternalIssueKind.PR, state='open',
                html_url=f'https://github.com/o/r/pull/{n[0]}',
            )
        return item

    def test_requires_post(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_empty_selection_rejected(self):
        self.assertEqual(self.client.post(self.url).status_code, 400)

    def test_mixed_batch_reports_per_item(self):
        ok = self._item(ItemStatus.TESTING)
        dup = self._item(ItemStatus.INTEGRATED)
        bad_status = self._item(ItemStatus.BACKLOG)
        no_pr = self._item(ItemStatus.TESTING, with_pr=False)
        self.client.post(self.url, {'item_ids': [dup.id]})
        response = self.client.post(
            self.url,
            {'item_ids': [ok.id, dup.id, bad_status.id, no_pr.id, 999999, 'x']},
        )
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(data['success'])
        self.assertEqual([e['item_id'] for e in data['enqueued']], [ok.id])
        self.assertEqual([e['item_id'] for e in data['existing']], [dup.id])
        self.assertEqual(
            sorted(f['item_id'] for f in data['failed']),
            sorted([bad_status.id, no_pr.id, 999999]),
        )
        self.assertEqual(
            ClaudeQueueJob.objects.filter(kind=ClaudeQueueJobKind.REVIEW).count(), 2,
        )


class ItemsBulkFieldUpdateViewTestCase(TestCase):
    """Bulk assignment of suggested_model / assigned_to / parent from the lists."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='fielduser', password='testpass123', email='f@example.com',
        )
        self.user.name = 'Field User'
        self.user.active = True
        self.user.save()
        self.client.login(username='fielduser', password='testpass123')
        self.project = Project.objects.create(name='P1')
        self.other_project = Project.objects.create(name='P2')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.url = reverse('items-bulk-field')

    def _item(self, project=None, status=ItemStatus.BACKLOG):
        return Item.objects.create(
            title='I', project=project or self.project, type=self.item_type, status=status,
        )

    def test_requires_post_and_valid_field(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        item = self._item()
        r = self.client.post(self.url, {'field': 'status', 'value': 'Closed', 'item_ids': [item.id]})
        self.assertEqual(r.status_code, 400)
        r = self.client.post(self.url, {'field': 'parent', 'value': ''})
        self.assertEqual(r.status_code, 400)

    def test_assign_user_and_clear(self):
        a, b = self._item(), self._item()
        r = self.client.post(self.url, {
            'field': 'assigned_to', 'value': self.user.id, 'item_ids': [a.id, b.id],
        })
        self.assertEqual(len(r.json()['updated']), 2)
        a.refresh_from_db()
        self.assertEqual(a.assigned_to, self.user)
        self.client.post(self.url, {'field': 'assigned_to', 'value': '', 'item_ids': [a.id]})
        a.refresh_from_db()
        self.assertIsNone(a.assigned_to)

    def test_suggested_model(self):
        item = self._item()
        r = self.client.post(self.url, {
            'field': 'suggested_model', 'value': 'opus-5-5', 'item_ids': [item.id],
        })
        self.assertTrue(r.json()['success'], r.json())
        item.refresh_from_db()
        self.assertEqual(item.suggested_model, 'opus-5-5')

    def test_parent_reports_per_item_failures(self):
        parent = self._item()
        ok = self._item()
        other = self._item(project=self.other_project)
        r = self.client.post(self.url, {
            'field': 'parent', 'value': parent.id,
            'item_ids': [ok.id, other.id, parent.id],
        })
        data = r.json()
        self.assertEqual(data['updated'], [ok.id])
        self.assertEqual(sorted(f['item_id'] for f in data['failed']), sorted([other.id, parent.id]))
        ok.refresh_from_db()
        self.assertEqual(ok.parent, parent)
