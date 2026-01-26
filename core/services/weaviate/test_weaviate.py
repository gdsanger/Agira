"""
Tests for the Weaviate service layer.
"""

import uuid
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from django.test import TestCase

from core.models import WeaviateConfiguration
from core.services.exceptions import ServiceDisabled, ServiceNotConfigured
from core.services.weaviate import client, schema, service


class MakeWeaviateUUIDTestCase(TestCase):
    """Test make_weaviate_uuid public API function."""
    
    def test_make_weaviate_uuid_returns_string(self):
        """Test that make_weaviate_uuid returns a string."""
        result = service.make_weaviate_uuid("item", "123")
        self.assertIsInstance(result, str)
    
    def test_make_weaviate_uuid_is_deterministic(self):
        """Test that make_weaviate_uuid returns same UUID for same input."""
        uuid1 = service.make_weaviate_uuid("item", "123")
        uuid2 = service.make_weaviate_uuid("item", "123")
        self.assertEqual(uuid1, uuid2)
    
    def test_make_weaviate_uuid_differs_by_type(self):
        """Test that different types produce different UUIDs."""
        uuid1 = service.make_weaviate_uuid("item", "123")
        uuid2 = service.make_weaviate_uuid("comment", "123")
        self.assertNotEqual(uuid1, uuid2)
    
    def test_make_weaviate_uuid_differs_by_id(self):
        """Test that different IDs produce different UUIDs."""
        uuid1 = service.make_weaviate_uuid("item", "123")
        uuid2 = service.make_weaviate_uuid("item", "456")
        self.assertNotEqual(uuid1, uuid2)


class DeterministicUUIDTestCase(TestCase):
    """Test deterministic UUID generation."""
    
    def test_same_input_generates_same_uuid(self):
        """Test that the same source generates the same UUID."""
        uuid1 = service._get_deterministic_uuid("item", "123")
        uuid2 = service._get_deterministic_uuid("item", "123")
        self.assertEqual(uuid1, uuid2)
    
    def test_different_source_type_generates_different_uuid(self):
        """Test that different source types generate different UUIDs."""
        uuid1 = service._get_deterministic_uuid("item", "123")
        uuid2 = service._get_deterministic_uuid("node", "123")
        self.assertNotEqual(uuid1, uuid2)
    
    def test_different_source_id_generates_different_uuid(self):
        """Test that different source IDs generate different UUIDs."""
        uuid1 = service._get_deterministic_uuid("item", "123")
        uuid2 = service._get_deterministic_uuid("item", "456")
        self.assertNotEqual(uuid1, uuid2)
    
    def test_uuid_is_valid_uuid5(self):
        """Test that generated UUID is a valid UUID5."""
        result = service._get_deterministic_uuid("item", "123")
        self.assertIsInstance(result, uuid.UUID)
        self.assertEqual(result.version, 5)


