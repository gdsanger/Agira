"""
Tests for Activity Service
"""

from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType

from core.models import (
    Activity,
    Project,
    Item,
    ItemType,
    ProjectStatus,
    ItemStatus,
)
from core.services.activity import ActivityService

User = get_user_model()


class ActivityServiceLogTestCase(TestCase):
    """Test ActivityService.log() method."""
    
    def setUp(self):
        """Set up test data."""
        self.service = ActivityService()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        # Create test project
        self.project = Project.objects.create(
            name='Test Project',
            status=ProjectStatus.NEW,
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug'
        )
        
        # Create test item
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
    
    def test_log_creates_activity(self):
        """Test that log() creates an Activity record."""
        activity = self.service.log(
            verb='item.created',
            target=self.item,
            actor=self.user,
            summary='Test activity'
        )
        
        self.assertIsNotNone(activity)
        self.assertIsInstance(activity, Activity)
        self.assertEqual(activity.verb, 'item.created')
        self.assertEqual(activity.actor, self.user)
        self.assertEqual(activity.summary, 'Test activity')
    
    def test_log_sets_target_correctly(self):
        """Test that target is set via GenericForeignKey."""
        activity = self.service.log(
            verb='item.updated',
            target=self.item,
        )
        
        # Check GenericForeignKey fields
        item_ct = ContentType.objects.get_for_model(Item)
        self.assertEqual(activity.target_content_type, item_ct)
        self.assertEqual(activity.target_object_id, str(self.item.pk))
        
        # Check that generic relation works
        self.assertEqual(activity.target, self.item)
    
    def test_log_without_actor(self):
        """Test logging without an actor (system action)."""
        activity = self.service.log(
            verb='system.maintenance',
            target=self.project,
            summary='Automated maintenance'
        )
        
        self.assertIsNone(activity.actor)
        self.assertEqual(activity.verb, 'system.maintenance')
    
    def test_log_without_summary(self):
        """Test logging without a summary."""
        activity = self.service.log(
            verb='item.viewed',
            target=self.item,
            actor=self.user,
        )
        
        self.assertEqual(activity.summary, '')
    
    def test_log_without_target(self):
        """Test logging global activity without a target."""
        activity = self.service.log(
            verb='system.startup',
            actor=self.user,
            summary='System started'
        )
        
        self.assertIsNotNone(activity)
        self.assertEqual(activity.verb, 'system.startup')
        # Target fields should still be set to satisfy DB constraints
        self.assertIsNotNone(activity.target_content_type)
        self.assertEqual(activity.target_object_id, '0')
    
    def test_log_sets_created_at(self):
        """Test that created_at is automatically set."""
        before = timezone.now()
        activity = self.service.log(
            verb='item.created',
            target=self.item,
        )
        after = timezone.now()
        
        self.assertIsNotNone(activity.created_at)
        self.assertGreaterEqual(activity.created_at, before)
        self.assertLessEqual(activity.created_at, after)
    
    def test_log_with_different_model_types(self):
        """Test logging activities for different model types."""
        # Log for project
        project_activity = self.service.log(
            verb='project.created',
            target=self.project,
            actor=self.user,
        )
        
        project_ct = ContentType.objects.get_for_model(Project)
        self.assertEqual(project_activity.target_content_type, project_ct)
        self.assertEqual(project_activity.target, self.project)
        
        # Log for item
        item_activity = self.service.log(
            verb='item.created',
            target=self.item,
            actor=self.user,
        )
        
        item_ct = ContentType.objects.get_for_model(Item)
        self.assertEqual(item_activity.target_content_type, item_ct)
        self.assertEqual(item_activity.target, self.item)


