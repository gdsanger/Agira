"""
Tests for GlobalSettings views and model
"""

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import GlobalSettings
import os

User = get_user_model()


class GlobalSettingsModelTestCase(TestCase):
    """Test cases for GlobalSettings model"""
    
    def setUp(self):
        """Set up test data"""
        # Clear any existing settings
        GlobalSettings.objects.all().delete()
    
    def test_singleton_creation(self):
        """Test that only one GlobalSettings instance can exist"""
        # Create first instance
        settings1 = GlobalSettings.objects.create(
            company_name='Test Company',
            email='test@example.com',
            address='123 Test St',
            base_url='https://test.com'
        )
        
        # Try to create a second instance - should raise ValidationError
        with self.assertRaises(ValidationError):
            settings2 = GlobalSettings(
                company_name='Another Company',
                email='another@example.com',
                address='456 Another St',
                base_url='https://another.com'
            )
            settings2.save()
    
    def test_get_instance_creates_if_not_exists(self):
        """Test that get_instance creates settings if they don't exist"""
        # Ensure no settings exist
        self.assertEqual(GlobalSettings.objects.count(), 0)
        
        # Get instance
        settings = GlobalSettings.get_instance()
        
        # Should now exist with defaults
        self.assertIsNotNone(settings)
        self.assertEqual(settings.company_name, 'Your Company Name')
        self.assertEqual(settings.email, 'company@example.com')
        self.assertEqual(GlobalSettings.objects.count(), 1)
    
    def test_get_instance_returns_existing(self):
        """Test that get_instance returns existing settings"""
        # Create settings
        settings1 = GlobalSettings.objects.create(
            company_name='My Company',
            email='my@example.com',
            address='789 My St',
            base_url='https://my.com'
        )
        
        # Get instance
        settings2 = GlobalSettings.get_instance()
        
        # Should be the same instance
        self.assertEqual(settings1.id, settings2.id)
        self.assertEqual(settings2.company_name, 'My Company')
    
    def test_default_values(self):
        """Test that default values are set correctly"""
        settings = GlobalSettings.get_instance()
        
        self.assertEqual(settings.company_name, 'Your Company Name')
        self.assertEqual(settings.email, 'company@example.com')
        self.assertIn('Street Address', settings.address)
        self.assertEqual(settings.base_url, 'https://example.com')
    
    def test_email_validation(self):
        """Test email field validation"""
        settings = GlobalSettings.get_instance()
        settings.email = 'invalid-email'
        
        with self.assertRaises(ValidationError):
            settings.full_clean()
    
    def test_url_validation(self):
        """Test base_url field validation"""
        settings = GlobalSettings.get_instance()
        settings.base_url = 'not-a-url'
        
        with self.assertRaises(ValidationError):
            settings.full_clean()


