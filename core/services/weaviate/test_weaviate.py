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
        WeaviateConfiguration.objects.all().delete()
    
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
        # Verify no auth_credentials parameter
        call_kwargs = mock_connect.call_args[1]
        self.assertNotIn('auth_credentials', call_kwargs)
    
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


class SchemaTestCase(TestCase):
    """Test Weaviate schema management."""
    
    def test_get_collection_name_returns_correct_name(self):
        """Test that get_collection_name returns the correct collection name."""
        self.assertEqual(schema.get_collection_name(), "AgiraContext")
    
    def test_get_schema_version_returns_v1(self):
        """Test that get_schema_version returns v1."""
        self.assertEqual(schema.get_schema_version(), "v1")
    
    def test_ensure_schema_skips_when_collection_exists(self):
        """Test that ensure_schema doesn't recreate existing collection."""
        mock_client = Mock()
        mock_client.collections.exists.return_value = True
        
        schema.ensure_schema(mock_client)
        
        # Should check if exists
        mock_client.collections.exists.assert_called_once_with("AgiraContext")
        # Should not create
        mock_client.collections.create.assert_not_called()
    
    def test_ensure_schema_creates_collection_when_not_exists(self):
        """Test that ensure_schema creates collection when it doesn't exist."""
        mock_client = Mock()
        mock_client.collections.exists.return_value = False
        
        schema.ensure_schema(mock_client)
        
        # Should check if exists
        mock_client.collections.exists.assert_called_once_with("AgiraContext")
        # Should create collection
        mock_client.collections.create.assert_called_once()
        
        # Verify collection name
        call_kwargs = mock_client.collections.create.call_args[1]
        self.assertEqual(call_kwargs['name'], "AgiraContext")
        
        # Verify properties include required fields
        properties = call_kwargs['properties']
        property_names = [prop.name for prop in properties]
        self.assertIn('source_type', property_names)
        self.assertIn('source_id', property_names)
        self.assertIn('project_id', property_names)
        self.assertIn('title', property_names)
        self.assertIn('text', property_names)
        self.assertIn('tags', property_names)
        self.assertIn('url', property_names)
        self.assertIn('updated_at', property_names)


class ServiceTestCase(TestCase):
    """Test Weaviate service operations."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Reset the schema ensured flag
        service._schema_ensured = False
    
    def tearDown(self):
        """Clean up test data."""
        WeaviateConfiguration.objects.all().delete()
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
        mock_client.collections.get.assert_called_once_with("AgiraContext")
        
        # Verify insert was called
        mock_collection.data.insert.assert_called_once()
        
        # Verify properties
        call_kwargs = mock_collection.data.insert.call_args[1]
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
        mock_client.collections.get.assert_called_once_with("AgiraContext")
        
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