class ClientTestCase(TestCase):
    """Test Weaviate client management."""
    
    def tearDown(self):
        """Clean up test data."""
        from core.services.config import invalidate_singleton
        WeaviateConfiguration.objects.all().delete()
        invalidate_singleton(WeaviateConfiguration)
    
    def test_get_client_raises_service_disabled_when_not_enabled(self):
        """Test that get_client raises ServiceDisabled when disabled."""
        WeaviateConfiguration.objects.create(
            url="http://localhost:8080",
            enabled=False
        )
        
        with self.assertRaises(ServiceDisabled) as cm:
            client.get_client()
        
        self.assertIn("not enabled", str(cm.exception))
    
    def test_get_client_raises_service_disabled_when_not_configured(self):
        """Test that get_client raises ServiceDisabled when config doesn't exist."""
        with self.assertRaises(ServiceDisabled) as cm:
            client.get_client()
        
        self.assertIn("not enabled", str(cm.exception))
    
    def test_get_client_raises_service_not_configured_when_url_missing(self):
        """Test that get_client raises ServiceNotConfigured when URL is missing."""
        WeaviateConfiguration.objects.create(
            url="",
            enabled=True
        )
        
        with self.assertRaises(ServiceNotConfigured) as cm:
            client.get_client()
        
        self.assertIn("URL is not configured", str(cm.exception))
    
    @patch('core.services.weaviate.client.weaviate.connect_to_custom')
    def test_get_client_creates_client_without_auth(self, mock_connect):
        """Test that get_client creates a client without auth when no API key."""
        WeaviateConfiguration.objects.create(
            url="http://localhost:8080",
            api_key="",
            enabled=True
        )
        
        mock_client = Mock()
        mock_connect.return_value = mock_client
        
        result = client.get_client()
        
        self.assertEqual(result, mock_client)
        mock_connect.assert_called_once()
    
    @patch('core.services.weaviate.client.weaviate.connect_to_custom')
    def test_get_client_creates_client_with_auth(self, mock_connect):
        """Test that get_client creates a client with auth when API key provided."""
        WeaviateConfiguration.objects.create(
            url="http://localhost:8080",
            api_key="test-api-key",
            enabled=True
        )
        
        mock_client = Mock()
        mock_connect.return_value = mock_client
        
        result = client.get_client()
        
        self.assertEqual(result, mock_client)
        mock_connect.assert_called_once()
        # Verify auth_credentials parameter is present
        call_kwargs = mock_connect.call_args[1]
        self.assertIn('auth_credentials', call_kwargs)
    
    def test_is_available_returns_false_when_not_configured(self):
        """Test that is_available returns False when not configured."""
        self.assertFalse(client.is_available())
    
    def test_is_available_returns_false_when_disabled(self):
        """Test that is_available returns False when disabled."""
        WeaviateConfiguration.objects.create(
            url="http://localhost:8080",
            enabled=False
        )
        
        self.assertFalse(client.is_available())
    
    def test_is_available_returns_false_when_url_missing(self):
        """Test that is_available returns False when URL is missing."""
        WeaviateConfiguration.objects.create(
            url="",
            enabled=True
        )
        
        self.assertFalse(client.is_available())
    
    def test_is_available_returns_true_when_configured(self):
        """Test that is_available returns True when properly configured."""
        WeaviateConfiguration.objects.create(
            url="http://localhost:8080",
            enabled=True
        )
        
        self.assertTrue(client.is_available())
    
    @patch('core.services.weaviate.client.weaviate.connect_to_custom')
    def test_get_client_uses_custom_ports(self, mock_connect):
        """Test that get_client uses custom http_port and grpc_port when configured."""
        WeaviateConfiguration.objects.create(
            url="http://192.168.1.100",  # URL without port
            http_port=8081,
            grpc_port=50051,
            api_key="",
            enabled=True
        )
        
        mock_client = Mock()
        mock_connect.return_value = mock_client
        
        result = client.get_client()
        
        self.assertEqual(result, mock_client)
        mock_connect.assert_called_once()
        
        # Verify the ports are correctly used
        call_kwargs = mock_connect.call_args[1]
        self.assertEqual(call_kwargs['http_port'], 8081)
        self.assertEqual(call_kwargs['grpc_port'], 50051)
        self.assertEqual(call_kwargs['http_host'], '192.168.1.100')
    
    @patch('core.services.weaviate.client.weaviate.connect_to_custom')
    def test_get_client_url_port_takes_precedence(self, mock_connect):
        """Test that port in URL takes precedence over http_port field."""
        WeaviateConfiguration.objects.create(
            url="http://localhost:9999",  # URL with port
            http_port=8081,  # This should be ignored
            grpc_port=50051,
            api_key="",
            enabled=True
        )
        
        mock_client = Mock()
        mock_connect.return_value = mock_client
        
        result = client.get_client()
        
        self.assertEqual(result, mock_client)
        mock_connect.assert_called_once()
        
        # Verify URL port takes precedence
        call_kwargs = mock_connect.call_args[1]
        self.assertEqual(call_kwargs['http_port'], 9999)
        self.assertEqual(call_kwargs['grpc_port'], 50051)
    
    def test_port_validation_rejects_invalid_http_port(self):
        """Test that invalid HTTP port values are rejected."""
        from django.core.exceptions import ValidationError
        
        # Test port too low
        config = WeaviateConfiguration(
            url="http://localhost",
            http_port=0,
            enabled=True
        )
        with self.assertRaises(ValidationError):
            config.full_clean()
        
        # Test port too high
        config = WeaviateConfiguration(
            url="http://localhost",
            http_port=65536,
            enabled=True
        )
        with self.assertRaises(ValidationError):
            config.full_clean()
    
    def test_port_validation_rejects_invalid_grpc_port(self):
        """Test that invalid gRPC port values are rejected."""
        from django.core.exceptions import ValidationError
        
        # Test port too low
        config = WeaviateConfiguration(
            url="http://localhost",
            grpc_port=0,
            enabled=True
        )
        with self.assertRaises(ValidationError):
            config.full_clean()
        
        # Test port too high
        config = WeaviateConfiguration(
            url="http://localhost",
            grpc_port=65536,
            enabled=True
        )
        with self.assertRaises(ValidationError):
            config.full_clean()
    
    def test_port_validation_accepts_valid_ports(self):
        """Test that valid port values are accepted."""
        config = WeaviateConfiguration(
            url="http://localhost",
            http_port=8081,
            grpc_port=50051,
            enabled=True
        )
        # Should not raise ValidationError
        config.full_clean()


