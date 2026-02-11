"""
Tests for blueprint views
"""

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    IssueBlueprint, IssueBlueprintCategory, User
)


class BlueprintDetailViewTestCase(TestCase):
    """Test cases for blueprint detail view"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            name="Test User"
        )
        
        # Log in the user
        self.client.force_login(self.user)
        
        # Create blueprint category
        self.category = IssueBlueprintCategory.objects.create(
            name="Features",
            slug="features"
        )
        
        # Create blueprint with markdown description
        self.blueprint = IssueBlueprint.objects.create(
            title="User Authentication",
            category=self.category,
            description_md="# Authentication\n\nImplement user authentication.\n\n## Acceptance Criteria\n- Users can log in\n- Users can log out",
            is_active=True,
            version=1,
            created_by=self.user
        )
    
    def test_blueprint_detail_renders_without_error(self):
        """Test that blueprint detail page renders without TemplateSyntaxError"""
        url = reverse('blueprint-detail', kwargs={'id': self.blueprint.id})
        response = self.client.get(url)
        
        # Should return HTTP 200, not 500
        self.assertEqual(response.status_code, 200)
        
        # Should contain blueprint title
        self.assertContains(response, self.blueprint.title)
        
        # Should not have any template syntax errors
        self.assertNotContains(response, 'TemplateSyntaxError')
        self.assertNotContains(response, 'markdown_extras')
    
    def test_blueprint_detail_renders_markdown(self):
        """Test that blueprint detail page renders markdown content"""
        url = reverse('blueprint-detail', kwargs={'id': self.blueprint.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Markdown should be converted to HTML
        # The markdown "# Authentication" should become an h1 tag
        self.assertContains(response, '<h1')
        self.assertContains(response, 'Authentication')
        
        # Should contain the acceptance criteria
        self.assertContains(response, 'Acceptance Criteria')
    
    def test_blueprint_detail_shows_metadata(self):
        """Test that blueprint detail page shows blueprint metadata"""
        url = reverse('blueprint-detail', kwargs={'id': self.blueprint.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        
        # Should show category
        self.assertContains(response, self.category.name)
        
        # Should show version
        self.assertContains(response, 'Version 1')
        
        # Should show active status
        self.assertContains(response, 'Active')
        
        # Should show created by
        self.assertContains(response, self.user.username)


class BlueprintCreateViewTestCase(TestCase):
    """Test cases for blueprint create view"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            name="Test User"
        )
        
        # Log in the user
        self.client.force_login(self.user)
        
        # Create blueprint category
        self.category = IssueBlueprintCategory.objects.create(
            name="Features",
            slug="features",
            is_active=True
        )
    
    def test_blueprint_create_page_renders_without_error(self):
        """Test that blueprint create page renders without NoReverseMatch error (Issue #373)"""
        url = reverse('blueprint-create')
        response = self.client.get(url)
        
        # Should return HTTP 200, not 500
        # This test specifically addresses Issue #373 where the page failed
        # with NoReverseMatch error when trying to use '0' as blueprint ID
        self.assertEqual(response.status_code, 200)
        
        # Should contain the form
        self.assertContains(response, 'blueprintForm')


class BlueprintEditViewTestCase(TestCase):
    """Test cases for blueprint edit view"""
    
    def setUp(self):
        """Set up test data"""
        # Create client
        self.client = Client()
        
        # Create test user
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            name="Test User"
        )
        
        # Log in the user
        self.client.force_login(self.user)
        
        # Create blueprint category
        self.category = IssueBlueprintCategory.objects.create(
            name="Features",
            slug="features",
            is_active=True
        )
        
        # Create blueprint
        self.blueprint = IssueBlueprint.objects.create(
            title="User Authentication",
            category=self.category,
            description_md="# Authentication\n\nImplement user authentication.",
            is_active=True,
            version=1,
            created_by=self.user
        )
    
    def test_blueprint_edit_page_renders_without_error(self):
        """Test that blueprint edit page renders without NoReverseMatch error"""
        url = reverse('blueprint-edit', kwargs={'id': self.blueprint.id})
        response = self.client.get(url)
        
        # Should return HTTP 200, not 500
        self.assertEqual(response.status_code, 200)
        
        # Should contain the form
        self.assertContains(response, 'blueprintForm')
        
        # Should contain the blueprint title in the form
        self.assertContains(response, self.blueprint.title)
