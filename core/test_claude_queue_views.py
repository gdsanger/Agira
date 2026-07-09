"""
Tests for the Claude Queue visibility views (list, detail, and HTMX polling
partials).
"""
import json
import re
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.db.models import Max
from django.template.defaultfilters import floatformat
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

    # ---- mini dashboard --------------------------------------------------

    def _job_with_data(self, cost=None, turns=None, duration_seconds=None, created_at=None):
        started = timezone.now() - timezone.timedelta(seconds=duration_seconds) if duration_seconds is not None else None
        finished = timezone.now() if duration_seconds is not None else None
        job = ClaudeQueueJob.objects.create(
            item=self.item,
            project=self.project,
            status=ClaudeQueueJobStatus.DONE,
            total_cost_usd=cost,
            num_turns=turns,
            started_at=started,
            finished_at=finished,
        )
        if created_at is not None:
            ClaudeQueueJob.objects.filter(pk=job.pk).update(created_at=created_at)
        return job

    def test_dashboard_empty_queue_renders_without_errors(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['queue_total_jobs'], 0)
        self.assertIsNone(response.context['queue_avg_cost'])
        self.assertIsNone(response.context['queue_avg_turns'])
        self.assertIsNone(response.context['queue_avg_duration_display'])
        self.assertContains(response, 'No queue jobs found.')

    def test_dashboard_kpis_with_complete_data(self):
        self.client.login(username='testuser', password='testpass123')
        self._job_with_data(cost=Decimal('1.00'), turns=10, duration_seconds=60)
        self._job_with_data(cost=Decimal('3.00'), turns=20, duration_seconds=120)
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        # Assert on context values, not rendered HTML — the KPI numbers go
        # through the locale-aware floatformat filter (LANGUAGE_CODE=de-DE
        # renders a comma decimal separator), so string-matching the
        # rendered markup would be locale-fragile.
        self.assertEqual(response.context['queue_total_jobs'], 2)
        self.assertEqual(round(response.context['queue_avg_cost'], 4), Decimal('2.0000'))
        self.assertEqual(response.context['queue_avg_turns'], 15.0)
        self.assertEqual(response.context['queue_avg_duration_display'], '1m 30s')

    def test_dashboard_kpis_ignore_missing_values(self):
        self.client.login(username='testuser', password='testpass123')
        # One job with all values, one job missing cost/turns/duration entirely.
        self._job_with_data(cost=Decimal('4.00'), turns=8, duration_seconds=60)
        ClaudeQueueJob.objects.create(
            item=self.item, project=self.project, status=ClaudeQueueJobStatus.RUNNING,
        )
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        # Averages should be based on the single job with data, not diluted by the empty one.
        self.assertEqual(response.context['queue_total_jobs'], 2)
        self.assertEqual(round(response.context['queue_avg_cost'], 4), Decimal('4.0000'))
        self.assertEqual(response.context['queue_avg_turns'], 8.0)
        self.assertEqual(response.context['queue_avg_duration_display'], '1m 0s')

    def test_dashboard_chart_has_exactly_seven_days_using_created_at(self):
        self.client.login(username='testuser', password='testpass123')
        self._job_with_data(cost=Decimal('2.50'), created_at=timezone.now())
        old_job = self._job_with_data(cost=Decimal('99.00'))
        ClaudeQueueJob.objects.filter(pk=old_job.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=30)
        )
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        match = re.search(r'\{"labels".*?\]\}', response.content.decode(), re.DOTALL)
        self.assertIsNotNone(match)
        chart_data = json.loads(match.group(0))
        self.assertEqual(len(chart_data['labels']), 7)
        self.assertEqual(len(chart_data['jobs']), 7)
        self.assertEqual(len(chart_data['costs']), 7)
        # Old job (30 days ago) must not be counted in the 7-day window.
        self.assertEqual(sum(chart_data['jobs']), 1)
        self.assertEqual(sum(chart_data['costs']), 2.5)
        # Today (last entry) should carry the one recent job.
        self.assertEqual(chart_data['jobs'][-1], 1)

    def test_dashboard_days_without_jobs_are_zero(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        match = re.search(r'\{"labels".*?\]\}', response.content.decode(), re.DOTALL)
        chart_data = json.loads(match.group(0))
        self.assertEqual(chart_data['jobs'], [0, 0, 0, 0, 0, 0, 0])
        self.assertEqual(chart_data['costs'], [0, 0, 0, 0, 0, 0, 0])

    def test_dashboard_cost_kpi_rendered_with_two_decimals(self):
        self.client.login(username='testuser', password='testpass123')
        self._job_with_data(cost=Decimal('1.00'), turns=10, duration_seconds=60)
        self._job_with_data(cost=Decimal('2.2345'), turns=20, duration_seconds=120)
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        expected_cost = floatformat(response.context['queue_avg_cost'], 2)
        self.assertContains(response, f'US${expected_cost}')
        # Guard against a regression back to more decimal places.
        self.assertNotContains(response, f'US${floatformat(response.context["queue_avg_cost"], 4)}')

    def test_dashboard_turns_kpi_rendered_without_decimals(self):
        self.client.login(username='testuser', password='testpass123')
        self._job_with_data(cost=Decimal('1.00'), turns=9, duration_seconds=60)
        self._job_with_data(cost=Decimal('1.00'), turns=10, duration_seconds=60)
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['queue_avg_turns'], 9.5)
        expected_turns = floatformat(response.context['queue_avg_turns'], 0)
        self.assertContains(response, expected_turns)
        self.assertNotIn(',', expected_turns)
        self.assertNotIn('.', expected_turns)

    def test_dashboard_kpis_render_without_errors_when_all_values_missing(self):
        self.client.login(username='testuser', password='testpass123')
        ClaudeQueueJob.objects.create(
            item=self.item, project=self.project, status=ClaudeQueueJobStatus.RUNNING,
        )
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '–')  # the "–" placeholder for empty KPIs

    def test_dashboard_chart_canvas_is_placed_below_kpi_cards(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        kpi_row_index = content.index('Ø Turns')
        chart_index = content.index('id="queueChart"')
        self.assertGreater(chart_index, kpi_row_index)

    def test_dashboard_chart_container_has_increased_height(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'height: 320px;')

    # ---- pagination ------------------------------------------------------

    def test_pagination_up_to_20_jobs_is_a_single_page(self):
        self.client.login(username='testuser', password='testpass123')
        for _ in range(20):
            self._running_job()
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['page_obj'].object_list), 20)
        self.assertFalse(response.context['page_obj'].has_other_pages())

    def test_pagination_more_than_20_jobs_spans_pages(self):
        self.client.login(username='testuser', password='testpass123')
        for _ in range(25):
            self._running_job()
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        page_obj = response.context['page_obj']
        self.assertEqual(len(page_obj.object_list), 20)
        self.assertEqual(page_obj.paginator.num_pages, 2)

        response_page_2 = self.client.get(reverse('claude-queue-jobs'), {'page': 2})
        self.assertEqual(response_page_2.status_code, 200)
        self.assertEqual(len(response_page_2.context['page_obj'].object_list), 5)

    def test_pagination_zero_jobs_renders_without_errors(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['page_obj'].object_list), [])

    def test_pagination_compatible_with_status_filter(self):
        self.client.login(username='testuser', password='testpass123')
        for _ in range(22):
            self._running_job()
        self._done_job()
        response = self.client.get(
            reverse('claude-queue-jobs'), {'status': ClaudeQueueJobStatus.DONE}
        )
        page_obj = response.context['page_obj']
        self.assertEqual(page_obj.paginator.count, 1)
        self.assertContains(response, 'PR #42')