class SchemaTestCase(TestCase):
    """Test Weaviate schema management."""
    
    def test_get_collection_name_returns_correct_name(self):
        """Test that get_collection_name returns the correct collection name."""
        self.assertEqual(schema.get_collection_name(), "AgiraObject")
    
    def test_get_schema_version_returns_v1(self):
        """Test that get_schema_version returns v1."""
        self.assertEqual(schema.get_schema_version(), "v1")
    
    def test_ensure_schema_skips_when_collection_exists(self):
        """Test that ensure_schema doesn't recreate existing collection."""
        mock_client = Mock()
        mock_client.collections.exists.return_value = True
        
        schema.ensure_schema(mock_client)
        
        # Should check if exists
        mock_client.collections.exists.assert_called_once_with("AgiraObject")
        # Should not create
        mock_client.collections.create.assert_not_called()
    
    def test_ensure_schema_creates_collection_when_not_exists(self):
        """Test that ensure_schema creates collection when it doesn't exist."""
        mock_client = Mock()
        mock_client.collections.exists.return_value = False
        
        schema.ensure_schema(mock_client)
        
        # Should check if exists
        mock_client.collections.exists.assert_called_once_with("AgiraObject")
        # Should create collection
        mock_client.collections.create.assert_called_once()
        
        # Verify collection name
        call_kwargs = mock_client.collections.create.call_args[1]
        self.assertEqual(call_kwargs['name'], "AgiraObject")
        
        # Verify properties include required fields from new schema
        properties = call_kwargs['properties']
        property_names = [prop.name for prop in properties]
        self.assertIn('type', property_names)
        self.assertIn('object_id', property_names)
        self.assertIn('project_id', property_names)
        self.assertIn('title', property_names)
        self.assertIn('text', property_names)
        self.assertIn('created_at', property_names)
        self.assertIn('updated_at', property_names)
        self.assertIn('org_id', property_names)
        self.assertIn('status', property_names)
        self.assertIn('url', property_names)
        self.assertIn('source_system', property_names)
        self.assertIn('external_key', property_names)
        self.assertIn('parent_object_id', property_names)
        self.assertIn('mime_type', property_names)
        self.assertIn('size_bytes', property_names)
        self.assertIn('sha256', property_names)


