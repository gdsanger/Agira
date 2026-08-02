"""
Tests for the Project Detail "Kosten" tab: Claude-Queue-Kosten je Monat/Jahr (#1003).
"""
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Item, Project, ItemStatus, ItemType, User,
    ClaudeQueueJob, ClaudeQueueJobModel,
)


class ProjectCostsTabTest(TestCase):
    """Test the project-scoped, month/year-grouped Claude Queue cost tab."""

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
        self.client.login(username='testuser', password='testpass123')

        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug', is_active=True)
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.WORKING,
        )

    def _job(self, cost, created_at=None, item=None):
        job = ClaudeQueueJob.objects.create(
            item=item or self.item,
            project=self.project,
            model=ClaudeQueueJobModel.SONNET,
            total_cost_usd=cost,
        )
        if created_at is not None:
            ClaudeQueueJob.objects.filter(pk=job.pk).update(created_at=created_at)
        return job

    def test_no_jobs_shows_empty_state(self):
        response = self.client.get(reverse('project-costs-tab', args=[self.project.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cost_by_month'], [])
        self.assertEqual(response.context['total_cost'], Decimal('0'))
        self.assertContains(response, 'noch keine Claude-Queue-Kosten')

    def test_jobs_grouped_by_month_and_sorted_chronologically(self):
        self._job(Decimal('1.000000'), created_at=timezone.datetime(2026, 7, 15, tzinfo=timezone.get_current_timezone()))
        self._job(Decimal('2.000000'), created_at=timezone.datetime(2026, 7, 20, tzinfo=timezone.get_current_timezone()))
        self._job(Decimal('4.000000'), created_at=timezone.datetime(2026, 8, 1, tzinfo=timezone.get_current_timezone()))

        response = self.client.get(reverse('project-costs-tab', args=[self.project.id]))

        self.assertEqual(response.status_code, 200)
        rows = response.context['cost_by_month']
        self.assertEqual([r['label'] for r in rows], ['07/2026', '08/2026'])
        self.assertEqual(rows[0]['total'], Decimal('3.000000'))
        self.assertEqual(rows[0]['count'], 2)
        self.assertEqual(rows[1]['total'], Decimal('4.000000'))
        self.assertEqual(response.context['total_cost'], Decimal('7.000000'))
        self.assertEqual(response.context['total_jobs'], 3)

    def test_jobs_without_cost_do_not_break_the_sum(self):
        self._job(Decimal('1.500000'), created_at=timezone.datetime(2026, 7, 15, tzinfo=timezone.get_current_timezone()))
        self._job(None, created_at=timezone.datetime(2026, 7, 20, tzinfo=timezone.get_current_timezone()))

        response = self.client.get(reverse('project-costs-tab', args=[self.project.id]))

        self.assertEqual(response.status_code, 200)
        rows = response.context['cost_by_month']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['total'], Decimal('1.500000'))
        self.assertEqual(rows[0]['count'], 2)

    def test_costs_from_other_projects_are_not_included(self):
        other_project = Project.objects.create(name='Other Project')
        other_item = Item.objects.create(
            project=other_project,
            title='Other Item',
            type=self.item_type,
            status=ItemStatus.WORKING,
        )
        self._job(Decimal('9.999999'), item=other_item)

        response = self.client.get(reverse('project-costs-tab', args=[self.project.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['cost_by_month'], [])
        self.assertEqual(response.context['total_cost'], Decimal('0'))

    def test_project_detail_page_includes_costs_tab(self):
        response = self.client.get(reverse('project-detail', args=[self.project.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kosten')
        self.assertContains(response, reverse('project-costs-tab', args=[self.project.id]))
