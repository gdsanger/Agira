"""
Tests for blueprint extension features:
1. Create issue from blueprint with variables
2. Apply blueprint to existing issue with variables
3. Create new item with blueprint selection
"""
from django.test import TestCase, Client
from django.urls import reverse
from core.models import (
    User, Organisation, Project, Item, ItemType, ItemStatus,
    IssueBlueprint, IssueBlueprintCategory
)
import json


class BlueprintExtensionTestCase(TestCase):
    """Test cases for blueprint extension features"""
    
    def setUp(self):
        """Set up test data"""
        # Create test organization
        self.org = Organisation.objects.create(
            name="Test Org",
            short="TEST"
        )
        
        # Create test user
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            name="Test User"
        )
        self.user.set_password("testpass123")
        self.user.save()
        
        # Associate user with organization
        from core.models import UserOrganisation, UserRole
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org,
            role=UserRole.USER
        )
        
        # Create test project
        self.project = Project.objects.create(
            name="Test Project"
        )
        self.project.clients.add(self.org)
        
        # Create test item type
        self.item_type = ItemType.objects.create(
            name="Feature",
            is_active=True
        )
        
        # Set default item type for project
        self.project.default_item_type = self.item_type
        self.project.save()
        
        # Create blueprint category
        self.category = IssueBlueprintCategory.objects.create(
            name="Features",
            slug="features"
        )
        
        # Create blueprint with variables
        self.blueprint = IssueBlueprint.objects.create(
            title="{{ feature_name }}",
            category=self.category,
            description_md="""# {{ feature_name }}

## Description
This feature will add {{ feature_description }} to the system.

## Acceptance Criteria
- [ ] {{ criterion_1 }}
- [ ] {{ criterion_2 }}

## Technical Notes
This will be implemented in {{ project_name }}.
""",
            is_active=True,
            created_by=self.user
        )
        
        # Create blueprint without variables
        self.simple_blueprint = IssueBlueprint.objects.create(
            title="Simple Feature",
            category=self.category,
            description_md="This is a simple feature without variables.",
            is_active=True,
            created_by=self.user
        )
        
        # Set up client
        self.client = Client()
        self.client.login(username="testuser", password="testpass123")
    
    def test_create_issue_from_blueprint_with_variables(self):
        """Test creating an issue from a blueprint with variable replacement"""
        url = reverse('blueprint-create-issue', args=[self.blueprint.id])
        
        variables = {
            'feature_name': 'User Authentication',
            'feature_description': 'OAuth2 support',
            'criterion_1': 'Users can login with Google',
            'criterion_2': 'Users can login with GitHub',
            'project_name': 'Agira'
        }
        
        response = self.client.post(url, {
            'project_id': self.project.id,
            'variables': json.dumps(variables)
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify the item was created with replaced variables
        item = Item.objects.latest('created_at')
        self.assertEqual(item.title, 'User Authentication')
        self.assertIn('OAuth2 support', item.description)
        self.assertIn('Users can login with Google', item.description)
        self.assertNotIn('{{', item.description)  # No variables left
        self.assertNotIn('}}', item.description)
    
    def test_create_issue_from_blueprint_missing_variables(self):
        """Test creating an issue with missing variables returns error"""
        url = reverse('blueprint-create-issue', args=[self.blueprint.id])
        
        # Missing some required variables
        variables = {
            'feature_name': 'User Authentication',
        }
        
        response = self.client.post(url, {
            'project_id': self.project.id,
            'variables': json.dumps(variables)
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Missing required variables', data['error'])
    
    def test_apply_blueprint_to_existing_item_with_variables(self):
        """Test applying a blueprint to an existing item with variables"""
        # Create an existing item
        item = Item.objects.create(
            project=self.project,
            title="Original Title",
            description="Original description",
            type=self.item_type
        )
        
        url = reverse('item-apply-blueprint-submit', args=[item.id])
        
        variables = {
            'feature_name': 'Payment Integration',
            'feature_description': 'Stripe payment support',
            'criterion_1': 'Process credit card payments',
            'criterion_2': 'Handle payment failures gracefully',
            'project_name': 'E-commerce'
        }
        
        response = self.client.post(url, {
            'blueprint_id': str(self.blueprint.id),
            'variables': json.dumps(variables),
            'replace_description': 'on'  # Replace instead of append
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Reload item and verify description was replaced with variables
        item.refresh_from_db()
        self.assertIn('Stripe payment support', item.description)
        self.assertIn('Process credit card payments', item.description)
        self.assertNotIn('{{', item.description)
        self.assertNotIn('Original description', item.description)  # Original replaced
    
    def test_apply_blueprint_append_mode(self):
        """Test applying a blueprint in append mode"""
        item = Item.objects.create(
            project=self.project,
            title="Existing Item",
            description="Existing content",
            type=self.item_type
        )
        
        url = reverse('item-apply-blueprint-submit', args=[item.id])
        
        variables = {
            'feature_name': 'New Feature',
            'feature_description': 'test',
            'criterion_1': 'test1',
            'criterion_2': 'test2',
            'project_name': 'test'
        }
        
        response = self.client.post(url, {
            'blueprint_id': str(self.blueprint.id),
            'variables': json.dumps(variables)
            # No replace_description flag = append mode
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Verify original content is preserved
        item.refresh_from_db()
        self.assertIn('Existing content', item.description)
        self.assertIn('New Feature', item.description)
        self.assertIn('Blueprint angewendet', item.description)
    
    def test_create_item_with_blueprint_selection(self):
        """Test creating a new item with blueprint selection"""
        url = reverse('item-create')
        
        variables = {
            'feature_name': 'API Integration',
            'feature_description': 'REST API',
            'criterion_1': 'Implement endpoints',
            'criterion_2': 'Add authentication',
            'project_name': 'Backend'
        }
        
        response = self.client.post(url, {
            'project': self.project.id,
            'type': self.item_type.id,
            'blueprint': str(self.blueprint.id),
            'blueprint_variables': json.dumps(variables),
            'status': ItemStatus.INBOX,
        })
        
        # The view uses HTMX, check for success
        self.assertEqual(response.status_code, 200)
        
        # Verify item was created with blueprint content
        item = Item.objects.latest('created_at')
        self.assertEqual(item.title, 'API Integration')
        self.assertIn('REST API', item.description)
        self.assertNotIn('{{', item.description)
    
    def test_create_item_without_blueprint(self):
        """Test creating a new item without blueprint (normal flow)"""
        url = reverse('item-create')
        
        response = self.client.post(url, {
            'project': self.project.id,
            'type': self.item_type.id,
            'title': 'Manual Title',
            'description': 'Manual description',
            'status': ItemStatus.INBOX,
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Verify item was created normally
        item = Item.objects.latest('created_at')
        self.assertEqual(item.title, 'Manual Title')
        self.assertEqual(item.description, 'Manual description')
    
    def test_blueprint_detail_page_has_create_button(self):
        """Test that blueprint detail page includes create issue button"""
        url = reverse('blueprint-detail', args=[self.blueprint.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create Issue from Blueprint')
        self.assertContains(response, 'createIssueModal')
    
    def test_apply_blueprint_modal_has_variable_support(self):
        """Test that apply blueprint modal handles variables"""
        # Create an item first
        item = Item.objects.create(
            project=self.project,
            title="Test Item",
            description="Test",
            type=self.item_type
        )
        
        url = reverse('item-apply-blueprint', args=[item.id])
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'variables-container')
        # Check for variable extraction logic in JavaScript
        self.assertContains(response, 'variablePattern')
    
    def test_apply_blueprint_with_title_variables_only(self):
        """Test applying blueprint with variables only in title"""
        # Create blueprint with variable only in title
        blueprint = IssueBlueprint.objects.create(
            title="Error in {{ entity }}",
            category=self.category,
            description_md="This is a plain description without variables.",
            is_active=True,
            created_by=self.user
        )
        
        item = Item.objects.create(
            project=self.project,
            title="Original Title",
            description="Original description",
            type=self.item_type
        )
        
        url = reverse('item-apply-blueprint-submit', args=[item.id])
        
        variables = {
            'entity': 'Database'
        }
        
        response = self.client.post(url, {
            'blueprint_id': str(blueprint.id),
            'variables': json.dumps(variables),
            'use_blueprint_title': 'on'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Reload item and verify title was replaced
        item.refresh_from_db()
        self.assertEqual(item.title, 'Error in Database')
        self.assertNotIn('{{', item.title)
    
    def test_apply_blueprint_with_title_and_description_variables(self):
        """Test applying blueprint with variables in both title and description"""
        # Create blueprint with variables in both title and description
        blueprint = IssueBlueprint.objects.create(
            title="Error in {{ entity }}",
            category=self.category,
            description_md="Please check {{ entity }} in {{ environment }}. {{ entity }} occurs multiple times.",
            is_active=True,
            created_by=self.user
        )
        
        item = Item.objects.create(
            project=self.project,
            title="Original Title",
            description="Original description",
            type=self.item_type
        )
        
        url = reverse('item-apply-blueprint-submit', args=[item.id])
        
        variables = {
            'entity': 'Database',
            'environment': 'Production'
        }
        
        response = self.client.post(url, {
            'blueprint_id': str(blueprint.id),
            'variables': json.dumps(variables),
            'use_blueprint_title': 'on',
            'replace_description': 'on'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Reload item and verify both title and description were replaced
        item.refresh_from_db()
        self.assertEqual(item.title, 'Error in Database')
        self.assertIn('Please check Database in Production', item.description)
        # Verify all occurrences were replaced
        self.assertEqual(item.description.count('Database'), 2)
        self.assertNotIn('{{', item.title)
        self.assertNotIn('{{', item.description)
    
    def test_apply_blueprint_missing_title_variable(self):
        """Test that missing title variables are caught in validation"""
        # Create blueprint with variable in title
        blueprint = IssueBlueprint.objects.create(
            title="Error in {{ entity }}",
            category=self.category,
            description_md="Some description",
            is_active=True,
            created_by=self.user
        )
        
        item = Item.objects.create(
            project=self.project,
            title="Original Title",
            description="Original description",
            type=self.item_type
        )
        
        url = reverse('item-apply-blueprint-submit', args=[item.id])
        
        # Don't provide the entity variable
        response = self.client.post(url, {
            'blueprint_id': str(blueprint.id),
            'variables': json.dumps({})
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Missing required variables', data['error'])
        self.assertIn('entity', data['error'])
    
    def test_create_issue_with_title_variables(self):
        """Test creating issue from blueprint with title variables"""
        # Create blueprint with variables in title
        blueprint = IssueBlueprint.objects.create(
            title="{{ feature_name }} Implementation",
            category=self.category,
            description_md="Implement {{ feature_name }} with {{ technology }}",
            is_active=True,
            created_by=self.user
        )
        
        url = reverse('blueprint-create-issue', args=[blueprint.id])
        
        variables = {
            'feature_name': 'Authentication',
            'technology': 'OAuth2'
        }
        
        response = self.client.post(url, {
            'project_id': self.project.id,
            'variables': json.dumps(variables)
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify the item was created with replaced variables in both title and description
        item = Item.objects.latest('created_at')
        self.assertEqual(item.title, 'Authentication Implementation')
        self.assertIn('Implement Authentication with OAuth2', item.description)
        self.assertNotIn('{{', item.title)
        self.assertNotIn('{{', item.description)