class ServiceTestCase(TestCase):
    """Test Weaviate service operations."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Reset the schema ensured flag
        service._schema_ensured = False
    
    def tearDown(self):
        """Clean up test data."""
        from core.services.config import invalidate_singleton
        WeaviateConfiguration.objects.all().delete()
        invalidate_singleton(WeaviateConfiguration)
        service._schema_ensured = False
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service.ensure_schema')
    def test_upsert_document_creates_document(self, mock_ensure_schema, mock_get_client):
        """Test that upsert_document creates a document."""
        # Setup mocks
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        # Call upsert
        result = service.upsert_document(
            source_type="item",
            source_id="123",
            project_id="proj-1",
            title="Test Item",
            text="This is a test item",
            tags=["test", "bug"],
            url="/items/123"
        )
        
        # Verify schema was ensured
        mock_ensure_schema.assert_called_once_with(mock_client)
        
        # Verify collection was retrieved
        mock_client.collections.get.assert_called_once_with("AgiraObject")
        
        # Verify replace was attempted (may fail and fall back to insert)
        # Since replace will fail in test (throws exception), insert should be called
        self.assertTrue(
            mock_collection.data.replace.called or mock_collection.data.insert.called
        )
        
        # Get the call that was actually made
        if mock_collection.data.insert.called:
            call_kwargs = mock_collection.data.insert.call_args[1]
        else:
            call_kwargs = mock_collection.data.replace.call_args[1]
        
        # Verify properties
        props = call_kwargs['properties']
        self.assertEqual(props['source_type'], "item")
        self.assertEqual(props['source_id'], "123")
        self.assertEqual(props['project_id'], "proj-1")
        self.assertEqual(props['title'], "Test Item")
        self.assertEqual(props['text'], "This is a test item")
        self.assertEqual(props['tags'], ["test", "bug"])
        self.assertEqual(props['url'], "/items/123")
        
        # Verify deterministic UUID
        expected_uuid = service._get_deterministic_uuid("item", "123")
        self.assertEqual(call_kwargs['uuid'], expected_uuid)
        
        # Verify result is UUID string
        self.assertEqual(result, str(expected_uuid))
        
        # Verify client was closed
        mock_client.close.assert_called_once()
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service.ensure_schema')
    def test_upsert_document_converts_int_ids_to_strings(self, mock_ensure_schema, mock_get_client):
        """Test that upsert_document converts integer IDs to strings."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        # Make replace fail so it falls back to insert
        mock_collection.data.replace.side_effect = Exception("Not found")
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        service.upsert_document(
            source_type="item",
            source_id=123,  # int
            project_id=456,  # int
            title="Test",
            text="Test"
        )
        
        # Verify IDs were converted to strings
        # Since replace fails, insert should be called
        self.assertTrue(mock_collection.data.insert.called)
        call_kwargs = mock_collection.data.insert.call_args[1]
        props = call_kwargs['properties']
        self.assertEqual(props['source_id'], "123")
        self.assertEqual(props['project_id'], "456")
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service.ensure_schema')
    def test_upsert_document_ensures_schema_only_once(self, mock_ensure_schema, mock_get_client):
        """Test that ensure_schema is only called once per process."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        # First call
        service.upsert_document(
            source_type="item",
            source_id="123",
            project_id="proj-1",
            title="Test 1",
            text="Test 1"
        )
        
        # Second call
        service.upsert_document(
            source_type="item",
            source_id="456",
            project_id="proj-1",
            title="Test 2",
            text="Test 2"
        )
        
        # Schema should only be ensured once
        self.assertEqual(mock_ensure_schema.call_count, 1)
    
    @patch('core.services.weaviate.service.get_client')
    def test_delete_document_deletes_by_uuid(self, mock_get_client):
        """Test that delete_document deletes using deterministic UUID."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        result = service.delete_document("item", "123")
        
        # Verify collection was retrieved
        mock_client.collections.get.assert_called_once_with("AgiraObject")
        
        # Verify delete was called with deterministic UUID
        expected_uuid = service._get_deterministic_uuid("item", "123")
        mock_collection.data.delete_by_id.assert_called_once_with(expected_uuid)
        
        # Verify result
        self.assertTrue(result)
        
        # Verify client was closed
        mock_client.close.assert_called_once()
    
    @patch('core.services.weaviate.service.get_client')
    def test_delete_document_returns_false_on_error(self, mock_get_client):
        """Test that delete_document returns False when deletion fails."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.data.delete_by_id.side_effect = Exception("Not found")
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        result = service.delete_document("item", "123")
        
        self.assertFalse(result)
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service.ensure_schema')
    def test_query_filters_by_project_id(self, mock_ensure_schema, mock_get_client):
        """Test that query filters by project_id."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        mock_collection.query.near_text.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        service.query(
            project_id="proj-1",
            query_text="test query",
            top_k=10
        )
        
        # Verify near_text was called
        mock_collection.query.near_text.assert_called_once()
        
        # Verify query parameters
        call_kwargs = mock_collection.query.near_text.call_args[1]
        self.assertEqual(call_kwargs['query'], "test query")
        self.assertEqual(call_kwargs['limit'], 10)
        
        # Note: Filter is created with Filter API, hard to verify exact filter
        # but we can verify where parameter exists
        self.assertIn('where', call_kwargs)
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service.ensure_schema')
    def test_query_returns_formatted_results(self, mock_ensure_schema, mock_get_client):
        """Test that query returns properly formatted results."""
        # Setup mock response
        mock_obj = MagicMock()
        mock_obj.properties = {
            "source_type": "item",
            "source_id": "123",
            "title": "Test Item",
            "text": "This is a test item with some text",
            "url": "/items/123"
        }
        mock_obj.metadata.distance = 0.123
        
        mock_response = MagicMock()
        mock_response.objects = [mock_obj]
        
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.near_text.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        results = service.query(
            project_id="proj-1",
            query_text="test",
            top_k=5
        )
        
        # Verify result structure
        self.assertEqual(len(results), 1)
        result = results[0]
        
        self.assertEqual(result['source_type'], "item")
        self.assertEqual(result['source_id'], "123")
        self.assertEqual(result['title'], "Test Item")
        self.assertEqual(result['text_preview'], "This is a test item with some text")
        self.assertEqual(result['url'], "/items/123")
        self.assertEqual(result['score'], 0.123)
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service.ensure_schema')
    def test_query_truncates_long_text(self, mock_ensure_schema, mock_get_client):
        """Test that query truncates text preview to 200 characters."""
        # Create long text (300 characters)
        long_text = "a" * 300
        
        mock_obj = MagicMock()
        mock_obj.properties = {
            "source_type": "item",
            "source_id": "123",
            "title": "Test",
            "text": long_text,
        }
        mock_obj.metadata.distance = 0.5
        
        mock_response = MagicMock()
        mock_response.objects = [mock_obj]
        
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.near_text.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        results = service.query(
            project_id="proj-1",
            query_text="test"
        )
        
        # Verify text was truncated
        self.assertEqual(len(results[0]['text_preview']), 203)  # 200 + "..."
        self.assertTrue(results[0]['text_preview'].endswith("..."))


class GetWeaviateTypeTestCase(TestCase):
    """Test get_weaviate_type function."""
    
    def test_get_weaviate_type_returns_item_for_item(self):
        """Test that get_weaviate_type returns 'item' for Item model."""
        from core.models import Item, Project, ItemType
        
        project = Project.objects.create(name="Test Project")
        item_type = ItemType.objects.create(key="bug", name="Bug")
        item = Item.objects.create(
            title="Test Item",
            project=project,
            type=item_type
        )
        
        result = service.get_weaviate_type(item)
        self.assertEqual(result, "item")
    
    def test_get_weaviate_type_returns_comment_for_comment(self):
        """Test that get_weaviate_type returns 'comment' for ItemComment model."""
        from core.models import Item, ItemComment, Project, ItemType, User
        
        project = Project.objects.create(name="Test Project")
        item_type = ItemType.objects.create(key="bug", name="Bug")
        item = Item.objects.create(
            title="Test Item",
            project=project,
            type=item_type
        )
        user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        comment = ItemComment.objects.create(
            item=item,
            author=user,
            body="Test comment"
        )
        
        result = service.get_weaviate_type(comment)
        self.assertEqual(result, "comment")
    
    def test_get_weaviate_type_returns_project_for_project(self):
        """Test that get_weaviate_type returns 'project' for Project model."""
        from core.models import Project
        
        project = Project.objects.create(name="Test Project")
        
        result = service.get_weaviate_type(project)
        self.assertEqual(result, "project")


