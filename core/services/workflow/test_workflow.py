"""
Tests for Item Workflow Guard
"""

from django.test import TestCase
from django.core.exceptions import ValidationError

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ProjectStatus
)
from core.services.workflow import ItemWorkflowGuard
from core.services.activity import ActivityService


class ItemWorkflowGuardTestCase(TestCase):
    """Test cases for ItemWorkflowGuard"""
    
    def setUp(self):
        """Set up test data"""
        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation"
        )
        
        # Create test user
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com"
        )
        
        # Create project
        self.project = Project.objects.create(
            name="Test Project",
            status=ProjectStatus.WORKING
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            name="Bug"
        )
        
        # Create test item in inbox
        self.item = Item.objects.create(
            title="Test Item",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.INBOX,
            organisation=self.org,
        )
        
        self.guard = ItemWorkflowGuard()
        self.activity_service = ActivityService()
    
    def test_transition_valid(self):
        """Test valid state transition"""
        # Transition from Inbox to Backlog
        result = self.guard.transition(self.item, ItemStatus.BACKLOG, self.user)
        
        self.assertEqual(result.status, ItemStatus.BACKLOG)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.BACKLOG)
    
    def test_transition_any_status_allowed(self):
        """Test that any status transition is now allowed"""
        # Transition from Inbox to Testing (previously not allowed)
        result = self.guard.transition(self.item, ItemStatus.TESTING, self.user)
        
        self.assertEqual(result.status, ItemStatus.TESTING)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.TESTING)
    
    def test_transition_from_closed(self):
        """Test that closed items can now transition to other statuses"""
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        
        # Should now be able to transition from Closed to Working
        result = self.guard.transition(self.item, ItemStatus.WORKING, self.user)
        self.assertEqual(result.status, ItemStatus.WORKING)
    
    def test_transition_same_status(self):
        """Test transition to same status is allowed"""
        result = self.guard.transition(self.item, ItemStatus.INBOX, self.user)
        self.assertEqual(result.status, ItemStatus.INBOX)
    
    def test_transition_logs_activity(self):
        """Test that transition logs activity"""
        # Clear any existing activities
        from core.models import Activity
        Activity.objects.all().delete()
        
        # Perform transition
        self.guard.transition(self.item, ItemStatus.BACKLOG, self.user)
        
        # Check activity was logged
        activities = self.activity_service.latest(item=self.item)
        self.assertEqual(activities.count(), 1)
        
        activity = activities.first()
        self.assertEqual(activity.verb, 'item.status_changed')
        self.assertEqual(activity.actor, self.user)
        self.assertIn('Inbox', activity.summary)
        self.assertIn('Backlog', activity.summary)
    
    def test_classify_inbox_backlog(self):
        """Test classify inbox item to backlog"""
        result = self.guard.classify_inbox(self.item, 'backlog', self.user)
        
        self.assertEqual(result.status, ItemStatus.BACKLOG)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.BACKLOG)
    
    def test_classify_inbox_start(self):
        """Test classify inbox item to start working"""
        result = self.guard.classify_inbox(self.item, 'start', self.user)
        
        self.assertEqual(result.status, ItemStatus.WORKING)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)
    
    def test_classify_inbox_close(self):
        """Test classify inbox item to close"""
        result = self.guard.classify_inbox(self.item, 'close', self.user)
        
        self.assertEqual(result.status, ItemStatus.CLOSED)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.CLOSED)
    
    def test_classify_inbox_invalid_action(self):
        """Test classify with invalid action raises error"""
        with self.assertRaises(ValidationError):
            self.guard.classify_inbox(self.item, 'invalid', self.user)
    
    def test_classify_non_inbox_item(self):
        """Test classify non-inbox item raises error"""
        self.item.status = ItemStatus.BACKLOG
        self.item.save()
        
        with self.assertRaises(ValidationError):
            self.guard.classify_inbox(self.item, 'start', self.user)
    
    def test_valid_transitions_from_backlog(self):
        """Test valid transitions from Backlog"""
        self.item.status = ItemStatus.BACKLOG
        self.item.save()
        
        # Should allow Backlog -> Working
        result = self.guard.transition(self.item, ItemStatus.WORKING, self.user)
        self.assertEqual(result.status, ItemStatus.WORKING)
    
    def test_backlog_to_any_status(self):
        """Test that Backlog can transition to any status including non-adjacent ones"""
        self.item.status = ItemStatus.BACKLOG
        self.item.save()
        
        # Should now allow Backlog -> Ready for Release (previously not allowed)
        result = self.guard.transition(self.item, ItemStatus.READY_FOR_RELEASE, self.user)
        self.assertEqual(result.status, ItemStatus.READY_FOR_RELEASE)
