"""
Tests for Blueprint Import/Export functionality
"""

import json
from django.test import TestCase, Client
from django.urls import reverse

from core.models import IssueBlueprint, IssueBlueprintCategory, User, RiskLevel
from core.utils.blueprint_serializer import (
    export_blueprint,
    export_blueprint_json,
    import_blueprint,
    import_blueprint_json,
    BlueprintSerializationError,
    BlueprintDeserializationError,
    CURRENT_SCHEMA_VERSION,
)


class BlueprintExportTestCase(TestCase):
    """Test cases for blueprint export functionality"""
    
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
        
        self.blueprint = IssueBlueprint.objects.create(
            title="Test Blueprint",
            category=self.category,
            description_md="# Test Description\n\nThis is a test.",
            is_active=True,
            version=1,
            tags=["tag1", "tag2"],
            default_labels=["label1"],
            default_risk_level=RiskLevel.HIGH,
            default_security_relevant=True,
            notes="Test notes",
            created_by=self.user
        )
    
    def test_export_blueprint_structure(self):
        """Test that export produces correct structure"""
        data = export_blueprint(self.blueprint)
        
        # Check top-level structure
        self.assertIn('schema_version', data)
        self.assertIn('blueprint', data)
        self.assertEqual(data['schema_version'], CURRENT_SCHEMA_VERSION)
        
        # Check blueprint data
        blueprint_data = data['blueprint']
        self.assertEqual(blueprint_data['title'], 'Test Blueprint')
        self.assertEqual(blueprint_data['description_md'], '# Test Description\n\nThis is a test.')
        self.assertEqual(blueprint_data['is_active'], True)
        self.assertEqual(blueprint_data['version'], 1)
        self.assertEqual(blueprint_data['tags'], ['tag1', 'tag2'])
        self.assertEqual(blueprint_data['default_labels'], ['label1'])
        self.assertEqual(blueprint_data['default_risk_level'], RiskLevel.HIGH)
        self.assertEqual(blueprint_data['default_security_relevant'], True)
        self.assertEqual(blueprint_data['notes'], 'Test notes')
        
        # Check category data
        self.assertIn('category', blueprint_data)
        self.assertEqual(blueprint_data['category']['name'], 'Features')
        self.assertEqual(blueprint_data['category']['slug'], 'features')
    
    def test_export_blueprint_json_format(self):
        """Test that export produces valid JSON"""
        json_str = export_blueprint_json(self.blueprint)
        
        # Should be valid JSON
        data = json.loads(json_str)
        
        # Should have proper structure
        self.assertIn('schema_version', data)
        self.assertIn('blueprint', data)
    
    def test_export_blueprint_minimal(self):
        """Test exporting blueprint with only required fields"""
        minimal_blueprint = IssueBlueprint.objects.create(
            title="Minimal Blueprint",
            category=self.category,
            description_md="Minimal description"
        )
        
        data = export_blueprint(minimal_blueprint)
        blueprint_data = data['blueprint']
        
        self.assertEqual(blueprint_data['title'], 'Minimal Blueprint')
        self.assertEqual(blueprint_data['description_md'], 'Minimal description')
        self.assertIsNone(blueprint_data['tags'])
        self.assertIsNone(blueprint_data['default_labels'])
        self.assertIsNone(blueprint_data['default_risk_level'])
        self.assertIsNone(blueprint_data['default_security_relevant'])
    
    def test_export_deterministic(self):
        """Test that export is deterministic (same input = same output)"""
        json1 = export_blueprint_json(self.blueprint)
        json2 = export_blueprint_json(self.blueprint)
        
        self.assertEqual(json1, json2)