class ExistsObjectTestCase(TestCase):
    """Test exists_object and exists_instance functions."""
    
    @patch('core.services.weaviate.service.get_client')
    def test_exists_object_returns_true_when_object_exists(self, mock_get_client):
        """Test that exists_object returns True when object exists."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_obj = MagicMock()
        mock_collection.query.fetch_object_by_id.return_value = mock_obj
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        result = service.exists_object("item", "123")
        
        # Verify fetch was called with deterministic UUID
        expected_uuid = service._get_deterministic_uuid("item", "123")
        mock_collection.query.fetch_object_by_id.assert_called_once_with(expected_uuid)
        
        self.assertTrue(result)
        mock_client.close.assert_called_once()
    
    @patch('core.services.weaviate.service.get_client')
    def test_exists_object_returns_false_when_object_not_found(self, mock_get_client):
        """Test that exists_object returns False when object doesn't exist."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.fetch_object_by_id.return_value = None
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        result = service.exists_object("item", "123")
        
        self.assertFalse(result)
        mock_client.close.assert_called_once()
    
    @patch('core.services.weaviate.service.get_client')
    def test_exists_object_returns_false_on_exception(self, mock_get_client):
        """Test that exists_object returns False when an exception occurs."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.fetch_object_by_id.side_effect = Exception("Connection error")
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        result = service.exists_object("item", "123")
        
        self.assertFalse(result)
    
    @patch('core.services.weaviate.service.exists_object')
    def test_exists_instance_calls_exists_object_with_correct_params(self, mock_exists_object):
        """Test that exists_instance calls exists_object with correct parameters."""
        from core.models import Item, Project, ItemType
        
        project = Project.objects.create(name="Test Project")
        item_type = ItemType.objects.create(key="bug", name="Bug")
        item = Item.objects.create(
            title="Test Item",
            project=project,
            type=item_type
        )
        
        mock_exists_object.return_value = True
        
        result = service.exists_instance(item)
        
        # Verify exists_object was called with correct type and ID
        mock_exists_object.assert_called_once_with("item", str(item.pk))
        self.assertTrue(result)


class FetchObjectTestCase(TestCase):
    """Test fetch_object and fetch_object_by_type functions."""
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service._ensure_schema_once')
    def test_fetch_object_by_type_returns_object_data(self, mock_ensure_schema, mock_get_client):
        """Test that fetch_object_by_type returns object data when found."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        
        # Mock the returned object
        mock_obj = MagicMock()
        mock_obj.properties = {
            "type": "item",
            "object_id": "123",
            "title": "Test Item",
            "text": "Test text"
        }
        mock_obj.uuid = uuid.uuid4()
        
        mock_collection.query.fetch_object_by_id.return_value = mock_obj
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        result = service.fetch_object_by_type("item", "123")
        
        # Verify result contains properties and UUID
        self.assertIsNotNone(result)
        self.assertEqual(result['type'], "item")
        self.assertEqual(result['object_id'], "123")
        self.assertEqual(result['title'], "Test Item")
        self.assertEqual(result['text'], "Test text")
        self.assertIn('uuid', result)
        
        mock_client.close.assert_called_once()
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service._ensure_schema_once')
    def test_fetch_object_by_type_returns_none_when_not_found(self, mock_ensure_schema, mock_get_client):
        """Test that fetch_object_by_type returns None when object not found."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.fetch_object_by_id.return_value = None
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        result = service.fetch_object_by_type("item", "123")
        
        self.assertIsNone(result)
        mock_client.close.assert_called_once()
    
    @patch('core.services.weaviate.service.fetch_object_by_type')
    def test_fetch_object_calls_fetch_object_by_type(self, mock_fetch_by_type):
        """Test that fetch_object calls fetch_object_by_type with correct parameters."""
        from core.models import Item, Project, ItemType
        
        project = Project.objects.create(name="Test Project")
        item_type = ItemType.objects.create(key="bug", name="Bug")
        item = Item.objects.create(
            title="Test Item",
            project=project,
            type=item_type
        )
        
        mock_fetch_by_type.return_value = {"type": "item", "object_id": str(item.pk)}
        
        result = service.fetch_object(item)
        
        # Verify fetch_object_by_type was called with correct type and ID
        mock_fetch_by_type.assert_called_once_with("item", str(item.pk))
        self.assertIsNotNone(result)


class ExternalIssueMappingSerializationTestCase(TestCase):
    """Test ExternalIssueMapping serialization with GitHub data fetching."""
    
    def setUp(self):
        """Set up test data."""
        from core.models import Project, Item, ItemType, ExternalIssueMapping, Organisation
        
        # Create test organisation
        self.org = Organisation.objects.create(name="Test Org")
        
        # Create test project with GitHub config
        self.project = Project.objects.create(
            name="Test Project",
            github_owner="test-owner",
            github_repo="test-repo"
        )
        
        # Create test item type
        self.item_type = ItemType.objects.create(
            key="bug",
            name="Bug"
        )
        
        # Create test item
        self.item = Item.objects.create(
            title="Test Item",
            description="Local description",
            project=self.project,
            type=self.item_type,
            organisation=self.org
        )
        
        # Create external issue mapping
        self.mapping = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=12345,
            number=42,
            kind='Issue',
            state='open',
            html_url='https://github.com/test-owner/test-repo/issues/42'
        )
    
    def test_serialize_github_issue_without_fetch(self):
        """Test serializing ExternalIssueMapping without fetching from GitHub."""
        from core.services.weaviate.serializers import _serialize_github_issue
        
        result = _serialize_github_issue(self.mapping, fetch_from_github=False)
        
        # Should use local Item data
        self.assertEqual(result['type'], 'github_issue')
        self.assertEqual(result['object_id'], str(self.mapping.id))
        self.assertEqual(result['title'], 'Test Item')
        self.assertIn('Local description', result['text'])
        self.assertEqual(result['status'], 'open')
        self.assertEqual(result['source_system'], 'github')
        self.assertEqual(result['external_key'], 'test-owner/test-repo#42')
    
    @patch('core.services.weaviate.serializers._fetch_github_issue_data')
    def test_serialize_github_issue_with_fetch_success(self, mock_fetch):
        """Test serializing ExternalIssueMapping with successful GitHub fetch."""
        from core.services.weaviate.serializers import _serialize_github_issue
        
        # Mock GitHub API response
        mock_fetch.return_value = {
            'title': 'Real GitHub Issue Title',
            'body': 'Real GitHub issue body with details',
            'state': 'open',
            'labels': [
                {'name': 'bug'},
                {'name': 'high-priority'}
            ],
            'created_at': '2024-01-15T10:30:00Z',
            'updated_at': '2024-01-16T14:45:00Z'
        }
        
        result = _serialize_github_issue(self.mapping, fetch_from_github=True)
        
        # Should use GitHub data
        self.assertEqual(result['type'], 'github_issue')
        self.assertEqual(result['title'], 'Real GitHub Issue Title')
        self.assertIn('Real GitHub issue body with details', result['text'])
        self.assertIn('bug, high-priority', result['text'])
        self.assertEqual(result['status'], 'open')
        
        # Verify GitHub fetch was called
        mock_fetch.assert_called_once_with(
            owner='test-owner',
            repo='test-repo',
            number=42,
            kind='Issue'
        )
    
    @patch('core.services.weaviate.serializers._fetch_github_issue_data')
    def test_serialize_github_issue_with_fetch_failure(self, mock_fetch):
        """Test serializing ExternalIssueMapping when GitHub fetch fails."""
        from core.services.weaviate.serializers import _serialize_github_issue
        
        # Mock GitHub fetch failure
        mock_fetch.return_value = None
        
        result = _serialize_github_issue(self.mapping, fetch_from_github=True)
        
        # Should fall back to local Item data
        self.assertEqual(result['type'], 'github_issue')
        self.assertEqual(result['title'], 'Test Item')
        self.assertIn('Local description', result['text'])
    
    @patch('core.services.weaviate.serializers._fetch_github_issue_data')
    def test_serialize_github_pr(self, mock_fetch):
        """Test serializing ExternalIssueMapping for a Pull Request."""
        from core.services.weaviate.serializers import _serialize_github_issue
        from core.models import ExternalIssueMapping
        
        # Create PR mapping
        pr_mapping = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=67890,
            number=100,
            kind='PR',
            state='merged',
            html_url='https://github.com/test-owner/test-repo/pull/100'
        )
        
        mock_fetch.return_value = {
            'title': 'Fix critical bug',
            'body': 'This PR fixes the critical bug',
            'state': 'merged',
            'labels': [],
            'created_at': '2024-01-15T10:30:00Z',
            'updated_at': '2024-01-16T14:45:00Z'
        }
        
        result = _serialize_github_issue(pr_mapping, fetch_from_github=True)
        
        # Should be typed as github_pr
        self.assertEqual(result['type'], 'github_pr')
        self.assertEqual(result['title'], 'Fix critical bug')
        self.assertEqual(result['status'], 'merged')


class AttachmentSerializationTestCase(TestCase):
    """Test Attachment serialization with markdown content."""
    
    def setUp(self):
        """Set up test data."""
        from core.models import Project
        
        # Create test project
        self.project = Project.objects.create(
            name="Test Project",
            github_owner="test-owner",
            github_repo="test-repo"
        )
    
    def test_serialize_markdown_attachment_with_content(self):
        """Test serializing markdown attachment reads file content."""
        import io
        from core.models import Attachment
        from core.services.storage.service import AttachmentStorageService
        from core.services.weaviate.serializers import _serialize_attachment
        
        # Create markdown content
        markdown_content = """# Test Markdown File

