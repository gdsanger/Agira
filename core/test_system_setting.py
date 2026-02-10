"""
Test SystemSetting model and views
"""
from django.test import TestCase, Client
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from core.models import SystemSetting, Organisation, UserOrganisation

User = get_user_model()


class SystemSettingModelTest(TestCase):
    """Test SystemSetting model"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Clean up any existing instances
        SystemSetting.objects.all().delete()
    
    def test_singleton_pattern(self):
        """Test that only one SystemSetting instance can exist"""
        # Create first instance
        setting1 = SystemSetting.objects.create(
            system_name="Test System 1",
            company="Test Company 1",
            email="test1@example.com"
        )
        self.assertIsNotNone(setting1)
        
        # Try to create another instance - should raise ValidationError
        with self.assertRaises(ValidationError):
            SystemSetting.objects.create(
                system_name="Test System 2",
                company="Test Company 2",
                email="test2@example.com"
            )
    
    def test_get_instance(self):
        """Test get_instance class method"""
        # First call should create the instance with defaults
        instance = SystemSetting.get_instance()
        self.assertEqual(instance.system_name, "Agira Issue Tracking v1.0")
        self.assertEqual(instance.company, "Agira Software Enterprises")
        self.assertEqual(instance.email, "agira@angermeier.net")
        
        # Second call should return the same instance
        instance2 = SystemSetting.get_instance()
        self.assertEqual(instance.id, instance2.id)
    
    def test_default_values(self):
        """Test that default values are set correctly"""
        setting = SystemSetting.get_instance()
        self.assertEqual(setting.system_name, "Agira Issue Tracking v1.0")
        self.assertEqual(setting.company, "Agira Software Enterprises")
        self.assertEqual(setting.email, "agira@angermeier.net")
        self.assertFalse(setting.company_logo)  # Should be blank/null
    
    def test_delete_prevention(self):
        """Test that SystemSetting cannot be deleted"""
        setting = SystemSetting.get_instance()
        setting_id = setting.id
        
        # Try to delete - should do nothing
        setting.delete()
        
        # Instance should still exist
        self.assertTrue(SystemSetting.objects.filter(id=setting_id).exists())
    
    def test_str_method(self):
        """Test string representation"""
        setting = SystemSetting.get_instance()
        expected = f"System Settings - {setting.system_name}"
        self.assertEqual(str(setting), expected)


class SystemSettingViewTest(TestCase):
    """Test SystemSetting views"""
    
    def setUp(self):
        """Set up test fixtures"""
        # Clean up any existing instances
        SystemSetting.objects.all().delete()
        
        # Create test user
        self.org = Organisation.objects.create(name="Test Org", short="TO")
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        UserOrganisation.objects.create(
            user=self.user,
            organisation=self.org
        )
        self.client = Client()
        self.client.login(username="testuser", password="testpass123")
    
    def test_detail_view_accessible(self):
        """Test that the detail view is accessible"""
        response = self.client.get(reverse('system-setting'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'system_setting_detail.html')
    
    def test_detail_view_shows_default_values(self):
        """Test that the detail view shows default values"""
        response = self.client.get(reverse('system-setting'))
        self.assertContains(response, "Agira Issue Tracking v1.0")
        self.assertContains(response, "Agira Software Enterprises")
        self.assertContains(response, "agira@angermeier.net")
    
    def test_update_view_success(self):
        """Test successful update"""
        response = self.client.post(
            reverse('system-setting-update'),
            {
                'system_name': 'Updated System Name',
                'company': 'Updated Company',
                'email': 'updated@example.com'
            },
            HTTP_HX_REQUEST='true'
        )
        self.assertEqual(response.status_code, 200)
        
        # Verify the update
        setting = SystemSetting.get_instance()
        self.assertEqual(setting.system_name, 'Updated System Name')
        self.assertEqual(setting.company, 'Updated Company')
        self.assertEqual(setting.email, 'updated@example.com')
    
    def test_update_view_requires_login(self):
        """Test that update view requires authentication"""
        self.client.logout()
        response = self.client.post(
            reverse('system-setting-update'),
            {'system_name': 'Test'}
        )
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
    
    def test_update_view_invalid_email(self):
        """Test update with invalid email"""
        response = self.client.post(
            reverse('system-setting-update'),
            {
                'system_name': 'Test',
                'company': 'Test Company',
                'email': 'invalid-email'
            },
            HTTP_HX_REQUEST='true'
        )
        # Should return error
        self.assertEqual(response.status_code, 400)