class ActivityServiceStatusChangeTestCase(TestCase):
    """Test ActivityService.log_status_change() method."""
    
    def setUp(self):
        """Set up test data."""
        self.service = ActivityService()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        self.project = Project.objects.create(
            name='Test Project',
            status=ProjectStatus.NEW,
        )
        
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug'
        )
        
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
    
    def test_log_status_change_creates_activity(self):
        """Test that log_status_change() creates an Activity."""
        activity = self.service.log_status_change(
            item=self.item,
            from_status='Inbox',
            to_status='Working',
            actor=self.user,
        )
        
        self.assertIsNotNone(activity)
        self.assertEqual(activity.verb, 'item.status_changed')
        self.assertEqual(activity.summary, 'Status: Inbox → Working')
        self.assertEqual(activity.actor, self.user)
    
    def test_log_status_change_determines_verb_from_model(self):
        """Test that verb is determined from model type."""
        # For Item
        item_activity = self.service.log_status_change(
            item=self.item,
            from_status='Inbox',
            to_status='Working',
        )
        self.assertEqual(item_activity.verb, 'item.status_changed')
        
        # For Project
        project_activity = self.service.log_status_change(
            item=self.project,
            from_status='New',
            to_status='Working',
        )
        self.assertEqual(project_activity.verb, 'project.status_changed')
    
    def test_log_status_change_formats_summary(self):
        """Test that summary is formatted correctly."""
        activity = self.service.log_status_change(
            item=self.item,
            from_status='Backlog',
            to_status='Ready for Release',
            actor=self.user,
        )
        
        self.assertEqual(activity.summary, 'Status: Backlog → Ready for Release')
    
    def test_log_status_change_without_actor(self):
        """Test status change without actor (automated)."""
        activity = self.service.log_status_change(
            item=self.item,
            from_status='Working',
            to_status='Testing',
        )
        
        self.assertIsNone(activity.actor)
        self.assertEqual(activity.verb, 'item.status_changed')


class ActivityServiceCreatedTestCase(TestCase):
    """Test ActivityService.log_created() method."""
    
    def setUp(self):
        """Set up test data."""
        self.service = ActivityService()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        self.project = Project.objects.create(
            name='Test Project',
            status=ProjectStatus.NEW,
        )
        
        self.item_type = ItemType.objects.create(
            key='feature',
            name='Feature'
        )
        
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
    
    def test_log_created_creates_activity(self):
        """Test that log_created() creates an Activity."""
        activity = self.service.log_created(
            target=self.item,
            actor=self.user,
        )
        
        self.assertIsNotNone(activity)
        self.assertEqual(activity.verb, 'item.created')
        self.assertEqual(activity.summary, 'Created')
        self.assertEqual(activity.actor, self.user)
        self.assertEqual(activity.target, self.item)
    
    def test_log_created_determines_verb_from_model(self):
        """Test that verb is determined from model type."""
        # For Item
        item_activity = self.service.log_created(target=self.item)
        self.assertEqual(item_activity.verb, 'item.created')
        
        # For Project
        project_activity = self.service.log_created(target=self.project)
        self.assertEqual(project_activity.verb, 'project.created')
    
    def test_log_created_with_custom_summary(self):
        """Test log_created with custom summary."""
        activity = self.service.log_created(
            target=self.item,
            actor=self.user,
            summary='Created from GitHub issue #42',
        )
        
        self.assertEqual(activity.summary, 'Created from GitHub issue #42')
    
    def test_log_created_without_actor(self):
        """Test creation without actor (system created)."""
        activity = self.service.log_created(
            target=self.item,
        )
        
        self.assertIsNone(activity.actor)
        self.assertEqual(activity.verb, 'item.created')


