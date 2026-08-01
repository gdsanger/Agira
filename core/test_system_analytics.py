"""
Tests for the system analytics ("Agira über Agira") view.
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Item, Project, ItemStatus, ItemType, User, Release,
    ClaudeQueueJob, ClaudeQueueJobStatus, ClaudeQueueJobModel,
    ExternalIssueMapping, ExternalIssueKind,
)
from core.services.activity import ActivityService


class SystemAnalyticsViewTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com',
        )
        self.user.active = True
        self.user.save()

        self.project = Project.objects.create(name='Test Project', description='desc')
        self.item_type = ItemType.objects.create(key='bug', name='Bug', description='Bug type')

        self.item = Item.objects.create(
            title='Closed item with a job',
            description='desc',
            project=self.project,
            type=self.item_type,
            status=ItemStatus.CLOSED,
        )
        ActivityService().log_status_change(
            item=self.item, from_status=ItemStatus.TESTING, to_status=ItemStatus.CLOSED,
        )

        job = ClaudeQueueJob.objects.create(
            item=self.item,
            project=self.project,
            status=ClaudeQueueJobStatus.QUEUED,
            model=ClaudeQueueJobModel.SONNET,
        )
        job.transition_to(ClaudeQueueJobStatus.RUNNING)
        job.transition_to(ClaudeQueueJobStatus.DONE)
        job.total_cost_usd = Decimal('1.234500')
        job.num_turns = 12
        job.save()

        ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=123456,
            number=1,
            kind=ExternalIssueKind.PR,
            state='closed',
            html_url='https://example.com/pr/1',
            merged_at=timezone.now(),
        )

        self.open_item = Item.objects.create(
            title='Still open item',
            description='desc',
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
        )

    def test_requires_authentication(self):
        response = self.client.get(reverse('system-analytics'))
        self.assertEqual(response.status_code, 302)

    def test_renders_for_authenticated_user(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('system-analytics'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'system_analytics.html')

    def test_kpis_reflect_seeded_data(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('system-analytics'))

        self.assertEqual(response.context['total_items'], 2)
        self.assertEqual(response.context['closed_items_count'], 1)
        self.assertEqual(response.context['open_items_count'], 1)
        self.assertEqual(response.context['cycle_time_sample_size'], 1)
        self.assertEqual(response.context['lead_time_sample_size'], 1)
        self.assertAlmostEqual(response.context['lead_time_coverage_pct'], 50.0)
        self.assertEqual(response.context['items_with_jobs_count'], 1)
        self.assertEqual(response.context['total_jobs'], 1)
        self.assertEqual(response.context['jobs_done_ok'], 1)
        self.assertEqual(response.context['total_cost_all_time'], Decimal('1.234500'))

    def test_milestone_item_shown_when_present(self):
        # Backfill items up to id 1000 so the milestone item can be looked up by pk.
        Item.objects.filter(pk=1000).delete()
        milestone_item = Item.objects.create(
            id=1000,
            title='The 1000th item',
            description='desc',
            project=self.project,
            type=self.item_type,
            status=ItemStatus.CLOSED,
        )

        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('system-analytics'))

        self.assertTrue(response.context['milestone_reached'])
        self.assertEqual(response.context['milestone_item'], milestone_item)

    def test_top_cost_items_excludes_items_without_cost(self):
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('system-analytics'))

        top_cost_items = response.context['top_cost_items']
        self.assertEqual(len(top_cost_items), 1)
        self.assertEqual(top_cost_items[0].id, self.item.id)
