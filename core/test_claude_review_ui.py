"""Render tests for the "Review durch Claude" UI (#1287)."""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobKind,
    ClaudeQueueJobStatus,
    ClaudeQueueReviewVerdict,
    ExternalIssueKind,
    ExternalIssueMapping,
    Item,
    ItemStatus,
    ItemType,
    Project,
    User,
)

BUTTON_TEXT = 'Review durch Claude'


class ClaudeReviewUiTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser', password='testpass123', email='test@example.com',
        )
        self.user.name = 'Test User'
        self.user.active = True
        self.user.role = 'Agent'
        self.user.save()
        self.client.login(username='testuser', password='testpass123')
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')

    def _item(self, status, pr=True):
        item = Item.objects.create(
            title='Item', description='d', project=self.project,
            type=self.item_type, status=status,
        )
        if pr:
            ExternalIssueMapping.objects.create(
                item=item, github_id=1000 + item.id, number=item.id,
                kind=ExternalIssueKind.PR, state='open',
                html_url='https://github.com/o/r/pull/1',
            )
        return item

    def _detail(self, item):
        return self.client.get(reverse('item-detail', args=[item.id]))

    def test_button_visible_for_testing_and_integrated_with_pr(self):
        for status in (ItemStatus.TESTING, ItemStatus.INTEGRATED):
            response = self._detail(self._item(status))
            self.assertContains(response, 'onclick="reviewByClaude()"')
            self.assertTrue(response.context['can_claude_review'])

    def test_button_hidden_for_other_status(self):
        response = self._detail(self._item(ItemStatus.WORKING))
        self.assertNotContains(response, 'onclick="reviewByClaude()"')
        self.assertFalse(response.context['can_claude_review'])

    def test_button_hidden_without_pr(self):
        response = self._detail(self._item(ItemStatus.TESTING, pr=False))
        self.assertNotContains(response, 'onclick="reviewByClaude()"')

    def _job(self, **kw):
        item = self._item(ItemStatus.TESTING)
        return ClaudeQueueJob.objects.create(
            item=item, project=self.project, kind=ClaudeQueueJobKind.REVIEW,
            status=ClaudeQueueJobStatus.DONE, **kw,
        )

    def test_queue_list_shows_review_and_verdict_badge(self):
        self._job(review_verdict=ClaudeQueueReviewVerdict.DEVIATIONS)
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertContains(response, '> Review</span>')
        self.assertContains(response, 'Abweichungen')

    def test_unclear_shows_manual_check_hint(self):
        self._job(review_verdict=ClaudeQueueReviewVerdict.UNCLEAR)
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertContains(response, 'manuelle Prüfung nötig')

    def test_job_detail_shows_report_and_followup_link(self):
        followup = self._item(ItemStatus.BACKLOG, pr=False)
        job = self._job(
            review_verdict=ClaudeQueueReviewVerdict.DEVIATIONS,
            review_report='## Bericht\n\nEine Abweichung.',
            review_followup_item=followup,
        )
        response = self.client.get(reverse('claude-queue-job-detail', args=[job.id]))
        self.assertContains(response, 'Review-Ergebnis')
        self.assertContains(response, 'Eine Abweichung.')
        self.assertContains(response, reverse('item-detail', args=[followup.id]))

    def test_non_review_job_has_no_review_badge(self):
        item = self._item(ItemStatus.WORKING, pr=False)
        ClaudeQueueJob.objects.create(
            item=item, project=self.project, status=ClaudeQueueJobStatus.QUEUED,
        )
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertNotContains(response, '> Review</span>')
