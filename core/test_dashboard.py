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
