"""
Tests for AI Job Statistics view and aggregations.
"""
from decimal import Decimal
from datetime import timedelta

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AIJobsHistory, AIProvider, AIModel, AIProviderType, AIJobStatus,
    User,
)


def _make_provider():
    return AIProvider.objects.create(
        name='Test Provider',
        provider_type=AIProviderType.OPENAI,
        api_key='test-key',
        active=True,
    )


def _make_model(provider):
    return AIModel.objects.create(
        provider=provider,
        name='gpt-4',
        model_id='gpt-4',
        active=True,
    )


class AIJobStatisticsAggregationTests(TestCase):
    """Test DB-side aggregations for AI Job Statistics."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='statsuser',
            email='stats@example.com',
            password='pass',
        )
        self.provider = _make_provider()
        self.model = _make_model(self.provider)
        self.client = Client()
        self.client.force_login(self.user)

        now = timezone.now()
        today = timezone.localdate()

        # Job today – timestamp set via update() since field is auto_now_add
        self._job_today = AIJobsHistory.objects.create(
            agent='agent.test',
            user=self.user,
            provider=self.provider,
            model=self.model,
            status=AIJobStatus.COMPLETED,
            costs=Decimal('0.001000'),
            duration_ms=200,
        )

        # Job from 3 days ago (within last 7 days)
        self._job_3d = AIJobsHistory.objects.create(
            agent='agent.test',
            user=self.user,
            provider=self.provider,
            model=self.model,
            status=AIJobStatus.ERROR,
            costs=Decimal('0.002000'),
            duration_ms=400,
        )
        AIJobsHistory.objects.filter(pk=self._job_3d.pk).update(
            timestamp=now - timedelta(days=3)
        )

        # Job from 10 days ago (outside last 7 days)
        self._job_old = AIJobsHistory.objects.create(
            agent='agent.old',
            user=self.user,
            provider=self.provider,
            model=self.model,
            status=AIJobStatus.ERROR,
            costs=Decimal('0.005000'),
            duration_ms=500,
        )
        AIJobsHistory.objects.filter(pk=self._job_old.pk).update(
            timestamp=now - timedelta(days=10)
        )

    # ------------------------------------------------------------------
    # KPI: costs per time period
    # ------------------------------------------------------------------

    def test_costs_today(self):
        """Costs today should only include jobs timestamped today."""
        from django.db.models import Sum
        from datetime import datetime, time
        today = timezone.localdate()
        start_of_day = timezone.make_aware(datetime.combine(today, time.min))
        result = AIJobsHistory.objects.filter(
            timestamp__gte=start_of_day
        ).aggregate(total=Sum('costs'))['total'] or Decimal('0')
        self.assertEqual(result, Decimal('0.001000'))

    def test_costs_current_week(self):
        """Costs current week should include all jobs from Monday of this week."""
        from django.db.models import Sum
        from datetime import datetime, time
        today = timezone.localdate()
        start_of_week = today - timedelta(days=today.weekday())
        start_of_week_dt = timezone.make_aware(datetime.combine(start_of_week, time.min))
        result = AIJobsHistory.objects.filter(
            timestamp__gte=start_of_week_dt
        ).aggregate(total=Sum('costs'))['total'] or Decimal('0')
        # Only the job from today should be in the current week
        # (3 days ago might or might not be in current week depending on day of week)
        self.assertGreaterEqual(result, Decimal('0.001000'))

    def test_costs_current_month(self):
        """Costs current month should include jobs from 1st of this month."""
        from django.db.models import Sum
        from datetime import datetime, time
        today = timezone.localdate()
        start_of_month = today.replace(day=1)
        start_of_month_dt = timezone.make_aware(datetime.combine(start_of_month, time.min))
        result = AIJobsHistory.objects.filter(
            timestamp__gte=start_of_month_dt
        ).aggregate(total=Sum('costs'))['total'] or Decimal('0')
        self.assertGreaterEqual(result, Decimal('0.001000'))

    # ------------------------------------------------------------------
    # KPI: errors last 7 days
    # ------------------------------------------------------------------

    def test_errors_7d_excludes_older_jobs(self):
        """Error count for last 7 days must not include jobs older than 7 days."""
        from datetime import datetime, time
        today = timezone.localdate()
        days_ago_7 = today - timedelta(days=6)
        start_7days = timezone.make_aware(datetime.combine(days_ago_7, time.min))
        count = AIJobsHistory.objects.filter(
            timestamp__gte=start_7days,
            status=AIJobStatus.ERROR,
        ).count()
        # Only _job_3d is an Error within 7 days; _job_old is outside
        self.assertEqual(count, 1)

    def test_errors_7d_counts_error_status_only(self):
        """Error count must only include jobs with ERROR status."""
        from datetime import datetime, time
        today = timezone.localdate()
        days_ago_7 = today - timedelta(days=6)
        start_7days = timezone.make_aware(datetime.combine(days_ago_7, time.min))
        count = AIJobsHistory.objects.filter(
            timestamp__gte=start_7days,
            status=AIJobStatus.COMPLETED,
        ).count()
        self.assertEqual(count, 1)  # only _job_today is Completed within 7 days

    # ------------------------------------------------------------------
    # Table aggregations
    # ------------------------------------------------------------------

    def test_by_agent_aggregation(self):
        """Per-agent aggregation returns correct request count and costs."""
        from django.db.models import Sum, Count
        rows = list(
            AIJobsHistory.objects.values('agent')
            .annotate(requests=Count('id'), total_costs=Sum('costs'))
            .order_by('agent')
        )
        agents = {r['agent']: r for r in rows}
        self.assertIn('agent.test', agents)
        self.assertEqual(agents['agent.test']['requests'], 2)
        self.assertAlmostEqual(float(agents['agent.test']['total_costs']), 0.003, places=4)

    def test_by_model_aggregation(self):
        """Per-model aggregation returns correct request count."""
        from django.db.models import Sum, Count
        rows = list(
            AIJobsHistory.objects.filter(model__isnull=False)
            .values('model__name')
            .annotate(requests=Count('id'), total_costs=Sum('costs'))
            .order_by('model__name')
        )
        self.assertTrue(len(rows) > 0)
        self.assertEqual(rows[0]['model__name'], 'gpt-4')

    def test_by_user_aggregation(self):
        """Per-user aggregation includes username."""
        from django.db.models import Sum, Count
        rows = list(
            AIJobsHistory.objects.filter(user__isnull=False)
            .values('user__username')
            .annotate(requests=Count('id'), total_costs=Sum('costs'))
        )
        usernames = [r['user__username'] for r in rows]
        self.assertIn('statsuser', usernames)

    # ------------------------------------------------------------------
    # Timeseries
    # ------------------------------------------------------------------

    def test_requests_per_day_timeseries(self):
        """Requests timeseries covers last 7 days with correct daily counts."""
        from django.db.models import Count
        from django.db.models.functions import TruncDate
        from datetime import datetime, time
        today = timezone.localdate()
        days_ago_7 = today - timedelta(days=6)
        start_7days = timezone.make_aware(datetime.combine(days_ago_7, time.min))
        qs = (
            AIJobsHistory.objects.filter(timestamp__gte=start_7days)
            .annotate(day=TruncDate('timestamp'))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )
        result = {item['day']: item['count'] for item in qs}
        # Today must have count = 1
        self.assertEqual(result.get(today, 0), 1)

    def test_avg_duration_per_day_per_agent(self):
        """Avg duration timeseries groups correctly by day and agent."""
        from django.db.models import Avg
        from django.db.models.functions import TruncDate
        from datetime import datetime, time
        today = timezone.localdate()
        days_ago_7 = today - timedelta(days=6)
        start_7days = timezone.make_aware(datetime.combine(days_ago_7, time.min))
        qs = list(
            AIJobsHistory.objects.filter(
                timestamp__gte=start_7days,
                duration_ms__isnull=False,
            )
            .annotate(day=TruncDate('timestamp'))
            .values('day', 'agent')
            .annotate(avg_duration=Avg('duration_ms'))
            .order_by('day', 'agent')
        )
        # Today's job for agent.test has duration_ms=200
        today_rows = [r for r in qs if r['day'] == today and r['agent'] == 'agent.test']
        self.assertEqual(len(today_rows), 1)
        self.assertAlmostEqual(float(today_rows[0]['avg_duration']), 200.0, places=1)


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class AIJobStatisticsViewTests(TestCase):
    """Test the ai_job_statistics view access and response."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='viewuser',
            email='view@example.com',
            password='pass',
        )

    def test_unauthenticated_redirects(self):
        """Unauthenticated requests should be redirected to login."""
        url = reverse('ai-job-statistics')
        response = self.client.get(url)
        self.assertIn(response.status_code, [301, 302])
        self.assertIn('/login', response['Location'] if 'Location' in response else response.url)

    def test_authenticated_returns_200(self):
        """Authenticated users get a 200 response."""
        self.client.force_login(self.user)
        url = reverse('ai-job-statistics')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_context_keys_present(self):
        """View context must contain all required keys."""
        self.client.force_login(self.user)
        url = reverse('ai-job-statistics')
        response = self.client.get(url)
        for key in (
            'costs_today', 'costs_week', 'costs_month', 'errors_7d',
            'by_agent', 'by_model', 'by_user',
            'requests_chart_json', 'duration_chart_json',
        ):
            self.assertIn(key, response.context, f"Missing context key: {key}")

    def test_context_empty_without_jobs(self):
        """With no AI jobs, costs should be zero and error count should be 0."""
        self.client.force_login(self.user)
        url = reverse('ai-job-statistics')
        response = self.client.get(url)
        self.assertEqual(response.context['costs_today'], Decimal('0'))
        self.assertEqual(response.context['costs_week'], Decimal('0'))
        self.assertEqual(response.context['costs_month'], Decimal('0'))
        self.assertEqual(response.context['errors_7d'], 0)
