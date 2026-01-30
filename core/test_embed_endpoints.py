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
        self.assertContains(response, self.item1.description)

    def test_issue_detail_shows_only_public_comments(self):
        """Test that issue detail shows only public comments"""
        response = self.client.get(
            f'/embed/issues/{self.item1.id}/',
            {'token': self.valid_token}
        )
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Public comment')
        self.assertNotContains(response, 'Internal comment')

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
