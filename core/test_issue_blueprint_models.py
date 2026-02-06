"""
Tests for IssueBlueprint and IssueBlueprintCategory models
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from core.models import (
    IssueBlueprint, IssueBlueprintCategory, User, RiskLevel
)


class IssueBlueprintCategoryTestCase(TestCase):
    """Test cases for IssueBlueprintCategory model"""
    
    def test_create_category(self):
        """Test creating a blueprint category"""
        category = IssueBlueprintCategory.objects.create(
            name="Security Features",
            slug="security-features"
        )
        
        self.assertIsNotNone(category.id)
        self.assertEqual(category.name, "Security Features")
        self.assertEqual(category.slug, "security-features")
        self.assertTrue(category.is_active)
        self.assertIsNotNone(category.created_at)
        self.assertIsNotNone(category.updated_at)
    
    def test_category_str_representation(self):
        """Test string representation of category"""
        category = IssueBlueprintCategory.objects.create(
            name="Test Category",
            slug="test-category"
        )
        self.assertEqual(str(category), "Test Category")
    
    def test_category_default_is_active(self):
        """Test that is_active defaults to True"""
        category = IssueBlueprintCategory.objects.create(
            name="Test",
            slug="test"
        )
        self.assertTrue(category.is_active)
    
    def test_category_unique_name(self):
        """Test that category name must be unique"""
        IssueBlueprintCategory.objects.create(
            name="Duplicate",
            slug="duplicate-1"
        )
        
        with self.assertRaises(IntegrityError):
            IssueBlueprintCategory.objects.create(
                name="Duplicate",
                slug="duplicate-2"
            )
    
    def test_category_unique_slug(self):
        """Test that category slug must be unique"""
        IssueBlueprintCategory.objects.create(
            name="First",
            slug="same-slug"
        )
        
        with self.assertRaises(IntegrityError):
            IssueBlueprintCategory.objects.create(
                name="Second",
                slug="same-slug"
            )


class IssueBlueprintTestCase(TestCase):
    """Test cases for IssueBlueprint model"""
    
    def setUp(self):
        """Set up test data"""
        self.category = IssueBlueprintCategory.objects.create(
            name="Features",
            slug="features"
        )
        
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            name="Test User"
        )
    
    def test_create_blueprint_minimal(self):
        """Test creating a blueprint with only required fields"""
        blueprint = IssueBlueprint.objects.create(
            title="User Authentication",
            category=self.category,
            description_md="# Authentication\n\nImplement user authentication.\n\n## Acceptance Criteria\n- Users can log in"
        )
        
        self.assertIsNotNone(blueprint.id)
        self.assertEqual(blueprint.title, "User Authentication")
        self.assertEqual(blueprint.category, self.category)
        self.assertTrue(blueprint.is_active)
        self.assertEqual(blueprint.version, 1)
        self.assertIsNotNone(blueprint.created_at)
        self.assertIsNotNone(blueprint.updated_at)
    
    def test_create_blueprint_with_all_fields(self):
        """Test creating a blueprint with all fields"""
        blueprint = IssueBlueprint.objects.create(
            title="API Rate Limiting",
            category=self.category,
            description_md="# Rate Limiting\n\nImplement API rate limiting.",
            tags=["security", "api", "performance"],
            default_labels=["backend", "security"],
            default_risk_level=RiskLevel.HIGH,
            default_security_relevant=True,
            notes="This is a critical security feature",
            created_by=self.user,
            version=2
        )
        
        self.assertEqual(blueprint.title, "API Rate Limiting")
        self.assertEqual(blueprint.tags, ["security", "api", "performance"])
        self.assertEqual(blueprint.default_labels, ["backend", "security"])
        self.assertEqual(blueprint.default_risk_level, RiskLevel.HIGH)
        self.assertTrue(blueprint.default_security_relevant)
        self.assertEqual(blueprint.notes, "This is a critical security feature")
        self.assertEqual(blueprint.created_by, self.user)
        self.assertEqual(blueprint.version, 2)
    
    def test_blueprint_str_representation(self):
        """Test string representation of blueprint"""
        blueprint = IssueBlueprint.objects.create(
            title="Test Blueprint",
            category=self.category,
            description_md="Test description",
            version=3
        )
        self.assertEqual(str(blueprint), "Test Blueprint (v3)")
    
    def test_blueprint_default_values(self):
        """Test default values for blueprint"""
        blueprint = IssueBlueprint.objects.create(
            title="Test",
            category=self.category,
            description_md="Test"
        )
        
        self.assertTrue(blueprint.is_active)
        self.assertEqual(blueprint.version, 1)
        self.assertIsNone(blueprint.tags)
        self.assertIsNone(blueprint.default_labels)
        self.assertIsNone(blueprint.default_risk_level)
        self.assertIsNone(blueprint.default_security_relevant)
        self.assertEqual(blueprint.notes, "")
        self.assertIsNone(blueprint.created_by)
    
    def test_category_fk_protection(self):
        """Test that category cannot be deleted when blueprints reference it"""
        blueprint = IssueBlueprint.objects.create(
            title="Test",
            category=self.category,
            description_md="Test"
        )
        
        # Try to delete category - should raise error due to PROTECT
        from django.db.models import ProtectedError
        with self.assertRaises(ProtectedError):
            self.category.delete()
        
        # Verify blueprint still exists
        self.assertTrue(IssueBlueprint.objects.filter(id=blueprint.id).exists())
    
    def test_created_by_set_null_on_user_delete(self):
        """Test that created_by is set to null when user is deleted"""
        blueprint = IssueBlueprint.objects.create(
            title="Test",
            category=self.category,
            description_md="Test",
            created_by=self.user
        )
        
        # Delete user
        self.user.delete()
        
        # Reload blueprint
        blueprint.refresh_from_db()
        self.assertIsNone(blueprint.created_by)
    
    def test_blueprint_title_not_unique(self):
        """Test that blueprint title does NOT need to be unique"""
        IssueBlueprint.objects.create(
            title="Same Title",
            category=self.category,
            description_md="First"
        )
        
        # Should be able to create another with same title
        blueprint2 = IssueBlueprint.objects.create(
            title="Same Title",
            category=self.category,
            description_md="Second"
        )
        
        self.assertEqual(blueprint2.title, "Same Title")
        self.assertEqual(IssueBlueprint.objects.filter(title="Same Title").count(), 2)
    
    def test_risk_level_choices(self):
        """Test that only valid risk levels can be used"""
        # Valid risk level
        blueprint = IssueBlueprint.objects.create(
            title="Test",
            category=self.category,
            description_md="Test",
            default_risk_level=RiskLevel.VERY_HIGH
        )
        self.assertEqual(blueprint.default_risk_level, RiskLevel.VERY_HIGH)
    
    def test_json_fields(self):
        """Test JSON field functionality"""
        blueprint = IssueBlueprint.objects.create(
            title="Test",
            category=self.category,
            description_md="Test",
            tags=["tag1", "tag2", "tag3"],
            default_labels=["label1", "label2"]
        )
        
        # Verify JSON fields work correctly
        self.assertEqual(len(blueprint.tags), 3)
        self.assertEqual(len(blueprint.default_labels), 2)
        self.assertIn("tag2", blueprint.tags)
        self.assertIn("label1", blueprint.default_labels)
    
    def test_is_active_filtering(self):
        """Test filtering blueprints by is_active"""
        active = IssueBlueprint.objects.create(
            title="Active",
            category=self.category,
            description_md="Active",
            is_active=True
        )
        
        inactive = IssueBlueprint.objects.create(
            title="Inactive",
            category=self.category,
            description_md="Inactive",
            is_active=False
        )
        
        active_blueprints = IssueBlueprint.objects.filter(is_active=True)
        self.assertEqual(active_blueprints.count(), 1)
        self.assertEqual(active_blueprints.first(), active)
        
        inactive_blueprints = IssueBlueprint.objects.filter(is_active=False)
        self.assertEqual(inactive_blueprints.count(), 1)
        self.assertEqual(inactive_blueprints.first(), inactive)
