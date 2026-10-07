"""
Tests for dashboard views
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ProjectStatus, Change, ChangeStatus, AIJobsHistory,
    UserOrganisation, UserRole
)


class DashboardViewsTestCase(TestCase):
    """Test cases for dashboard views"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation"
        )
        
        # Create test user
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            name="Test User"
        )
        
        # Add user to organization
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org,
            role=UserRole.AGENT,
            is_primary=True
        )
        
        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
        self.project.clients.add(self.org)
        # Dashboard KPIs are scoped to the projects assigned to the user (#1248).
        self.project.members.add(self.user)
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key="bug",
            name="Bug"
        )
        
        # Create items with different statuses
        Item.objects.create(
            project=self.project,
            title="Inbox Item",
            type=self.item_type,
            status=ItemStatus.INBOX,
            organisation=self.org,
            requester=self.user
        )
        
        Item.objects.create(
            project=self.project,
            title="Backlog Item",
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            organisation=self.org,
            requester=self.user
        )
        
        Item.objects.create(
            project=self.project,
            title="Working Item",
            type=self.item_type,
            status=ItemStatus.WORKING,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        
        Item.objects.create(
            project=self.project,
            title="Testing Item",
            type=self.item_type,
            status=ItemStatus.TESTING,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        
        Item.objects.create(
            project=self.project,
            title="Ready Item",
            type=self.item_type,
            status=ItemStatus.READY_FOR_RELEASE,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        
        # Create a closed item within 7 days
        closed_item = Item.objects.create(
            project=self.project,
            title="Closed Item",
            type=self.item_type,
            status=ItemStatus.CLOSED,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        Item.objects.filter(pk=closed_item.pk).update(updated_at=timezone.now() - timedelta(days=2))
    
    def test_dashboard_view(self):
        """Test dashboard view loads correctly"""
        self.client.force_login(self.user)
        url = reverse('dashboard')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard')
        self.assertContains(response, 'Overview of your projects and activities')
    
    def test_dashboard_kpis(self):
        """Test dashboard KPIs are calculated correctly"""
        self.client.force_login(self.user)
        url = reverse('dashboard')
        response = self.client.get(url)
        
        # Check KPI values in context
        self.assertEqual(response.context['kpis']['inbox_count'], 1)
        self.assertEqual(response.context['kpis']['backlog_count'], 1)
        self.assertEqual(response.context['kpis']['in_progress_count'], 3)  # Working + Testing + Ready
        self.assertEqual(response.context['kpis']['closed_7d_count'], 1)
        self.assertEqual(response.context['kpis']['changes_open_count'], 0)
        self.assertEqual(response.context['kpis']['ai_jobs_24h_count'], 0)
    
    def test_dashboard_in_progress_partial(self):
        """Test in-progress items partial view"""
        self.client.force_login(self.user)
        url = reverse('dashboard-in-progress-items')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Working Item')
        self.assertContains(response, 'Testing Item')
        self.assertContains(response, 'Ready Item')
        # Should not contain inbox or backlog items
        self.assertNotContains(response, 'Inbox Item')
        self.assertNotContains(response, 'Backlog Item')
    
    def test_activity_stream_removed(self):
        """The global activity stream is gone from the dashboard."""
        from django.urls import NoReverseMatch
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))
        self.assertNotContains(response, 'Global Activity Stream')
        with self.assertRaises(NoReverseMatch):
            reverse('dashboard-activity-stream')

    def test_dashboard_section_order(self):
        """KPIs and closed chart first, new analytics, Currently Worked On last."""
        self.client.force_login(self.user)
        html = self.client.get(reverse('dashboard')).content.decode()
        positions = [html.index(marker) for marker in (
            'closedItemsChart', 'Status by Responsible', 'Status by Assigned To',
            'Status Distribution', '7-Day Trend', 'Currently Worked On',
        )]
        self.assertEqual(positions, sorted(positions))

    def test_dashboard_status_distribution(self):
        """Distribution counts open items of the user's projects only."""
        other = Project.objects.create(name="Other", status=ProjectStatus.WORKING)
        Item.objects.create(project=other, title="Hidden", type=self.item_type, status=ItemStatus.INBOX)
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))
        totals = {row['label']: row['count'] for row in response.context['status_totals']}
        self.assertEqual(totals['Inbox'], 1)
        self.assertEqual(totals['Working'], 1)
        self.assertEqual(response.context['status_total_open'], 5)
        self.assertEqual([p['name'] for p in response.context['status_projects']], ['Test Project'])
        self.assertEqual(len(response.context['trend_rows']), 7)

    def test_dashboard_person_charts(self):
        """Per-person breakdown: open items by status plus Closed of the last 7 days."""
        import json
        agent = User.objects.create(username="agent", email="agent@example.com", name="Agent A", role=UserRole.AGENT)
        Item.objects.filter(title="Working Item").update(responsible=agent)
        old_closed = Item.objects.create(
            project=self.project, title="Closed long ago", type=self.item_type,
            status=ItemStatus.CLOSED, assigned_to=self.user,
        )
        old_closed.status_changes.update(changed_at=timezone.now() - timedelta(days=30))
        self.client.force_login(self.user)
        response = self.client.get(reverse('dashboard'))

        assigned = json.loads(response.context['assigned_chart_json'])
        self.assertEqual(assigned['labels'][0], 'Test User')
        by_status = {ds['status']: ds['data'][0] for ds in assigned['datasets']}
        self.assertEqual(by_status['Working'], 1)
        self.assertEqual(by_status['Testing'], 1)
        self.assertEqual(by_status['ReadyForRelease'], 1)
        self.assertEqual(by_status['Closed'], 1)  # setUp item, not the one closed 30 days ago
        self.assertEqual(assigned['labels'][-1], 'Unassigned')

        responsible = json.loads(response.context['responsible_chart_json'])
        self.assertEqual(responsible['labels'], ['Agent A', 'No responsible'])

    def test_dashboard_closed_items_chart_data(self):
        """Test that closed items chart data is calculated correctly"""
        self.client.force_login(self.user)
        url = reverse('dashboard')
        response = self.client.get(url)
        
        # Check that the chart data is present in the context
        self.assertIn('closed_items_chart_json', response.context)
        
        # Parse the JSON data
        import json
        chart_data = json.loads(response.context['closed_items_chart_json'])
        
        # Should have exactly 7 data points
        self.assertEqual(len(chart_data), 7)
        
        # Each data point should have date, date_display, and count
        for data_point in chart_data:
            self.assertIn('date', data_point)
            self.assertIn('date_display', data_point)
            self.assertIn('count', data_point)
            self.assertIsInstance(data_point['count'], int)
        
        # Should have at least one closed item in the data (the one we created in setUp)
        total_closed = sum(point['count'] for point in chart_data)
        self.assertEqual(total_closed, 1)
    
    def test_dashboard_closed_items_chart_empty(self):
        """Test that chart works correctly when no items are closed"""
        # Delete the closed item created in setUp
        Item.objects.filter(status=ItemStatus.CLOSED).delete()
        
        self.client.force_login(self.user)
        url = reverse('dashboard')
        response = self.client.get(url)
        
        # Parse the JSON data
        import json
        chart_data = json.loads(response.context['closed_items_chart_json'])
        
        # Should still have exactly 7 data points
        self.assertEqual(len(chart_data), 7)
        
        # All counts should be 0
        total_closed = sum(point['count'] for point in chart_data)
        self.assertEqual(total_closed, 0)
    
    def test_dashboard_closed_items_chart_multiple_days(self):
        """Test that chart aggregates items across multiple days correctly"""
        from datetime import timedelta
        
        # Create items closed on different days
        today = timezone.now()
        
        # Item closed today
        item_today = Item.objects.create(
            project=self.project,
            title="Closed Today",
            type=self.item_type,
            status=ItemStatus.CLOSED,
            organisation=self.org,
            requester=self.user
        )
        
        # Item closed 3 days ago
        item_3_days = Item.objects.create(
            project=self.project,
            title="Closed 3 Days Ago",
            type=self.item_type,
            status=ItemStatus.CLOSED,
            organisation=self.org,
            requester=self.user
        )
        Item.objects.filter(pk=item_3_days.pk).update(updated_at=today - timedelta(days=3))
        
        # Item closed 5 days ago
        item_5_days = Item.objects.create(
            project=self.project,
            title="Closed 5 Days Ago",
            type=self.item_type,
            status=ItemStatus.CLOSED,
            organisation=self.org,
            requester=self.user
        )
        Item.objects.filter(pk=item_5_days.pk).update(updated_at=today - timedelta(days=5))
        
        self.client.force_login(self.user)
        url = reverse('dashboard')
        response = self.client.get(url)
        
        # Parse the JSON data
        import json
        chart_data = json.loads(response.context['closed_items_chart_json'])
        
        # Should have exactly 7 data points
        self.assertEqual(len(chart_data), 7)
        
        # Should have 4 closed items total (including the one from setUp)
        total_closed = sum(point['count'] for point in chart_data)
        self.assertEqual(total_closed, 4)
