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
    
    def test_items_with_mixed_open_closed_issues(self):
        """Test that items with both open and closed issues show only the open ones"""
        # Create an item with both open and closed issues
        mixed_item = Item.objects.create(
            title="Item with Mixed Issues",
            description="This item has both open and closed issues",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        
        # Add open issue
        open_mapping = ExternalIssueMapping.objects.create(
            item=mixed_item,
            github_id=2001,
            number=201,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testorg/testrepo/issues/201'
        )
        
        # Add closed issue
        closed_mapping = ExternalIssueMapping.objects.create(
            item=mixed_item,
            github_id=2002,
            number=202,
            kind=ExternalIssueKind.ISSUE,
            state='closed',
            html_url='https://github.com/testorg/testrepo/issues/202'
        )
        
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        issues_data = response.context['issues_data']
        issue_numbers = [issue['issue_number'] for issue in issues_data]
        
        # The open issue should be present
        self.assertIn(201, issue_numbers)
        
        # The closed issue should NOT be present
        self.assertNotIn(202, issue_numbers)
        
        # Count should include the mixed item's open issue
        count = get_open_github_issues_count()
        self.assertEqual(count, 3)  # Original 2 + new open issue
    
    def test_pr_display_with_pr(self):
        """Test that PR information is displayed when a PR exists"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        issues_data = response.context['issues_data']
        
        # Find the working_item issue (issue #101)
        issue_101 = None
        for issue in issues_data:
            if issue['issue_number'] == 101:
                issue_101 = issue
                break
        
        self.assertIsNotNone(issue_101)
        
        # Check that PR data is present (working_item has PR #105)
        self.assertIn('pr', issue_101)
        self.assertIsNotNone(issue_101['pr'])
        self.assertEqual(issue_101['pr']['number'], 105)
        self.assertEqual(issue_101['pr']['state'], 'open')
        self.assertIn('https://github.com/testorg/testrepo/pull/105', issue_101['pr']['url'])
    
    def test_pr_display_without_pr(self):
        """Test that 'No PR' marker is displayed when no PR exists"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        issues_data = response.context['issues_data']
        
        # Find the testing_item issue (issue #102) - has no PR
        issue_102 = None
        for issue in issues_data:
            if issue['issue_number'] == 102:
                issue_102 = issue
                break
        
        self.assertIsNotNone(issue_102)
        
        # Check that PR data is None
        self.assertIn('pr', issue_102)
        self.assertIsNone(issue_102['pr'])
        
        # Check that "No PR" is displayed in the HTML
        content = response.content.decode('utf-8')
        self.assertIn('No PR', content)
    
    def test_pr_selection_prefers_non_merged(self):
        """Test that when multiple PRs exist, the first non-merged PR is selected"""
        # Create an item with multiple PRs
        multi_pr_item = Item.objects.create(
            title="Item with Multiple PRs",
            description="This item has multiple PRs",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        
        # Create open issue
        issue_mapping = ExternalIssueMapping.objects.create(
            item=multi_pr_item,
            github_id=3001,
            number=301,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testorg/testrepo/issues/301'
        )
        
        # Create first PR (merged)
        pr1_mapping = ExternalIssueMapping.objects.create(
            item=multi_pr_item,
            github_id=3002,
            number=302,
            kind=ExternalIssueKind.PR,
            state='merged',
            html_url='https://github.com/testorg/testrepo/pull/302'
        )
        
        # Create second PR (open)
        pr2_mapping = ExternalIssueMapping.objects.create(
            item=multi_pr_item,
            github_id=3003,
            number=303,
            kind=ExternalIssueKind.PR,
            state='open',
            html_url='https://github.com/testorg/testrepo/pull/303'
        )
        
        # Create third PR (closed)
        pr3_mapping = ExternalIssueMapping.objects.create(
            item=multi_pr_item,
            github_id=3004,
            number=304,
            kind=ExternalIssueKind.PR,
            state='closed',
            html_url='https://github.com/testorg/testrepo/pull/304'
        )
        
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        issues_data = response.context['issues_data']
        
        # Find the issue #301
        issue_301 = None
        for issue in issues_data:
            if issue['issue_number'] == 301:
                issue_301 = issue
                break
        
        self.assertIsNotNone(issue_301)
        
        # Should select PR #303 (first non-merged, which is the open one)
        self.assertIsNotNone(issue_301['pr'])
        self.assertEqual(issue_301['pr']['number'], 303)
        self.assertEqual(issue_301['pr']['state'], 'open')
    
    def test_pr_selection_all_merged(self):
        """Test that when all PRs are merged, the first PR is selected"""
        # Create an item with multiple merged PRs
        all_merged_item = Item.objects.create(
            title="Item with All Merged PRs",
            description="This item has only merged PRs",
            project=self.project,
            type=self.item_type,
            status=ItemStatus.WORKING,
            organisation=self.org,
            requester=self.user,
            assigned_to=self.user
        )
        
        # Create open issue
        issue_mapping = ExternalIssueMapping.objects.create(
            item=all_merged_item,
            github_id=4001,
            number=401,
            kind=ExternalIssueKind.ISSUE,
            state='open',
            html_url='https://github.com/testorg/testrepo/issues/401'
        )
        
        # Create first merged PR
        pr1_mapping = ExternalIssueMapping.objects.create(
            item=all_merged_item,
            github_id=4002,
            number=402,
            kind=ExternalIssueKind.PR,
            state='merged',
            html_url='https://github.com/testorg/testrepo/pull/402'
        )
        
        # Create second merged PR
        pr2_mapping = ExternalIssueMapping.objects.create(
            item=all_merged_item,
            github_id=4003,
            number=403,
            kind=ExternalIssueKind.PR,
            state='merged',
            html_url='https://github.com/testorg/testrepo/pull/403'
        )
        
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        issues_data = response.context['issues_data']
        
        # Find the issue #401
        issue_401 = None
        for issue in issues_data:
            if issue['issue_number'] == 401:
                issue_401 = issue
                break
        
        self.assertIsNotNone(issue_401)
        
        # Should select first PR #402 (all merged, so pick first)
        self.assertIsNotNone(issue_401['pr'])
        self.assertEqual(issue_401['pr']['number'], 402)
        self.assertEqual(issue_401['pr']['state'], 'merged')
    
    def test_pr_display_in_html(self):
        """Test that PR information is correctly rendered in HTML"""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('items-github-open'))
        
        content = response.content.decode('utf-8')
        
        # Check that PR column header is present
        self.assertIn('Pull Request', content)
        
        # Check that PR #105 is displayed for issue #101
        self.assertIn('#105', content)
        self.assertIn('https://github.com/testorg/testrepo/pull/105', content)
        
        # Check that badge is displayed
        self.assertIn('badge', content)
        self.assertIn('open', content)
