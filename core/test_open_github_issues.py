"""
Tests for Open GitHub Issues ListView and header status element
"""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation,
    User, ExternalIssueMapping, ExternalIssueKind, UserOrganisation
)
from core.views import get_open_github_issues_count
from core.context_processors import open_github_issues_count as context_processor


class OpenGitHubIssuesTestCase(TestCase):
    """Test cases for Open GitHub Issues feature"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create organisation
        self.org = Organisation.objects.create(
            name="Test Organisation"
        )
        
        # Create test user
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            name="Test User",
            active=True
        )
        
        # Link user to organisation
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org,
            is_primary=True
        )
        
        # Create project with GitHub configuration
        self.project = Project.objects.create(
            name="Test Project",
            description="Test project",
            github_owner="testorg",
            github_repo="testrepo"
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key="feature",
            name="Feature"
        )
        
        # Create items with different statuses
        # Working item with open issue
        self.working_item = Item.objects.create(
            title="Working Item with Open Issue",
            description="This item has an open GitHub issue",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        
        # Testing item with open issue
        self.testing_item = Item.objects.create(
            title="Testing Item with Open Issue",
            description="This item has an open GitHub issue",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.TESTING,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        
        # Closed item with open issue (should not appear)
        self.closed_item = Item.objects.create(
            title="Closed Item with Open Issue",
            description="This item is closed",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.CLOSED,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        
        # Working item with closed issue (should not appear)
        self.working_item_closed_issue = Item.objects.create(
            title="Working Item with Closed Issue",
            description="This item has a closed GitHub issue",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        
        # Create GitHub issue mappings
        # Open issue for working item (should appear)
        self.mapping1 = ExternalIssueMapping.objects.create(
            item=self.working_item,
            github_id=1001,
            number=101,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testorg/testrepo/issues/101'
        )
        
        # Open issue for testing item (should appear)
        self.mapping2 = ExternalIssueMapping.objects.create(
            item=self.testing_item,
            github_id=1002,
            number=102,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testorg/testrepo/issues/102'
        )
        
        # Open issue for closed item (should NOT appear)
        self.mapping3 = ExternalIssueMapping.objects.create(
            item=self.closed_item,
            github_id=1003,
            number=103,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testorg/testrepo/issues/103'
        )
        
        # Closed issue for working item (should NOT appear)
        self.mapping4 = ExternalIssueMapping.objects.create(
            item=self.working_item_closed_issue,
            github_id=1004,
            number=104,
            kind=ExternalIssueKind.ISSUE,
            state='closed',
            html_url='https://github.com/testorg/testrepo/issues/104'
        )
        
        # PR for working item (should NOT appear)
        self.mapping5 = ExternalIssueMapping.objects.create(
            item=self.working_item,
            github_id=1005,
            number=105,
            kind=ExternalIssueKind.PR,
            state='open',
            html_url='https://github.com/testorg/testrepo/pull/105'
        )
    
    def test_get_open_github_issues_count(self):
        """Test the get_open_github_issues_count function"""
        count = get_open_github_issues_count()
        
        # Should only count open issues (not PRs) from Working/Testing items
        # Expected: issues #101 and #102
        self.assertEqual(count, 2)
    
    def test_context_processor(self):
        """Test the open_github_issues_count context processor"""
        # Create a mock request with authenticated user
        self.client.login(username='testuser', password='testpass123')
        request = self.client.get(reverse('dashboard')).wsgi_request
        
        context = context_processor(request)
        
        self.assertIn('open_github_issues_count', context)
        self.assertEqual(context['open_github_issues_count'], 2)
    
    def test_context_processor_unauthenticated(self):
        """Test the context processor with unauthenticated user"""
        request = self.client.get(reverse('login')).wsgi_request
        
        context = context_processor(request)
        
        self.assertIn('open_github_issues_count', context)
        self.assertEqual(context['open_github_issues_count'], 0)
    
    def test_items_github_open_view_requires_login(self):
        """Test that the Open GitHub Issues view requires login"""
        response = self.client.get(reverse('items-github-open'))
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_items_github_open_view_authenticated(self):
        """Test the Open GitHub Issues view when authenticated"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        # Should return 200 OK
        self.assertEqual(response.status_code, 200)
        
        # Check template is correct
        self.assertTemplateUsed(response, 'items_github_open.html')
        
        # Check context data
        self.assertIn('issues_data', response.context)
        issues_data = response.context['issues_data']
        
        # Should have exactly 2 issues
        self.assertEqual(len(issues_data), 2)
        
        # Check that correct issues are included
        issue_numbers = [issue['issue_number'] for issue in issues_data]
        self.assertIn(101, issue_numbers)
        self.assertIn(102, issue_numbers)
        
        # Check sorting (descending by issue number)
        self.assertEqual(issues_data[0]['issue_number'], 102)
        self.assertEqual(issues_data[1]['issue_number'], 101)
    
    def test_items_github_open_view_content(self):
        """Test the content of the Open GitHub Issues view"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        content = response.content.decode('utf-8')
        
        # Check page title
        self.assertIn('Open GitHub Issues', content)
        
        # Check that open issues are displayed
        self.assertIn('#101', content)
        self.assertIn('#102', content)
        self.assertIn('Working Item with Open Issue', content)
        self.assertIn('Testing Item with Open Issue', content)
        
        # Check that closed issues are NOT displayed
        self.assertNotIn('#103', content)
        self.assertNotIn('#104', content)
        self.assertNotIn('Closed Item with Open Issue', content)
        
        # Check that PRs are NOT displayed
        self.assertNotIn('#105', content)
        self.assertNotIn('/pull/105', content)
        
        # Check that GitHub links are present
        self.assertIn('https://github.com/testorg/testrepo/issues/101', content)
        self.assertIn('https://github.com/testorg/testrepo/issues/102', content)
    
    def test_items_github_open_view_empty_state(self):
        """Test the Open GitHub Issues view when there are no open issues"""
        # Delete all open issue mappings
        ExternalIssueMapping.objects.filter(
            kind=ExternalIssueKind.ISSUE,
            item__status__in=[ItemStatus.WORKING, ItemStatus.TESTING]
        ).exclude(state='closed').delete()
        
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        content = response.content.decode('utf-8')
        
        # Should show empty state message
        self.assertIn('No open GitHub issues', content)
    
    def test_filtering_excludes_prs(self):
        """Test that PRs are correctly excluded from the list"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        issues_data = response.context['issues_data']
        
        # Verify no PRs in the results
        for issue in issues_data:
            mapping = ExternalIssueMapping.objects.get(number=issue['issue_number'])
            self.assertEqual(mapping.kind, ExternalIssueKind.ISSUE)
    
    def test_filtering_excludes_closed_issues(self):
        """Test that closed issues are correctly excluded from the list"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        issues_data = response.context['issues_data']
        
        # Verify no closed issues in the results
        for issue in issues_data:
            mapping = ExternalIssueMapping.objects.get(number=issue['issue_number'])
            self.assertNotEqual(mapping.state, 'closed')
    
    def test_filtering_includes_only_working_testing_items(self):
        """Test that only items with Working or Testing status are included"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        issues_data = response.context['issues_data']
        
        # Verify all items are in Working or Testing status
        for issue in issues_data:
            item = Item.objects.get(id=issue['item_id'])
            self.assertIn(item.status, [ItemStatus.WORKING, ItemStatus.TESTING])