This is a test markdown file with some content.

## Section 1

Here is some text in section 1.

## Section 2

Here is some text in section 2.
"""
        
        # Create attachment via storage service
        storage = AttachmentStorageService()
        file_obj = io.BytesIO(markdown_content.encode('utf-8'))
        file_obj.name = 'test-readme.md'
        
        attachment = storage.store_attachment(
            file=file_obj,
            target=self.project,
            created_by=None,
        )
        
        # Set content type to markdown
        attachment.content_type = 'text/markdown'
        attachment.save()
        
        # Serialize the attachment
        result = _serialize_attachment(attachment)
        
        # Verify the text field contains the actual markdown content
        self.assertEqual(result['type'], 'attachment')
        self.assertEqual(result['title'], 'test-readme.md')
        self.assertIn('# Test Markdown File', result['text'])
        self.assertIn('This is a test markdown file with some content.', result['text'])
        self.assertIn('## Section 1', result['text'])
        self.assertIn('## Section 2', result['text'])
        # Should NOT contain the old filename-based text
        self.assertNotIn('Attachment:', result['text'])
    
    def test_serialize_non_markdown_attachment(self):
        """Test serializing non-markdown attachment uses metadata."""
        import io
        from core.models import Attachment
        from core.services.storage.service import AttachmentStorageService
        from core.services.weaviate.serializers import _serialize_attachment
        
        # Create a non-markdown file
        content = b"Some binary content"
        
        storage = AttachmentStorageService()
        file_obj = io.BytesIO(content)
        file_obj.name = 'test-file.pdf'
        
        attachment = storage.store_attachment(
            file=file_obj,
            target=self.project,
            created_by=None,
        )
        
        # Set content type to PDF
        attachment.content_type = 'application/pdf'
        attachment.save()
        
        # Serialize the attachment
        result = _serialize_attachment(attachment)
        
        # Verify the text field contains metadata, not file content
        self.assertEqual(result['type'], 'attachment')
        self.assertEqual(result['title'], 'test-file.pdf')
        self.assertIn('Attachment: test-file.pdf', result['text'])
        self.assertIn('application/pdf', result['text'])
        self.assertIn(f'Size: {len(content)} bytes', result['text'])
    
    def test_serialize_markdown_by_extension(self):
        """Test serializing markdown file identified by .md extension."""
        import io
        from core.models import Attachment
        from core.services.storage.service import AttachmentStorageService
        from core.services.weaviate.serializers import _serialize_attachment
        
        # Create markdown content
        markdown_content = "# Quick Test\n\nJust a quick test."
        
        storage = AttachmentStorageService()
        file_obj = io.BytesIO(markdown_content.encode('utf-8'))
        file_obj.name = 'notes.md'
        
        attachment = storage.store_attachment(
            file=file_obj,
            target=self.project,
            created_by=None,
        )
        
        # Don't set content_type, rely on .md extension detection
        attachment.content_type = ''
        attachment.save()
        
        # Serialize the attachment
        result = _serialize_attachment(attachment)
        
        # Should still read content based on .md extension
        self.assertIn('# Quick Test', result['text'])
        self.assertIn('Just a quick test.', result['text'])


class GlobalSearchTestCase(TestCase):
    """Test global_search function."""
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service._ensure_schema_once')
    def test_global_search_returns_list(self, mock_ensure_schema, mock_get_client):
        """Test that global_search returns a list of AgiraSearchHit objects."""
        # Mock Weaviate client and collection
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_response = MagicMock()
        
        # Create mock search result with fixed datetime for consistency
        fixed_datetime = datetime(2024, 1, 15, 10, 30, 0)
        mock_obj = MagicMock()
        mock_obj.properties = {
            'type': 'item',
            'title': 'Test Item',
            'url': '/items/123/',
            'object_id': '123',
            'project_id': '1',
            'status': 'working',
            'updated_at': fixed_datetime,
        }
        mock_obj.metadata.score = 0.85
        
        mock_response.objects = [mock_obj]
        mock_collection.query.hybrid.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        # Execute search
        from core.services.weaviate.service import global_search
        results = global_search("test query", limit=10)
        
        # Verify results
        self.assertIsInstance(results, list)
        self.assertEqual(len(results), 1)
        
        # Verify first result
        hit = results[0]
        from core.services.weaviate.service import AgiraSearchHit
        self.assertIsInstance(hit, AgiraSearchHit)
        self.assertEqual(hit.type, 'item')
        self.assertEqual(hit.title, 'Test Item')
        self.assertEqual(hit.url, '/items/123/')
        self.assertEqual(hit.object_id, '123')
        self.assertEqual(hit.score, 0.85)
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service._ensure_schema_once')
    def test_global_search_with_filters(self, mock_ensure_schema, mock_get_client):
        """Test that global_search applies filters correctly."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        
        mock_collection.query.hybrid.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        # Execute search with filters
        from core.services.weaviate.service import global_search
        filters = {'type': 'item', 'project_id': '1'}
        results = global_search("test", filters=filters)
        
        # Verify hybrid was called
        mock_collection.query.hybrid.assert_called_once()
        call_kwargs = mock_collection.query.hybrid.call_args[1]
        
        # Verify query parameters
        self.assertEqual(call_kwargs['query'], 'test')
        self.assertIsNotNone(call_kwargs['filters'])
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service._ensure_schema_once')
    def test_global_search_alpha_parameter(self, mock_ensure_schema, mock_get_client):
        """Test that global_search passes alpha parameter correctly."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        
        mock_collection.query.hybrid.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        # Execute search with custom alpha
        from core.services.weaviate.service import global_search
        results = global_search("test", alpha=0.75, limit=50)
        
        # Verify hybrid was called with correct parameters
        call_kwargs = mock_collection.query.hybrid.call_args[1]
        self.assertEqual(call_kwargs['alpha'], 0.75)
        self.assertEqual(call_kwargs['limit'], 50)
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service._ensure_schema_once')
    def test_global_search_uses_relative_score_fusion(self, mock_ensure_schema, mock_get_client):
        """Test that global_search uses RELATIVE_SCORE fusion for consistent scoring."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        
        mock_collection.query.hybrid.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        # Execute search
        from core.services.weaviate.service import global_search
        from weaviate.classes.query import HybridFusion
        results = global_search("test")
        
        # Verify fusion_type is set to RELATIVE_SCORE
        call_kwargs = mock_collection.query.hybrid.call_args[1]
        self.assertEqual(call_kwargs['fusion_type'], HybridFusion.RELATIVE_SCORE)
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service._ensure_schema_once')
    def test_global_search_sorts_by_score_descending(self, mock_ensure_schema, mock_get_client):
        """Test that global_search sorts results by score in descending order."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_response = MagicMock()
        
        # Create multiple mock results with different scores
        mock_obj1 = MagicMock()
        mock_obj1.properties = {'type': 'item', 'title': 'Low Score', 'object_id': '1'}
        mock_obj1.metadata.score = 0.3
        
        mock_obj2 = MagicMock()
        mock_obj2.properties = {'type': 'item', 'title': 'High Score', 'object_id': '2'}
        mock_obj2.metadata.score = 0.9
        
        mock_obj3 = MagicMock()
        mock_obj3.properties = {'type': 'item', 'title': 'Medium Score', 'object_id': '3'}
        mock_obj3.metadata.score = 0.6
        
        # Return in unsorted order
        mock_response.objects = [mock_obj1, mock_obj2, mock_obj3]
        mock_collection.query.hybrid.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        # Execute search
        from core.services.weaviate.service import global_search
        results = global_search("test")
        
        # Verify results are sorted by score descending
        self.assertEqual(len(results), 3)
        self.assertEqual(results[0].score, 0.9)  # Highest first
        self.assertEqual(results[0].title, 'High Score')
        self.assertEqual(results[1].score, 0.6)  # Medium second
        self.assertEqual(results[1].title, 'Medium Score')
        self.assertEqual(results[2].score, 0.3)  # Lowest last
        self.assertEqual(results[2].title, 'Low Score')
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service._ensure_schema_once')
    def test_global_search_mode_keyword(self, mock_ensure_schema, mock_get_client):
        """Test that keyword mode uses alpha=0.0 for pure BM25."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        
        mock_collection.query.hybrid.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        # Execute search with keyword mode
        from core.services.weaviate.service import global_search
        results = global_search("test", mode="keyword")
        
        # Verify hybrid was called with alpha=0.0
        call_kwargs = mock_collection.query.hybrid.call_args[1]
        self.assertEqual(call_kwargs['alpha'], 0.0)
    
    @patch('core.services.weaviate.service.get_client')
    @patch('core.services.weaviate.service._ensure_schema_once')
    def test_global_search_mode_similar(self, mock_ensure_schema, mock_get_client):
        """Test that similar mode uses near_text query."""
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_response = MagicMock()
        mock_response.objects = []
        
        mock_collection.query.near_text.return_value = mock_response
        mock_client.collections.get.return_value = mock_collection
        mock_get_client.return_value = mock_client
        
        # Execute search with similar mode
        from core.services.weaviate.service import global_search
        results = global_search("test", mode="similar")
        
        # Verify near_text was called
        mock_collection.query.near_text.assert_called_once()
        call_kwargs = mock_collection.query.near_text.call_args[1]
        self.assertEqual(call_kwargs['query'], 'test')


