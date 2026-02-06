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
        closed_item.updated_at = timezone.now() - timedelta(days=2)
        closed_item.save()
    
    def test_dashboard_view(self):
        """Test dashboard view loads correctly"""
        url = reverse('dashboard')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dashboard')
        self.assertContains(response, 'Overview of your projects and activities')
    
    def test_dashboard_kpis(self):
        """Test dashboard KPIs are calculated correctly"""
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
        url = reverse('dashboard-in-progress-items')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Working Item')
        self.assertContains(response, 'Testing Item')
        self.assertContains(response, 'Ready Item')
        # Should not contain inbox or backlog items
        self.assertNotContains(response, 'Inbox Item')
        self.assertNotContains(response, 'Backlog Item')
    
    def test_dashboard_activity_stream_partial(self):
        """Test activity stream partial view"""
        url = reverse('dashboard-activity-stream')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        # Check for activity stream structure
        self.assertContains(response, 'activity-stream')
    
    def test_dashboard_activity_stream_filter_items(self):
        """Test activity stream with items filter"""
        url = reverse('dashboard-activity-stream') + '?filter=items'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'activity-stream')
    
    def test_dashboard_activity_stream_pagination(self):
        """Test activity stream pagination"""
        url = reverse('dashboard-activity-stream') + '?offset=10'
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
    
    def test_dashboard_closed_items_chart_data(self):
        """Test that closed items chart data is calculated correctly"""
        self.client.force_login(self.user)
        url = reverse('dashboard')
        response = self.client.get(url)
        
        # Check that the chart data is present in the context
        self.assertIn('closed_items_chart', response.context)
        self.assertIn('closed_items_chart_json', response.context)
        
        chart_data = response.context['closed_items_chart']
        
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
        
        chart_data = response.context['closed_items_chart']
        
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
        item_3_days.updated_at = today - timedelta(days=3)
        item_3_days.save()
        
        # Item closed 5 days ago
        item_5_days = Item.objects.create(
            project=self.project,
            title="Closed 5 Days Ago",
            type=self.item_type,
            status=ItemStatus.CLOSED,
            organisation=self.org,
            requester=self.user
        )
        item_5_days.updated_at = today - timedelta(days=5)
        item_5_days.save()
        
        self.client.force_login(self.user)
        url = reverse('dashboard')
        response = self.client.get(url)
        
        chart_data = response.context['closed_items_chart']
        
        # Should have exactly 7 data points
        self.assertEqual(len(chart_data), 7)
        
        # Should have 4 closed items total (including the one from setUp)
        total_closed = sum(point['count'] for point in chart_data)
        self.assertEqual(total_closed, 4)