class BlueprintImportTestCase(TestCase):
    """Test cases for blueprint import functionality"""
    
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
    
    def test_import_blueprint_basic(self):
        """Test basic blueprint import"""
        data = {
            "schema_version": "1.0",
            "blueprint": {
                "title": "Imported Blueprint",
                "description_md": "# Imported Description",
                "category": {
                    "name": "Features",
                    "slug": "features"
                },
                "is_active": True,
                "version": 1
            }
        }
        
        blueprint, created = import_blueprint(data, created_by=self.user)
        
        self.assertTrue(created)
        self.assertEqual(blueprint.title, "Imported Blueprint")
        self.assertEqual(blueprint.description_md, "# Imported Description")
        self.assertEqual(blueprint.category, self.category)
        self.assertEqual(blueprint.created_by, self.user)
    
    def test_import_blueprint_with_all_fields(self):
        """Test importing blueprint with all optional fields"""
        data = {
            "schema_version": "1.0",
            "blueprint": {
                "title": "Full Blueprint",
                "description_md": "# Full Description",
                "category": {
                    "name": "Features",
                    "slug": "features"
                },
                "is_active": True,
                "version": 2,
                "tags": ["tag1", "tag2"],
                "default_labels": ["label1"],
                "default_risk_level": RiskLevel.VERY_HIGH,
                "default_security_relevant": False,
                "notes": "Import notes"
            }
        }
        
        blueprint, created = import_blueprint(data)
        
        self.assertTrue(created)
        self.assertEqual(blueprint.title, "Full Blueprint")
        self.assertEqual(blueprint.version, 2)
        self.assertEqual(blueprint.tags, ["tag1", "tag2"])
        self.assertEqual(blueprint.default_labels, ["label1"])
        self.assertEqual(blueprint.default_risk_level, RiskLevel.VERY_HIGH)
        self.assertFalse(blueprint.default_security_relevant)
        self.assertEqual(blueprint.notes, "Import notes")
    
    def test_import_creates_missing_category(self):
        """Test that import creates category if it doesn't exist"""
        data = {
            "schema_version": "1.0",
            "blueprint": {
                "title": "Blueprint with New Category",
                "description_md": "# Description",
                "category": {
                    "name": "New Category",
                    "slug": "new-category"
                },
                "is_active": True,
                "version": 1
            }
        }
        
        # Category doesn't exist yet
        self.assertFalse(IssueBlueprintCategory.objects.filter(slug="new-category").exists())
        
        blueprint, created = import_blueprint(data)
        
        self.assertTrue(created)
        # Category should now exist
        self.assertTrue(IssueBlueprintCategory.objects.filter(slug="new-category").exists())
        new_category = IssueBlueprintCategory.objects.get(slug="new-category")
        self.assertEqual(new_category.name, "New Category")
        self.assertEqual(blueprint.category, new_category)
    
    def test_import_with_unknown_fields(self):
        """Test that import ignores unknown fields"""
        data = {
            "schema_version": "1.0",
            "blueprint": {
                "title": "Blueprint with Unknown Fields",
                "description_md": "# Description",
                "category": {
                    "name": "Features",
                    "slug": "features"
                },
                "is_active": True,
                "version": 1,
                "unknown_field_1": "This should be ignored",
                "unknown_field_2": 12345
            }
        }
        
        # Should not raise an error
        blueprint, created = import_blueprint(data)
        
        self.assertTrue(created)
        self.assertEqual(blueprint.title, "Blueprint with Unknown Fields")
    
    def test_import_missing_required_fields(self):
        """Test that import fails with missing required fields"""
        # Missing title
        data = {
            "schema_version": "1.0",
            "blueprint": {
                "description_md": "# Description",
                "category": {
                    "name": "Features",
                    "slug": "features"
                }
            }
        }
        
        with self.assertRaises(BlueprintDeserializationError) as cm:
            import_blueprint(data)
        
        self.assertIn("title", str(cm.exception))
    
    def test_import_missing_schema_version(self):
        """Test that import fails without schema_version"""
        data = {
            "blueprint": {
                "title": "Test",
                "description_md": "# Description",
                "category": {
                    "name": "Features",
                    "slug": "features"
                }
            }
        }
        
        with self.assertRaises(BlueprintDeserializationError) as cm:
            import_blueprint(data)
        
        self.assertIn("schema_version", str(cm.exception))
    
    def test_import_unsupported_schema_version(self):
        """Test that import fails with unsupported schema version"""
        data = {
            "schema_version": "99.0",
            "blueprint": {
                "title": "Test",
                "description_md": "# Description",
                "category": {
                    "name": "Features",
                    "slug": "features"
                }
            }
        }
        
        with self.assertRaises(BlueprintDeserializationError) as cm:
            import_blueprint(data)
        
        self.assertIn("Unsupported schema version", str(cm.exception))
    
    def test_import_invalid_json(self):
        """Test that import fails with invalid JSON"""
        invalid_json = "{ this is not valid json }"
        
        with self.assertRaises(BlueprintDeserializationError) as cm:
            import_blueprint_json(invalid_json)
        
        self.assertIn("Invalid JSON", str(cm.exception))
    
    def test_import_update_existing(self):
        """Test updating existing blueprint on import"""
        # Create initial blueprint
        original = IssueBlueprint.objects.create(
            title="Original Blueprint",
            category=self.category,
            description_md="Original description",
            version=1
        )
        
        # Import with same title and category
        data = {
            "schema_version": "1.0",
            "blueprint": {
                "title": "Original Blueprint",
                "description_md": "Updated description",
                "category": {
                    "name": "Features",
                    "slug": "features"
                },
                "is_active": True,
                "version": 2,
                "tags": ["updated"]
            }
        }
        
        blueprint, created = import_blueprint(data, update_if_exists=True)
        
        self.assertFalse(created)
        self.assertEqual(blueprint.id, original.id)
        self.assertEqual(blueprint.description_md, "Updated description")
        self.assertEqual(blueprint.version, 2)
        self.assertEqual(blueprint.tags, ["updated"])
    
    def test_import_invalid_risk_level(self):
        """Test that import fails with invalid risk level"""
        data = {
            "schema_version": "1.0",
            "blueprint": {
                "title": "Test",
                "description_md": "# Description",
                "category": {
                    "name": "Features",
                    "slug": "features"
                },
                "default_risk_level": "InvalidLevel"
            }
        }
        
        with self.assertRaises(BlueprintDeserializationError) as cm:
            import_blueprint(data)
        
        self.assertIn("Invalid default_risk_level", str(cm.exception))


