"""
Tests for the Claude Queue visibility views (list, detail, and HTMX polling
partials).
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.db.models import Max
from django.utils import timezone

from core.models import (
    Item, Project, ItemStatus, ItemType, User,
    ClaudeQueueJob, ClaudeQueueJobStatus,
    CLAUDE_QUEUE_JOB_LONG_RUNNING_SECONDS,
)


class ClaudeQueueViewsTestCase(TestCase):
    """Test case for the Claude Queue list/detail/partial views."""

    def setUp(self):
        self.client = Client()

        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com',
        )
        self.user.name = 'Test User'
        self.user.active = True
        self.user.save()

        self.project = Project.objects.create(
            name='Test Project',
            description='Test project description',
        )
        self.other_project = Project.objects.create(
            name='Other Project',
            description='Another project',
        )
        self.item_type = ItemType.objects.create(
            key='bug', name='Bug', description='Bug type',
        )
        self.item = Item.objects.create(
            title='Fix the auth bug',
            description='desc',
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
        )
        self.other_item = Item.objects.create(
            title='Other item',
            description='desc',
            project=self.other_project,
            type=self.item_type,
            status=ItemStatus.WORKING,
        )

    # ---- helpers -------------------------------------------------------

    def _running_job(self):
        return ClaudeQueueJob.objects.create(
            item=self.item,
            project=self.project,
            status=ClaudeQueueJobStatus.RUNNING,
            progress_text='reads auth.py',
        )

    def _done_job(self):
        return ClaudeQueueJob.objects.create(
            item=self.item,
            project=self.project,
            status=ClaudeQueueJobStatus.DONE,
            num_turns=12,
            total_cost_usd=Decimal('0.4231'),
            pr_number=42,
            pr_url='https://github.com/acme/repo/pull/42',
        )

    def _failed_job(self):
        return ClaudeQueueJob.objects.create(
            item=self.item,
            project=self.project,
            status=ClaudeQueueJobStatus.FAILED,
            error_text='boom: something went wrong',
        )

    # ---- auth ----------------------------------------------------------

    def test_list_requires_authentication(self):
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_detail_requires_authentication(self):
        job = self._running_job()
        response = self.client.get(reverse('claude-queue-job-detail', args=[job.id]))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    # ---- list view -----------------------------------------------------

    def test_list_shows_jobs(self):
        self.client.login(username='testuser', password='testpass123')
        self._running_job()
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fix the auth bug')
        self.assertContains(response, 'reads auth.py')

    def test_list_filter_by_project(self):
        self.client.login(username='testuser', password='testpass123')
        self._running_job()
        ClaudeQueueJob.objects.create(
            item=self.other_item, project=self.other_project,
            status=ClaudeQueueJobStatus.RUNNING,
        )
        response = self.client.get(
            reverse('claude-queue-jobs'), {'project': self.project.id}
        )
        self.assertContains(response, 'Fix the auth bug')
        self.assertNotContains(response, 'Other item')

    def test_list_filter_by_status(self):
        self.client.login(username='testuser', password='testpass123')
        self._running_job()
        self._done_job()
        response = self.client.get(
            reverse('claude-queue-jobs'), {'status': ClaudeQueueJobStatus.DONE}
        )
        # The done job carries a PR link; the running one shows progress text.
        self.assertContains(response, 'PR #42')
        self.assertNotContains(response, 'reads auth.py')

    def test_list_invalid_project_filter_is_ignored(self):
        self.client.login(username='testuser', password='testpass123')
        self._running_job()
        response = self.client.get(
            reverse('claude-queue-jobs'), {'project': 'not-a-number'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Fix the auth bug')

    # ---- row partial (list polling) -----------------------------------

    def test_row_active_job_has_polling_attributes(self):
        self.client.login(username='testuser', password='testpass123')
        job = self._running_job()
        response = self.client.get(reverse('claude-queue-job-row', args=[job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'hx-get')
        self.assertContains(response, 'reads auth.py')

    def test_row_terminal_job_has_no_polling(self):
        self.client.login(username='testuser', password='testpass123')
        job = self._done_job()
        response = self.client.get(reverse('claude-queue-job-row', args=[job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'hx-get')
        self.assertContains(response, 'PR #42')

    def test_row_204_for_nonexistent_job(self):
        self.client.login(username='testuser', password='testpass123')
        max_id = ClaudeQueueJob.objects.aggregate(Max('id'))['id__max'] or 0
        response = self.client.get(reverse('claude-queue-job-row', args=[max_id + 1]))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b'')

    # ---- detail + live partial ----------------------------------------

    def test_detail_running_shows_current_step(self):
        self.client.login(username='testuser', password='testpass123')
        job = self._running_job()
        response = self.client.get(reverse('claude-queue-job-detail', args=[job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'reads auth.py')
        self.assertContains(response, 'hx-get')  # live block polls while running

    def test_detail_done_shows_pr_and_cost(self):
        self.client.login(username='testuser', password='testpass123')
        job = self._done_job()
        response = self.client.get(reverse('claude-queue-job-detail', args=[job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PR #42')
        self.assertContains(response, '4231')  # cost digits (locale-independent)
        self.assertContains(response, '12')  # num_turns
        self.assertNotContains(response, 'hx-get')  # polling stops when done

    def test_detail_failed_shows_error(self):
        self.client.login(username='testuser', password='testpass123')
        job = self._failed_job()
        response = self.client.get(reverse('claude-queue-job-detail', args=[job.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'boom: something went wrong')
        self.assertContains(response, 'failed')

    def test_detail_404_for_nonexistent_job(self):
        self.client.login(username='testuser', password='testpass123')
        max_id = ClaudeQueueJob.objects.aggregate(Max('id'))['id__max'] or 0
        response = self.client.get(reverse('claude-queue-job-detail', args=[max_id + 1]))
        self.assertEqual(response.status_code, 404)

    def test_live_204_for_nonexistent_job(self):
        self.client.login(username='testuser', password='testpass123')
        max_id = ClaudeQueueJob.objects.aggregate(Max('id'))['id__max'] or 0
        response = self.client.get(reverse('claude-queue-job-live', args=[max_id + 1]))
        self.assertEqual(response.status_code, 204)

    # ---- long-running warning ------------------------------------------

    def _job_started(self, seconds_ago, status=ClaudeQueueJobStatus.RUNNING):
        return ClaudeQueueJob.objects.create(
            item=self.item,
            project=self.project,
            status=status,
            started_at=timezone.now() - timezone.timedelta(seconds=seconds_ago),
        )

    def test_is_long_running_false_below_threshold(self):
        job = self._job_started(CLAUDE_QUEUE_JOB_LONG_RUNNING_SECONDS - 60)
        self.assertFalse(job.is_long_running)

    def test_is_long_running_true_above_threshold(self):
        job = self._job_started(CLAUDE_QUEUE_JOB_LONG_RUNNING_SECONDS + 60)
        self.assertTrue(job.is_long_running)

    def test_is_long_running_false_when_not_running(self):
        for status in (ClaudeQueueJobStatus.DONE, ClaudeQueueJobStatus.FAILED, ClaudeQueueJobStatus.CANCELLED):
            job = self._job_started(CLAUDE_QUEUE_JOB_LONG_RUNNING_SECONDS + 60, status=status)
            self.assertFalse(job.is_long_running)

    def test_row_no_warning_below_threshold(self):
        self.client.login(username='testuser', password='testpass123')
        job = self._job_started(CLAUDE_QUEUE_JOB_LONG_RUNNING_SECONDS - 60)
        response = self.client.get(reverse('claude-queue-job-row', args=[job.id]))
        self.assertNotContains(response, 'Dauert länger als gewöhnlich')

    def test_row_shows_warning_above_threshold(self):
        self.client.login(username='testuser', password='testpass123')
        job = self._job_started(CLAUDE_QUEUE_JOB_LONG_RUNNING_SECONDS + 60)
        response = self.client.get(reverse('claude-queue-job-row', args=[job.id]))
        self.assertContains(response, 'Dauert länger als gewöhnlich')

    def test_done_job_never_shows_long_running_warning(self):
        self.client.login(username='testuser', password='testpass123')
        job = self._job_started(
            CLAUDE_QUEUE_JOB_LONG_RUNNING_SECONDS + 3600,
            status=ClaudeQueueJobStatus.DONE,
        )
        response = self.client.get(reverse('claude-queue-job-row', args=[job.id]))
        self.assertNotContains(response, 'Dauert länger als gewöhnlich')

    def test_detail_shows_long_running_warning(self):
        self.client.login(username='testuser', password='testpass123')
        job = self._job_started(CLAUDE_QUEUE_JOB_LONG_RUNNING_SECONDS + 60)
        response = self.client.get(reverse('claude-queue-job-detail', args=[job.id]))
        self.assertContains(response, 'Dauert länger als gewöhnlich')