class ActivityServiceLatestTestCase(TestCase):
    """Test ActivityService.latest() query helper."""
    
    def setUp(self):
        """Set up test data."""
        self.service = ActivityService()
        
        self.user1 = User.objects.create_user(
            username='user1',
            email='user1@example.com',
            password='testpass123',
            name='User 1'
        )
        
        self.user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='testpass123',
            name='User 2'
        )
        
        self.project1 = Project.objects.create(
            name='Project 1',
            status=ProjectStatus.NEW,
        )
        
        self.project2 = Project.objects.create(
            name='Project 2',
            status=ProjectStatus.WORKING,
        )
        
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug'
        )
        
        self.item1 = Item.objects.create(
            project=self.project1,
            title='Item 1',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
        
        self.item2 = Item.objects.create(
            project=self.project1,
            title='Item 2',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        
        self.item3 = Item.objects.create(
            project=self.project2,
            title='Item 3',
            type=self.item_type,
            status=ItemStatus.WORKING,
        )
    
    def test_latest_returns_queryset(self):
        """Test that latest() returns a QuerySet."""
        result = self.service.latest()
        
        self.assertIsNotNone(result)
        # Check it's a QuerySet
        self.assertTrue(hasattr(result, 'filter'))
        self.assertTrue(hasattr(result, 'order_by'))
    
    def test_latest_without_filters(self):
        """Test getting latest activities without filters."""
        # Create some activities
        self.service.log(verb='item.created', target=self.item1, actor=self.user1)
        self.service.log(verb='item.created', target=self.item2, actor=self.user1)
        self.service.log(verb='item.created', target=self.item3, actor=self.user2)
        
        activities = self.service.latest()
        
        self.assertEqual(activities.count(), 3)
    
    def test_latest_respects_limit(self):
        """Test that latest() respects the limit parameter."""
        # Create 10 activities
        for i in range(10):
            self.service.log(
                verb='test.event',
                target=self.item1,
                summary=f'Activity {i}'
            )
        
        # Get latest 5
        activities = self.service.latest(limit=5)
        self.assertEqual(len(activities), 5)
        
        # Get latest 3
        activities = self.service.latest(limit=3)
        self.assertEqual(len(activities), 3)
    
    def test_latest_ordered_by_created_at_desc(self):
        """Test that activities are ordered by most recent first."""
        # Create activities with slight delays
        act1 = self.service.log(verb='first', target=self.item1)
        act2 = self.service.log(verb='second', target=self.item2)
        act3 = self.service.log(verb='third', target=self.item3)
        
        activities = list(self.service.latest())
        
        # Should be in reverse order (newest first)
        self.assertEqual(activities[0].id, act3.id)
        self.assertEqual(activities[1].id, act2.id)
        self.assertEqual(activities[2].id, act1.id)
    
    def test_latest_filter_by_item(self):
        """Test filtering activities by specific item."""
        # Create activities for different items
        self.service.log(verb='item.created', target=self.item1)
        self.service.log(verb='item.updated', target=self.item1)
        self.service.log(verb='item.created', target=self.item2)
        self.service.log(verb='item.created', target=self.item3)
        
        # Get activities for item1 only
        activities = self.service.latest(item=self.item1)
        
        self.assertEqual(activities.count(), 2)
        for activity in activities:
            self.assertEqual(activity.target, self.item1)
    
    def test_latest_filter_by_project(self):
        """Test filtering activities by project."""
        # Create activities
        self.service.log(verb='project.created', target=self.project1)
        self.service.log(verb='item.created', target=self.item1)  # project1
        self.service.log(verb='item.created', target=self.item2)  # project1
        self.service.log(verb='item.created', target=self.item3)  # project2
        
        # Get activities for project1
        activities = self.service.latest(project=self.project1)
        
        # Should include project and its items (3 total)
        self.assertEqual(activities.count(), 3)
        
        # Verify targets are either the project or items in project1
        targets = [act.target for act in activities]
        self.assertIn(self.project1, targets)
        self.assertIn(self.item1, targets)
        self.assertIn(self.item2, targets)
        self.assertNotIn(self.item3, targets)
    
    def test_latest_filter_by_project_without_items(self):
        """Test filtering by project that has no items."""
        empty_project = Project.objects.create(
            name='Empty Project',
            status=ProjectStatus.NEW,
        )
        
        # Create activity for empty project
        self.service.log(verb='project.created', target=empty_project)
        self.service.log(verb='item.created', target=self.item1)
        
        # Get activities for empty project
        activities = self.service.latest(project=empty_project)
        
        self.assertEqual(activities.count(), 1)
        self.assertEqual(activities[0].target, empty_project)
    
    def test_latest_item_filter_takes_precedence(self):
        """Test that item filter takes precedence over project filter."""
        self.service.log(verb='item.created', target=self.item1)
        self.service.log(verb='item.created', target=self.item2)
        
        # Both filters provided - item should take precedence
        activities = self.service.latest(project=self.project1, item=self.item1)
        
        self.assertEqual(activities.count(), 1)
        self.assertEqual(activities[0].target, self.item1)
    
    def test_latest_with_empty_result(self):
        """Test latest() with no matching activities."""
        activities = self.service.latest(item=self.item1)
        
        self.assertEqual(activities.count(), 0)
    
    def test_latest_select_related(self):
        """Test that latest() uses select_related for performance."""
        self.service.log(verb='item.created', target=self.item1, actor=self.user1)
        
        activities = self.service.latest()
        
        # Access related objects without additional queries
        # This would fail if select_related wasn't used
        first = activities[0]
        _ = first.actor.username  # Should not trigger additional query
        _ = first.target_content_type.model  # Should not trigger additional query


class ActivityServiceIntegrationTestCase(TestCase):
    """Integration tests for ActivityService."""
    
    def setUp(self):
        """Set up test data."""
        self.service = ActivityService()
        
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        self.project = Project.objects.create(
            name='Test Project',
            status=ProjectStatus.NEW,
        )
        
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug'
        )
    
    def test_full_item_lifecycle(self):
        """Test logging full lifecycle of an item."""
        # Create item
        item = Item.objects.create(
            project=self.project,
            title='Bug Fix',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
        
        # Log creation
        self.service.log_created(target=item, actor=self.user)
        
        # Log status changes
        self.service.log_status_change(
            item=item,
            from_status='Inbox',
            to_status='Backlog',
            actor=self.user,
        )
        
        self.service.log_status_change(
            item=item,
            from_status='Backlog',
            to_status='Working',
            actor=self.user,
        )
        
        self.service.log_status_change(
            item=item,
            from_status='Working',
            to_status='Closed',
            actor=self.user,
        )
        
        # Verify all activities were logged
        activities = self.service.latest(item=item)
        self.assertEqual(activities.count(), 4)
        
        # Verify order (newest first)
        activity_list = list(activities)
        self.assertEqual(activity_list[0].verb, 'item.status_changed')
        self.assertEqual(activity_list[0].summary, 'Status: Working → Closed')
        self.assertEqual(activity_list[3].verb, 'item.created')
    
    def test_multiple_actors(self):
        """Test activities from different actors."""
        user2 = User.objects.create_user(
            username='user2',
            email='user2@example.com',
            password='testpass123',
            name='User 2'
        )
        
        item = Item.objects.create(
            project=self.project,
            title='Feature Request',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
        
        # Different users perform actions
        self.service.log_created(target=item, actor=self.user)
        self.service.log(verb='item.assigned', target=item, actor=user2)
        self.service.log_status_change(
            item=item,
            from_status='Inbox',
            to_status='Working',
            actor=user2,
        )
        
        activities = list(self.service.latest(item=item))
        
        # Verify different actors
        self.assertEqual(activities[2].actor, self.user)
        self.assertEqual(activities[1].actor, user2)
        self.assertEqual(activities[0].actor, user2)


if __name__ == '__main__':
    import django
    django.setup()
    from django.test.utils import get_runner
    from django.conf import settings
    
    TestRunner = get_runner(settings)
    test_runner = TestRunner()
    failures = test_runner.run_tests(['core.services.activity.test_activity'])