class BlueprintRoundtripTestCase(TestCase):
    """Test cases for export -> import roundtrip"""
    
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
    
    def test_roundtrip_full_blueprint(self):
        """Test export -> import produces equivalent blueprint"""
        original = IssueBlueprint.objects.create(
            title="Original Blueprint",
            category=self.category,
            description_md="# Original Description\n\nWith multiple lines.",
            is_active=True,
            version=3,
            tags=["tag1", "tag2", "tag3"],
            default_labels=["label1", "label2"],
            default_risk_level=RiskLevel.HIGH,
            default_security_relevant=True,
            notes="Original notes",
            created_by=self.user
        )
        
        # Export
        json_str = export_blueprint_json(original)
        
        # Import (to a different category to avoid update)
        imported, created = import_blueprint_json(json_str, created_by=self.user)
        
        # Compare fields (except id, timestamps, and created_by)
        self.assertEqual(imported.title, original.title)
        self.assertEqual(imported.description_md, original.description_md)
        self.assertEqual(imported.category.slug, original.category.slug)
        self.assertEqual(imported.is_active, original.is_active)
        self.assertEqual(imported.version, original.version)
        self.assertEqual(imported.tags, original.tags)
        self.assertEqual(imported.default_labels, original.default_labels)
        self.assertEqual(imported.default_risk_level, original.default_risk_level)
        self.assertEqual(imported.default_security_relevant, original.default_security_relevant)
        self.assertEqual(imported.notes, original.notes)
    
    def test_roundtrip_minimal_blueprint(self):
        """Test roundtrip with minimal blueprint"""
        original = IssueBlueprint.objects.create(
            title="Minimal",
            category=self.category,
            description_md="Simple description"
        )
        
        # Export and import
        json_str = export_blueprint_json(original)
        imported, created = import_blueprint_json(json_str)
        
        self.assertEqual(imported.title, original.title)
        self.assertEqual(imported.description_md, original.description_md)
        self.assertEqual(imported.category.slug, original.category.slug)


class BlueprintExportViewTestCase(TestCase):
    """Test cases for blueprint export view"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            name="Test User"
        )
        self.client.force_login(self.user)
        
        self.category = IssueBlueprintCategory.objects.create(
            name="Features",
            slug="features"
        )
        
        self.blueprint = IssueBlueprint.objects.create(
            title="Export Test Blueprint",
            category=self.category,
            description_md="# Test",
            version=1
        )
    
    def test_export_view_returns_json(self):
        """Test that export view returns JSON file"""
        url = reverse('blueprint-export', kwargs={'id': self.blueprint.id})
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertIn('attachment', response['Content-Disposition'])
        
        # Verify JSON content
        data = json.loads(response.content)
        self.assertEqual(data['schema_version'], CURRENT_SCHEMA_VERSION)
        self.assertEqual(data['blueprint']['title'], 'Export Test Blueprint')
    
    def test_export_view_requires_login(self):
        """Test that export requires authentication"""
        self.client.logout()
        url = reverse('blueprint-export', kwargs={'id': self.blueprint.id})
        response = self.client.get(url)
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)


class BlueprintImportViewTestCase(TestCase):
    """Test cases for blueprint import view"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        self.user = User.objects.create(
            username="testuser",
            email="test@example.com",
            name="Test User"
        )
        self.client.force_login(self.user)
        
        self.category = IssueBlueprintCategory.objects.create(
            name="Features",
            slug="features"
        )
    
    def test_import_form_view(self):
        """Test that import form renders"""
        url = reverse('blueprint-import-form')
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Import Blueprint')
    
    def test_import_view_with_text(self):
        """Test importing blueprint via text input"""
        json_data = json.dumps({
            "schema_version": "1.0",
            "blueprint": {
                "title": "Imported via Text",
                "description_md": "# Description",
                "category": {
                    "name": "Features",
                    "slug": "features"
                },
                "is_active": True,
                "version": 1
            }
        })
        
        url = reverse('blueprint-import')
        response = self.client.post(url, {
            'json_text': json_data
        })
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        
        # Verify blueprint was created
        self.assertTrue(IssueBlueprint.objects.filter(title="Imported via Text").exists())
    
    def test_import_view_invalid_json(self):
        """Test import with invalid JSON"""
        url = reverse('blueprint-import')
        response = self.client.post(url, {
            'json_text': '{ invalid json }'
        })
        
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
        self.assertIn('Invalid JSON', data['error'])
    
    def test_import_view_requires_login(self):
        """Test that import requires authentication"""
        self.client.logout()
        url = reverse('blueprint-import')
        response = self.client.post(url, {})
        
        # Should redirect to login
        self.assertEqual(response.status_code, 302)
