"""
Tests for embed endpoint views.

These tests verify the token-based external access to project issues
via the embed portal.
"""
from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    Organisation, Project, OrganisationEmbedProject, Item, ItemType,
    ItemStatus, ItemComment, User, CommentVisibility, CommentKind
)


class EmbedEndpointTestCase(TestCase):
    """Test embed endpoint functionality"""

    def setUp(self):
        """Set up test data"""
        # Create organisations
        self.org1 = Organisation.objects.create(name='Test Org 1')
        self.org2 = Organisation.objects.create(name='Test Org 2')
        
        # Create projects
        self.project1 = Project.objects.create(
            name='Test Project 1',
            description='Test project 1'
        )
        self.project2 = Project.objects.create(
            name='Test Project 2',
            description='Test project 2'
        )
        
        # Create item types
        self.item_type_bug = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        self.item_type_feature = ItemType.objects.create(
            key='feature',
            name='Feature',
            is_active=True
        )
        
        # Create embed access for org1 -> project1
        self.embed_access = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project1,
            is_enabled=True
        )
        self.valid_token = self.embed_access.embed_token
        
        # Create disabled embed access for org2 -> project2
        self.disabled_embed = OrganisationEmbedProject.objects.create(
            organisation=self.org2,
            project=self.project2,
            is_enabled=False
        )
        self.disabled_token = self.disabled_embed.embed_token
        
        # Create some items for project1
        self.item1 = Item.objects.create(
            project=self.project1,
            organisation=self.org1,
            title='Test Issue 1',
            description='Description 1',
            type=self.item_type_bug,
            status=ItemStatus.INBOX
        )
        self.item2 = Item.objects.create(
            project=self.project1,
            organisation=self.org1,
            title='Test Issue 2',
            description='Description 2',
            type=self.item_type_feature,
            status=ItemStatus.WORKING
        )
        
        # Create item with user_input for testing
        self.item_with_user_input = Item.objects.create(
            project=self.project1,
            organisation=self.org1,
            title='Issue with User Input',
            description='Internal technical description',
            user_input='Customer request text',
            type=self.item_type_bug,
            status=ItemStatus.INBOX
        )
        
        # Create item for project2
        self.item_other_project = Item.objects.create(
            project=self.project2,
            organisation=self.org2,
            title='Other Project Issue',
            description='Should not be accessible',
            type=self.item_type_bug,
            status=ItemStatus.INBOX
        )
        
        # Create a user for comments
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        # Associate user with org1 for requester selection
        from core.models import UserOrganisation
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org1,
            role='User',
            is_primary=True
        )
        
        # Create some comments on item1
        self.comment1 = ItemComment.objects.create(
            item=self.item1,
            author=self.user,
            body='Public comment',
            visibility=CommentVisibility.PUBLIC,
            kind=CommentKind.COMMENT
        )
        self.comment2 = ItemComment.objects.create(
            item=self.item1,
            author=self.user,
            body='Internal comment',
            visibility=CommentVisibility.INTERNAL,
            kind=CommentKind.COMMENT
        )
        
        # Create test client
        self.client = Client()

    def test_project_issues_list_with_valid_token(self):
        """Test that valid token allows access to project issues list"""
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item1.title)
        self.assertContains(response, self.item2.title)
        self.assertNotContains(response, self.item_other_project.title)

    def test_project_issues_list_without_token(self):
        """Test that missing token returns 404"""
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/'
        )
        
        self.assertEqual(response.status_code, 404)

    def test_project_issues_list_with_invalid_token(self):
        """Test that invalid token returns 404"""
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': 'invalid-token-12345'}
        )
        
        self.assertEqual(response.status_code, 404)

    def test_project_issues_list_with_disabled_token(self):
        """Test that disabled token returns 403"""
        response = self.client.get(
            f'/embed/projects/{self.project2.id}/issues/',
            {'token': self.disabled_token}
        )
        
        self.assertEqual(response.status_code, 403)

    def test_project_issues_list_wrong_project(self):
        """Test that token cannot access different project"""
        response = self.client.get(
            f'/embed/projects/{self.project2.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 404)

    def test_issue_detail_with_valid_token(self):
        """Test that valid token allows access to issue detail"""
        response = self.client.get(
            f'/embed/issues/{self.item1.id}/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item1.title)
        # Description should NOT be shown in detail view
        self.assertNotContains(response, 'Description')
        self.assertNotContains(response, self.item1.description)

    def test_issue_detail_shows_only_public_comments(self):
        """Test that issue detail shows only public comments"""
        response = self.client.get(
            f'/embed/issues/{self.item1.id}/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public comment')
        self.assertNotContains(response, 'Internal comment')

    def test_issue_detail_shows_user_input(self):
        """Test that issue detail shows user_input instead of description"""
        response = self.client.get(
            f'/embed/issues/{self.item_with_user_input.id}/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Should show user_input
        self.assertContains(response, 'Customer request text')
        self.assertContains(response, 'Customer Request')
        # Should NOT show internal description
        self.assertNotContains(response, 'Internal technical description')

    def test_issue_detail_wrong_project(self):
        """Test that token cannot access issue from different project"""
        response = self.client.get(
            f'/embed/issues/{self.item_other_project.id}/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 404)

    def test_issue_detail_without_token(self):
        """Test that missing token returns 404"""
        response = self.client.get(f'/embed/issues/{self.item1.id}/')
        
        self.assertEqual(response.status_code, 404)

    def test_issue_detail_with_disabled_token(self):
        """Test that disabled token returns 403"""
        response = self.client.get(
            f'/embed/issues/{self.item_other_project.id}/',
            {'token': self.disabled_token}
        )
        
        self.assertEqual(response.status_code, 403)

    def test_issue_create_form_with_valid_token(self):
        """Test that valid token allows access to create form"""
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/create/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create New Issue')
        self.assertContains(response, self.item_type_bug.name)
        self.assertContains(response, self.item_type_feature.name)

    def test_issue_create_form_shows_type_descriptions(self):
        """Test that issue creation form includes type descriptions in data attributes"""
        # Add description to item type
        self.item_type_bug.description = 'Use this for reporting bugs and defects'
        self.item_type_bug.save()
        
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/create/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Check that description is in the data-description attribute
        self.assertContains(response, 'data-description="Use this for reporting bugs and defects"')
        # Check that JavaScript for showing description is present
        self.assertContains(response, 'type-description')

    def test_issue_create_form_without_token(self):
        """Test that missing token returns 404"""
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/create/'
        )
        
        self.assertEqual(response.status_code, 404)

    def test_issue_create_form_with_disabled_token(self):
        """Test that disabled token returns 403"""
        response = self.client.get(
            f'/embed/projects/{self.project2.id}/issues/create/',
            {'token': self.disabled_token}
        )
        
        self.assertEqual(response.status_code, 403)

    def test_issue_create_success(self):
        """Test successful issue creation"""
        initial_count = Item.objects.filter(project=self.project1).count()
        
        response = self.client.post(
            f'/embed/projects/{self.project1.id}/issues/create/submit/',
            {
                'token': self.valid_token,
                'title': 'New External Issue',
                'description': 'Created via embed portal',
                'type': self.item_type_bug.id,
                'requester': self.user.id,
            }
        )
        
        # Should redirect to issue detail
        self.assertEqual(response.status_code, 302)
        
        # Check item was created
        new_count = Item.objects.filter(project=self.project1).count()
        self.assertEqual(new_count, initial_count + 1)
        
        # Check item properties
        new_item = Item.objects.filter(
            project=self.project1,
            title='New External Issue'
        ).first()
        self.assertIsNotNone(new_item)
        self.assertEqual(new_item.description, 'Created via embed portal')
        self.assertEqual(new_item.type, self.item_type_bug)
        self.assertEqual(new_item.status, ItemStatus.INBOX)
        self.assertEqual(new_item.organisation, self.org1)
        self.assertEqual(new_item.requester, self.user)

    def test_issue_create_missing_title(self):
        """Test issue creation fails without title"""
        response = self.client.post(
            f'/embed/projects/{self.project1.id}/issues/create/submit/',
            {
                'token': self.valid_token,
                'description': 'No title',
                'type': self.item_type_bug.id,
            }
        )
        
        self.assertEqual(response.status_code, 400)

    def test_issue_create_missing_type(self):
        """Test issue creation fails without type"""
        response = self.client.post(
            f'/embed/projects/{self.project1.id}/issues/create/submit/',
            {
                'token': self.valid_token,
                'title': 'No Type Issue',
                'description': 'Missing type',
            }
        )
        
        self.assertEqual(response.status_code, 400)

    def test_issue_create_invalid_type(self):
        """Test issue creation fails with invalid type"""
        response = self.client.post(
            f'/embed/projects/{self.project1.id}/issues/create/submit/',
            {
                'token': self.valid_token,
                'title': 'Invalid Type Issue',
                'type': 99999,
                'requester': self.user.id,
            }
        )
        
        self.assertEqual(response.status_code, 400)

    def test_issue_create_missing_requester(self):
        """Test issue creation fails without requester"""
        response = self.client.post(
            f'/embed/projects/{self.project1.id}/issues/create/submit/',
            {
                'token': self.valid_token,
                'title': 'No Requester Issue',
                'description': 'Missing requester',
                'type': self.item_type_bug.id,
            }
        )
        
        self.assertEqual(response.status_code, 400)

    def test_issue_create_title_too_long(self):
        """Test issue creation fails with title exceeding max length"""
        long_title = 'x' * 501  # Exceeds 500 character limit
        response = self.client.post(
            f'/embed/projects/{self.project1.id}/issues/create/submit/',
            {
                'token': self.valid_token,
                'title': long_title,
                'type': self.item_type_bug.id,
                'requester': self.user.id,
            }
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'must not exceed 500 characters', response.content)

    def test_issue_create_without_token(self):
        """Test issue creation fails without token"""
        response = self.client.post(
            f'/embed/projects/{self.project1.id}/issues/create/submit/',
            {
                'title': 'No Token Issue',
                'type': self.item_type_bug.id,
            }
        )
        
        self.assertEqual(response.status_code, 404)

    def test_issue_create_with_disabled_token(self):
        """Test issue creation fails with disabled token"""
        response = self.client.post(
            f'/embed/projects/{self.project2.id}/issues/create/submit/',
            {
                'token': self.disabled_token,
                'title': 'Disabled Token Issue',
                'type': self.item_type_bug.id,
            }
        )
        
        self.assertEqual(response.status_code, 403)

    def test_issue_create_wrong_project(self):
        """Test that token cannot create issue in different project"""
        response = self.client.post(
            f'/embed/projects/{self.project2.id}/issues/create/submit/',
            {
                'token': self.valid_token,
                'title': 'Wrong Project Issue',
                'type': self.item_type_bug.id,
            }
        )
        
        self.assertEqual(response.status_code, 404)

    def test_add_comment_success(self):
        """Test successful comment addition"""
        initial_count = self.item1.comments.count()
        
        response = self.client.post(
            f'/embed/issues/{self.item1.id}/comments/',
            {
                'token': self.valid_token,
                'body': 'External comment via embed portal',
            }
        )
        
        # Should redirect to issue detail
        self.assertEqual(response.status_code, 302)
        
        # Check comment was created
        new_count = self.item1.comments.count()
        self.assertEqual(new_count, initial_count + 1)
        
        # Check comment properties
        new_comment = ItemComment.objects.filter(
            item=self.item1,
            body='External comment via embed portal'
        ).first()
        self.assertIsNotNone(new_comment)
        self.assertEqual(new_comment.visibility, CommentVisibility.PUBLIC)
        self.assertEqual(new_comment.kind, CommentKind.COMMENT)
        self.assertIsNone(new_comment.author)  # External commenter

    def test_add_comment_empty_body(self):
        """Test comment addition fails with empty body"""
        response = self.client.post(
            f'/embed/issues/{self.item1.id}/comments/',
            {
                'token': self.valid_token,
                'body': '',
            }
        )
        
        self.assertEqual(response.status_code, 400)

    def test_add_comment_without_token(self):
        """Test comment addition fails without token"""
        response = self.client.post(
            f'/embed/issues/{self.item1.id}/comments/',
            {
                'body': 'No token comment',
            }
        )
        
        self.assertEqual(response.status_code, 404)

    def test_add_comment_with_disabled_token(self):
        """Test comment addition fails with disabled token"""
        response = self.client.post(
            f'/embed/issues/{self.item_other_project.id}/comments/',
            {
                'token': self.disabled_token,
                'body': 'Disabled token comment',
            }
        )
        
        self.assertEqual(response.status_code, 403)

    def test_add_comment_wrong_project(self):
        """Test that token cannot add comment to issue from different project"""
        response = self.client.post(
            f'/embed/issues/{self.item_other_project.id}/comments/',
            {
                'token': self.valid_token,
                'body': 'Wrong project comment',
            }
        )
        
        self.assertEqual(response.status_code, 404)

    def test_embed_access_isolation(self):
        """Test that embed access is properly isolated between projects"""
        # Create another embed access for the same org to project2
        embed2 = OrganisationEmbedProject.objects.create(
            organisation=self.org1,
            project=self.project2,
            is_enabled=True
        )
        token2 = embed2.embed_token
        
        # Token 1 should access project1 items
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': self.valid_token}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item1.title)
        
        # Token 2 should access project2 items
        response = self.client.get(
            f'/embed/projects/{self.project2.id}/issues/',
            {'token': token2}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.item_other_project.title)
        
        # Token 1 should NOT access project2
        response = self.client.get(
            f'/embed/projects/{self.project2.id}/issues/',
            {'token': self.valid_token}
        )
        self.assertEqual(response.status_code, 404)
        
        # Token 2 should NOT access project1
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': token2}
        )
        self.assertEqual(response.status_code, 404)

    def test_status_filter_closed(self):
        """Test status filter for closed issues"""
        # Create a closed issue
        closed_item = Item.objects.create(
            project=self.project1,
            organisation=self.org1,
            title='Closed Issue',
            description='This is closed',
            type=self.item_type_bug,
            status=ItemStatus.CLOSED
        )
        
        # Filter for closed issues
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': self.valid_token, 'status': 'closed'}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Closed Issue')
        self.assertNotContains(response, 'Test Issue 1')  # Not closed
        self.assertNotContains(response, 'Test Issue 2')  # Not closed

    def test_status_filter_not_closed(self):
        """Test status filter for non-closed issues"""
        # Create a closed issue
        closed_item = Item.objects.create(
            project=self.project1,
            organisation=self.org1,
            title='Closed Issue',
            description='This is closed',
            type=self.item_type_bug,
            status=ItemStatus.CLOSED
        )
        
        # Filter for not closed issues
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': self.valid_token, 'status': 'not_closed'}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Closed Issue')
        self.assertContains(response, 'Test Issue 1')  # Not closed
        self.assertContains(response, 'Test Issue 2')  # Not closed

    def test_solution_description_indicator_shown(self):
        """Test that solution description indicator is shown when solution_description exists"""
        # Create an item with solution description
        item_with_solution = Item.objects.create(
            project=self.project1,
            organisation=self.org1,
            title='Issue with Solution',
            description='Description',
            solution_description='## Solution\n\nThis is the solution description.',
            type=self.item_type_bug,
            status=ItemStatus.CLOSED
        )
        
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Check for the solution button/indicator
        self.assertContains(response, 'bi-lightbulb')
        self.assertContains(response, f'solutionModal{item_with_solution.id}')

    def test_solution_description_indicator_not_shown_when_empty(self):
        """Test that solution description indicator is NOT shown when solution_description is empty"""
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # item1 and item2 have no solution_description, so no modal should exist for them
        self.assertNotContains(response, f'solutionModal{self.item1.id}')
        self.assertNotContains(response, f'solutionModal{self.item2.id}')

    def test_solution_description_indicator_not_shown_when_whitespace_only(self):
        """Test that solution description indicator is NOT shown when solution_description is only whitespace"""
        # Create an item with whitespace-only solution description
        item_whitespace = Item.objects.create(
            project=self.project1,
            organisation=self.org1,
            title='Issue with Whitespace Solution',
            description='Description',
            solution_description='   \n\t  ',
            type=self.item_type_bug,
            status=ItemStatus.INBOX
        )
        
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Should NOT show modal for whitespace-only solution
        self.assertNotContains(response, f'solutionModal{item_whitespace.id}')

    def test_solution_description_modal_renders_markdown(self):
        """Test that solution description modal renders markdown properly"""
        # Create an item with markdown solution description
        markdown_text = '''## Solution Overview

This is a **bold** statement.

* List item 1
* List item 2

[Link to example](https://example.com)
'''
        item_with_solution = Item.objects.create(
            project=self.project1,
            organisation=self.org1,
            title='Issue with Markdown Solution',
            description='Description',
            solution_description=markdown_text,
            type=self.item_type_bug,
            status=ItemStatus.CLOSED
        )
        
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Check modal exists
        self.assertContains(response, f'solutionModal{item_with_solution.id}')
        # Check that markdown is rendered to HTML
        self.assertContains(response, '<h2>Solution Overview</h2>')
        self.assertContains(response, '<strong>bold</strong>')
        self.assertContains(response, '<ul>')
        self.assertContains(response, '<li>List item 1</li>')

    def test_solution_description_modal_sanitizes_html(self):
        """Test that solution description modal sanitizes dangerous HTML/XSS attempts"""
        # Create an item with malicious content
        malicious_markdown = '''## Safe Content

<script>alert('XSS')</script>

[Click me](javascript:alert('XSS'))

<img src="x" onerror="alert('XSS')">
'''
        item_with_xss = Item.objects.create(
            project=self.project1,
            organisation=self.org1,
            title='Issue with XSS Attempt',
            description='Description',
            solution_description=malicious_markdown,
            type=self.item_type_bug,
            status=ItemStatus.CLOSED
        )
        
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Check that script tags are removed
        self.assertNotContains(response, '<script>')
        self.assertNotContains(response, "alert('XSS')")
        # Check that javascript: URLs are removed
        self.assertNotContains(response, 'javascript:')
        # Check that onerror handlers are removed
        self.assertNotContains(response, 'onerror=')
        # But safe content should remain
        self.assertContains(response, '<h2>Safe Content</h2>')

    def test_solution_description_modal_title_and_structure(self):
        """Test that solution description modal has correct structure"""
        item_with_solution = Item.objects.create(
            project=self.project1,
            organisation=self.org1,
            title='Test Issue with Solution',
            description='Description',
            solution_description='This is a simple solution.',
            type=self.item_type_bug,
            status=ItemStatus.CLOSED
        )
        
        response = self.client.get(
            f'/embed/projects/{self.project1.id}/issues/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Check modal structure
        self.assertContains(response, 'Solution Description')
        self.assertContains(response, f'Issue #{item_with_solution.id}')
        self.assertContains(response, 'Test Issue with Solution')
        self.assertContains(response, 'This is a simple solution.')


class EmbedInternalItemsSecurityTestCase(TestCase):
    """Test that internal items (intern=True) are never shown in embed portal"""

    def setUp(self):
        """Set up test data"""
        # Create organisations and projects
        self.org = Organisation.objects.create(name='Test Org')
        self.project = Project.objects.create(
            name='Test Project',
            description='Test project'
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='bug',
            name='Bug',
            is_active=True
        )
        
        # Create embed access
        self.embed_access = OrganisationEmbedProject.objects.create(
            organisation=self.org,
            project=self.project,
            is_enabled=True
        )
        self.token = self.embed_access.embed_token
        
        # Create a regular (non-internal) item
        self.public_item = Item.objects.create(
            project=self.project,
            organisation=self.org,
            title='Public Item',
            description='This is public',
            type=self.item_type,
            status=ItemStatus.INBOX,
            intern=False
        )
        
        # Create an internal item
        self.internal_item = Item.objects.create(
            project=self.project,
            organisation=self.org,
            title='Internal Item - SECRET',
            description='This should never be visible in customer portal',
            type=self.item_type,
            status=ItemStatus.INBOX,
            intern=True
        )
        
        self.client = Client()

    def test_internal_item_not_in_issues_list(self):
        """Test that internal items are not shown in the issues list"""
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/',
            {'token': self.token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Public item should be visible
        self.assertContains(response, 'Public Item')
        # Internal item should NOT be visible
        self.assertNotContains(response, 'Internal Item - SECRET')
        self.assertNotContains(response, 'This should never be visible in customer portal')

    def test_internal_item_not_accessible_via_detail_view(self):
        """Test that internal items cannot be accessed via detail view"""
        response = self.client.get(
            f'/embed/issues/{self.internal_item.id}/',
            {'token': self.token}
        )
        
        # Should return 404, not show the item
        self.assertEqual(response.status_code, 404)

    def test_public_item_accessible_via_detail_view(self):
        """Test that public items can be accessed via detail view"""
        response = self.client.get(
            f'/embed/issues/{self.public_item.id}/',
            {'token': self.token}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Item')

    def test_internal_item_not_in_filtered_results(self):
        """Test that internal items are excluded even when filtering"""
        # Filter by status - should still exclude internal items
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/',
            {'token': self.token, 'status': 'not_closed'}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public Item')
        self.assertNotContains(response, 'Internal Item - SECRET')

    def test_internal_item_not_in_search_results(self):
        """Test that internal items are excluded from search results"""
        # Search for the internal item - should not be found
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/',
            {'token': self.token, 'q': 'SECRET'}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Internal Item - SECRET')
        self.assertNotContains(response, 'SECRET')

    def test_kpis_exclude_internal_items(self):
        """Test that KPI counts exclude internal items"""
        # Create more items with different statuses
        Item.objects.create(
            project=self.project,
            organisation=self.org,
            title='Public Backlog Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            intern=False
        )
        Item.objects.create(
            project=self.project,
            organisation=self.org,
            title='Internal Backlog Item',
            type=self.item_type,
            status=ItemStatus.BACKLOG,
            intern=True
        )
        
        response = self.client.get(
            f'/embed/projects/{self.project.id}/issues/',
            {'token': self.token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Check that KPI counts are correct (excluding internal items)
        # We have 2 public items (inbox + backlog), 0 closed in 30d
        context = response.context
        self.assertEqual(context['kpis']['open_count'], 2)  # Only public items
        self.assertEqual(context['kpis']['inbox_count'], 1)  # Only public inbox item
        self.assertEqual(context['kpis']['backlog_count'], 1)  # Only public backlog item

    def test_releases_page_excludes_internal_items(self):
        """Test that the releases page excludes internal items"""
        from core.models import Release
        
        # Create a release
        release = Release.objects.create(
            project=self.project,
            name='Test Release',
            version='1.0.0'
        )
        
        # Assign both public and internal items to the release
        self.public_item.solution_release = release
        self.public_item.save()
        
        self.internal_item.solution_release = release
        self.internal_item.save()
        
        response = self.client.get(
            f'/embed/projects/{self.project.id}/releases/',
            {'token': self.token}
        )
        
        self.assertEqual(response.status_code, 200)
        # Public item should be visible
        self.assertContains(response, 'Public Item')
        # Internal item should NOT be visible
        self.assertNotContains(response, 'Internal Item - SECRET')
