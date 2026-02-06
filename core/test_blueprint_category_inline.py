"""
Tests for inline blueprint category creation
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

from core.models import IssueBlueprintCategory

User = get_user_model()


class BlueprintCategoryInlineCreateTestCase(TestCase):
    """Test cases for inline category creation endpoint"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123",
            name="Test User"
        )
        self.client.login(username="testuser", password="testpass123")
        self.url = reverse('blueprint-category-create-inline')
    
    def test_create_category_success(self):
        """Test successfully creating a category"""
        response = self.client.post(self.url, {
            'name': 'New Category'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertIn('message', data)
        self.assertIn('category', data)
        self.assertEqual(data['category']['name'], 'New Category')
        self.assertEqual(data['category']['slug'], 'new-category')
        
        # Verify category was created in database
        category = IssueBlueprintCategory.objects.get(name='New Category')
        self.assertEqual(category.slug, 'new-category')
        self.assertTrue(category.is_active)
    
    def test_create_category_with_special_characters(self):
        """Test creating category with special characters in name"""
        response = self.client.post(self.url, {
            'name': 'Test & Special Characters!'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        self.assertEqual(data['category']['name'], 'Test & Special Characters!')
        # Slug should be sanitized
        self.assertEqual(data['category']['slug'], 'test-special-characters')
    
    def test_create_category_duplicate_name(self):
        """Test that duplicate category name fails"""
        # Create first category
        IssueBlueprintCategory.objects.create(
            name='Duplicate',
            slug='duplicate'
        )
        
        # Try to create another with same name
        response = self.client.post(self.url, {
            'name': 'Duplicate'
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        
        self.assertFalse(data['success'])
        self.assertIn('error', data)
        self.assertIn('already exists', data['error'].lower())
        
        # Verify only one category with that name exists
        self.assertEqual(IssueBlueprintCategory.objects.filter(name='Duplicate').count(), 1)
    
    def test_create_category_slug_auto_increment(self):
        """Test that slug is auto-incremented if duplicate"""
        # Create first category
        IssueBlueprintCategory.objects.create(
            name='Test',
            slug='test-category'
        )
        
        # Create another with name that would generate same slug
        response = self.client.post(self.url, {
            'name': 'Test Category'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertTrue(data['success'])
        # Slug should be incremented
        self.assertEqual(data['category']['slug'], 'test-category-1')
    
    def test_create_category_missing_name(self):
        """Test that missing name returns error"""
        response = self.client.post(self.url, {
            'name': ''
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        
        self.assertFalse(data['success'])
        self.assertIn('error', data)
        self.assertIn('required', data['error'].lower())
    
    def test_create_category_whitespace_name(self):
        """Test that whitespace-only name is treated as empty"""
        response = self.client.post(self.url, {
            'name': '   '
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        
        self.assertFalse(data['success'])
        self.assertIn('required', data['error'].lower())
    
    def test_create_category_requires_authentication(self):
        """Test that endpoint requires authentication"""
        # Logout
        self.client.logout()
        
        response = self.client.post(self.url, {
            'name': 'Test Category'
        })
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
    
    def test_create_category_requires_post(self):
        """Test that only POST method is allowed"""
        response = self.client.get(self.url)
        
        # Should return method not allowed
        self.assertEqual(response.status_code, 405)
    
    def test_category_response_format(self):
        """Test that response has correct format"""
        response = self.client.post(self.url, {
            'name': 'Format Test'
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check response structure
        self.assertIn('success', data)
        self.assertIn('message', data)
        self.assertIn('category', data)
        
        category_data = data['category']
        self.assertIn('id', category_data)
        self.assertIn('name', category_data)
        self.assertIn('slug', category_data)