class GlobalSettingsViewsTestCase(TestCase):
    """Test cases for GlobalSettings views"""
    
    def setUp(self):
        """Set up test data"""
        # Clear any existing settings
        GlobalSettings.objects.all().delete()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        # Set up client
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def test_global_settings_detail_view_requires_login(self):
        """Test that detail view requires authentication"""
        self.client.logout()
        response = self.client.get(reverse('global-settings'))
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
    
    def test_global_settings_detail_view(self):
        """Test global settings detail view"""
        response = self.client.get(reverse('global-settings'))
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Global Settings')
        self.assertContains(response, 'company_name')
        self.assertContains(response, 'email')
        self.assertContains(response, 'address')
        self.assertContains(response, 'base_url')
    
    def test_global_settings_detail_view_creates_instance(self):
        """Test that detail view creates settings if they don't exist"""
        # Ensure no settings exist
        self.assertEqual(GlobalSettings.objects.count(), 0)
        
        response = self.client.get(reverse('global-settings'))
        
        self.assertEqual(response.status_code, 200)
        # Should have created an instance
        self.assertEqual(GlobalSettings.objects.count(), 1)
    
    def test_global_settings_update(self):
        """Test updating global settings"""
        settings = GlobalSettings.get_instance()
        
        response = self.client.post(reverse('global-settings-update'), {
            'company_name': 'Updated Company',
            'email': 'updated@example.com',
            'address': 'Updated Address\n12345 City\nCountry',
            'base_url': 'https://updated.com'
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Reload settings from database
        settings.refresh_from_db()
        self.assertEqual(settings.company_name, 'Updated Company')
        self.assertEqual(settings.email, 'updated@example.com')
        self.assertEqual(settings.base_url, 'https://updated.com')
    
    def test_global_settings_update_invalid_email(self):
        """Test updating with invalid email"""
        GlobalSettings.get_instance()
        
        response = self.client.post(reverse('global-settings-update'), {
            'company_name': 'Test Company',
            'email': 'invalid-email',
            'address': 'Test Address',
            'base_url': 'https://test.com'
        })
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('Validation error', response.content.decode())
    
    def test_global_settings_update_invalid_url(self):
        """Test updating with invalid URL"""
        GlobalSettings.get_instance()
        
        response = self.client.post(reverse('global-settings-update'), {
            'company_name': 'Test Company',
            'email': 'test@example.com',
            'address': 'Test Address',
            'base_url': 'not-a-url'
        })
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('Validation error', response.content.decode())
    
    def test_global_settings_logo_upload(self):
        """Test uploading a logo"""
        GlobalSettings.get_instance()
        
        # Create a simple test image
        image_content = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        test_image = SimpleUploadedFile(
            'test_logo.gif',
            image_content,
            content_type='image/gif'
        )
        
        response = self.client.post(reverse('global-settings-update'), {
            'company_name': 'Test Company',
            'email': 'test@example.com',
            'address': 'Test Address',
            'base_url': 'https://test.com',
            'logo': test_image
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Reload settings
        settings = GlobalSettings.get_instance()
        self.assertTrue(settings.logo)
        
        # Clean up
        if settings.logo:
            settings.logo.delete()
    
    def test_global_settings_logo_upload_only(self):
        """Test uploading a logo without changing other fields (empty strings)"""
        # First, set up initial settings with known values
        settings = GlobalSettings.get_instance()
        settings.company_name = 'Initial Company'
        settings.email = 'initial@example.com'
        settings.address = 'Initial Address\nCity\nCountry'
        settings.base_url = 'https://initial.com'
        settings.save()
        
        # Create a test image
        image_content = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        test_image = SimpleUploadedFile(
            'test_logo.gif',
            image_content,
            content_type='image/gif'
        )
        
        # Upload logo with empty strings for other fields (simulating what htmx might send)
        response = self.client.post(reverse('global-settings-update'), {
            'company_name': '',
            'email': '',
            'address': '',
            'base_url': '',
            'logo': test_image
        })
        
        # Should succeed (not return 400)
        self.assertEqual(response.status_code, 200)
        
        # Reload settings
        settings.refresh_from_db()
        
        # Logo should be uploaded
        self.assertTrue(settings.logo)
        
        # Other fields should NOT be changed (should still have initial values)
        self.assertEqual(settings.company_name, 'Initial Company')
        self.assertEqual(settings.email, 'initial@example.com')
        self.assertEqual(settings.address, 'Initial Address\nCity\nCountry')
        self.assertEqual(settings.base_url, 'https://initial.com')
        
        # Clean up
        if settings.logo:
            settings.logo.delete()
    
    def test_global_settings_update_without_logo(self):
        """Test updating settings without uploading a logo"""
        settings = GlobalSettings.get_instance()
        
        # First upload a logo
        image_content = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        test_image = SimpleUploadedFile(
            'test_logo.gif',
            image_content,
            content_type='image/gif'
        )
        settings.logo = test_image
        settings.company_name = 'Company With Logo'
        settings.save()
        
        logo_name = settings.logo.name
        
        # Now update other fields without changing the logo
        response = self.client.post(reverse('global-settings-update'), {
            'company_name': 'Updated Company',
            'email': 'updated@example.com',
            'address': 'Updated Address',
            'base_url': 'https://updated.com'
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Reload settings
        settings.refresh_from_db()
        
        # Fields should be updated
        self.assertEqual(settings.company_name, 'Updated Company')
        self.assertEqual(settings.email, 'updated@example.com')
        
        # Logo should still exist and be unchanged
        self.assertTrue(settings.logo)
        self.assertEqual(settings.logo.name, logo_name)
        
        # Clean up
        if settings.logo:
            settings.logo.delete()


class PublicLogoViewTestCase(TestCase):
    """Test cases for public logo endpoint"""
    
    def setUp(self):
        """Set up test data"""
        # Clear any existing settings
        GlobalSettings.objects.all().delete()
        
        # Create client (no login required for public endpoint)
        self.client = Client()
    
    def test_public_logo_no_auth_required(self):
        """Test that public logo endpoint doesn't require authentication"""
        # Create settings with logo
        settings = GlobalSettings.get_instance()
        
        # Create a test image
        image_content = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        test_image = SimpleUploadedFile(
            'logo.gif',
            image_content,
            content_type='image/gif'
        )
        settings.logo = test_image
        settings.save()
        
        # Access public logo without authentication
        response = self.client.get(reverse('public-logo'))
        
        # Should return the logo (200) or 404 if no logo
        self.assertIn(response.status_code, [200, 404])
        
        # Clean up
        if settings.logo:
            settings.logo.delete()
    
    def test_public_logo_404_when_no_logo(self):
        """Test that 404 is returned when no logo exists"""
        GlobalSettings.get_instance()
        
        response = self.client.get(reverse('public-logo'))
        
        self.assertEqual(response.status_code, 404)


class GlobalSettingsIntegrationTestCase(TestCase):
    """Integration tests for the complete Global Settings workflow"""
    
    def setUp(self):
        """Set up test data"""
        # Clear any existing settings
        GlobalSettings.objects.all().delete()
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass123',
            email='test@example.com'
        )
        
        # Set up client
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')
    
    def test_complete_logo_upload_workflow(self):
        """Test the complete workflow: initial setup -> logo upload -> public access"""
        # Step 1: Get initial settings page
        response = self.client.get(reverse('global-settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Global Settings')
        
        # Step 2: Set up initial settings
        settings = GlobalSettings.get_instance()
        settings.company_name = 'Test Company Inc.'
        settings.email = 'contact@testcompany.com'
        settings.address = '123 Test Street\n12345 Test City\nTest Country'
        settings.base_url = 'https://testcompany.com'
        settings.save()
        
        # Step 3: Upload a logo (simulating the form submission with empty other fields)
        image_content = b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        test_image = SimpleUploadedFile(
            'company_logo.gif',
            image_content,
            content_type='image/gif'
        )
        
        response = self.client.post(reverse('global-settings-update'), {
            'company_name': '',  # Empty - should keep existing
            'email': '',  # Empty - should keep existing
            'address': '',  # Empty - should keep existing
            'base_url': '',  # Empty - should keep existing
            'logo': test_image
        })
        
        # Should succeed
        self.assertEqual(response.status_code, 200)
        self.assertIn('HX-Trigger', response)
        
        # Step 4: Verify settings were preserved and logo was uploaded
        settings.refresh_from_db()
        self.assertEqual(settings.company_name, 'Test Company Inc.')
        self.assertEqual(settings.email, 'contact@testcompany.com')
        self.assertTrue(settings.logo)
        self.assertIn('company_logo', settings.logo.name)
        
        # Step 5: Verify public logo endpoint works without authentication
        self.client.logout()
        response = self.client.get(reverse('public-logo'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/gif')
        
        # Step 6: Verify detail view shows the logo
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('global-settings'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, settings.logo.url)
        
        # Clean up
        if settings.logo:
            settings.logo.delete()
