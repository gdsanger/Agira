"""
Tests for AI Provider views
"""

from unittest.mock import patch, Mock
from django.test import TestCase, Client
from django.urls import reverse
from core.models import AIProvider, AIModel


class AIProviderFetchModelsTestCase(TestCase):
    """Test cases for AI provider fetch models functionality"""
    
    def setUp(self):
        """Set up test data"""
        from core.models import User
        
        self.client = Client()
        
        # Create and login test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.client.force_login(self.user)
        
        # Create OpenAI provider
        self.openai_provider = AIProvider.objects.create(
            name='Test OpenAI',
            provider_type='OpenAI',
            api_key='test-openai-key',
            active=True
        )
        
        # Create Gemini provider
        self.gemini_provider = AIProvider.objects.create(
            name='Test Gemini',
            provider_type='Gemini',
            api_key='test-gemini-key',
            active=True
        )
        
        # Create Claude provider
        self.claude_provider = AIProvider.objects.create(
            name='Test Claude',
            provider_type='Claude',
            api_key='test-claude-key',
            active=True
        )
    
    @patch('core.views.openai.OpenAI')
    def test_fetch_openai_models_creates_new_models(self, mock_openai):
        """Test that fetching OpenAI models creates new AIModel records"""
        # Mock OpenAI API response
        mock_model1 = Mock()
        mock_model1.id = 'gpt-4'
        
        mock_model2 = Mock()
        mock_model2.id = 'gpt-3.5-turbo'
        
        mock_model3 = Mock()
        mock_model3.id = 'o1-preview'
        
        mock_model4 = Mock()
        mock_model4.id = 'gpt-4o-2024-05-13'
        
        # Add a non-GPT model that should be filtered out
        mock_model5 = Mock()
        mock_model5.id = 'text-embedding-ada-002'
        
        mock_models_list = Mock()
        mock_models_list.data = [mock_model1, mock_model2, mock_model3, mock_model4, mock_model5]
        
        mock_client = Mock()
        mock_client.models.list.return_value = mock_models_list
        mock_openai.return_value = mock_client
        
        # Fetch models
        response = self.client.post(
            reverse('ai-provider-fetch-models', kwargs={'id': self.openai_provider.id})
        )
        
        # Check response
        self.assertEqual(response.status_code, 200)
        
        # Check models were created in database
        models = AIModel.objects.filter(provider=self.openai_provider)
        self.assertEqual(models.count(), 4)
        
        model_ids = [m.model_id for m in models]
        self.assertIn('gpt-4', model_ids)
        self.assertIn('gpt-3.5-turbo', model_ids)
        self.assertIn('o1-preview', model_ids)
        self.assertIn('gpt-4o-2024-05-13', model_ids)
        # Embedding model should be filtered out
        self.assertNotIn('text-embedding-ada-002', model_ids)
        
        # Check default values - NEW MODELS SHOULD BE INACTIVE
        for model in models:
            self.assertFalse(model.active)  # Changed from True to False
            self.assertFalse(model.is_default)
            self.assertIsNone(model.input_price_per_1m_tokens)
            self.assertIsNone(model.output_price_per_1m_tokens)
    
    @patch('core.views.openai.OpenAI')
    def test_fetch_openai_models_skips_existing_models(self, mock_openai):
        """Test that fetching models skips already existing models"""
        # Create an existing model
        existing_model = AIModel.objects.create(
            provider=self.openai_provider,
            name='gpt-4',
            model_id='gpt-4',
            active=True,
            is_default=False
        )
        
        # Mock OpenAI API response with same model
        mock_model = Mock()
        mock_model.id = 'gpt-4'
        
        mock_models_list = Mock()
        mock_models_list.data = [mock_model]
        
        mock_client = Mock()
        mock_client.models.list.return_value = mock_models_list
        mock_openai.return_value = mock_client
        
        # Fetch models
        response = self.client.post(
            reverse('ai-provider-fetch-models', kwargs={'id': self.openai_provider.id})
        )
        
        # Check response - now returns HTML not JSON
        self.assertEqual(response.status_code, 200)
        
        # Check that only one model exists
        models = AIModel.objects.filter(provider=self.openai_provider)
        self.assertEqual(models.count(), 1)
        self.assertEqual(models.first().id, existing_model.id)
    
    @patch('google.genai.Client')
    def test_fetch_gemini_models_creates_models_from_api(self, mock_genai_client):
        """Test that fetching Gemini models fetches from API and creates models"""
        # Mock Gemini API response
        mock_model1 = Mock()
        mock_model1.name = 'models/gemini-1.5-pro'
        mock_model1.display_name = 'Gemini 1.5 Pro'
        mock_model1.supported_generation_methods = ['generateContent']
        
        mock_model2 = Mock()
        mock_model2.name = 'models/gemini-1.5-flash'
        mock_model2.display_name = 'Gemini 1.5 Flash'
        mock_model2.supported_generation_methods = ['generateContent']
        
        mock_model3 = Mock()
        mock_model3.name = 'models/gemini-2.0-flash-exp'
        mock_model3.display_name = 'Gemini 2.0 Flash'
        mock_model3.supported_generation_methods = ['generateContent']
        
        # Add an embedding model that should be filtered out
        mock_embedding_model = Mock()
        mock_embedding_model.name = 'models/text-embedding-004'
        mock_embedding_model.display_name = 'Text Embedding 004'
        mock_embedding_model.supported_generation_methods = ['embedContent']
        
        mock_client = Mock()
        mock_client.models.list.return_value = [mock_model1, mock_model2, mock_model3, mock_embedding_model]
        mock_genai_client.return_value = mock_client
        
        response = self.client.post(
            reverse('ai-provider-fetch-models', kwargs={'id': self.gemini_provider.id})
        )
        
        # Check response - now returns HTML not JSON
        self.assertEqual(response.status_code, 200)
        
        # Check models were created
        models = AIModel.objects.filter(provider=self.gemini_provider)
        self.assertEqual(models.count(), 3)
        
        model_ids = [m.model_id for m in models]
        self.assertIn('gemini-1.5-pro', model_ids)
        self.assertIn('gemini-1.5-flash', model_ids)
        self.assertIn('gemini-2.0-flash-exp', model_ids)
        # Embedding model should not be included
        self.assertNotIn('text-embedding-004', model_ids)
    
    def test_fetch_claude_models_creates_predefined_models(self):
        """Test that fetching Claude models creates predefined model list"""
        response = self.client.post(
            reverse('ai-provider-fetch-models', kwargs={'id': self.claude_provider.id})
        )
        
        # Check response - now returns HTML not JSON
        self.assertEqual(response.status_code, 200)
        
        # Check models were created
        models = AIModel.objects.filter(provider=self.claude_provider)
        self.assertEqual(models.count(), 4)
        
        model_ids = [m.model_id for m in models]
        self.assertIn('claude-3-5-sonnet-20241022', model_ids)
        self.assertIn('claude-3-opus-20240229', model_ids)
        self.assertIn('claude-3-sonnet-20240229', model_ids)
        self.assertIn('claude-3-haiku-20240307', model_ids)
    
    @patch('core.views.openai.OpenAI')
    def test_fetch_models_handles_api_errors(self, mock_openai):
        """Test that API errors are handled gracefully"""
        # Mock OpenAI to raise exception
        mock_client = Mock()
        mock_client.models.list.side_effect = Exception('API Error')
        mock_openai.return_value = mock_client
        
        response = self.client.post(
            reverse('ai-provider-fetch-models', kwargs={'id': self.openai_provider.id})
        )
        
        # Check error response - now returns HTTP error with text, not JSON
        self.assertEqual(response.status_code, 400)
        
        # Check no models were created
        models = AIModel.objects.filter(provider=self.openai_provider)
        self.assertEqual(models.count(), 0)
    
    def test_fetch_models_with_invalid_provider_id(self):
        """Test that invalid provider ID returns 404"""
        response = self.client.post(
            reverse('ai-provider-fetch-models', kwargs={'id': 99999})
        )
        
        self.assertEqual(response.status_code, 404)
    
    @patch('core.views.openai.OpenAI')
    def test_fetch_models_mixed_new_and_existing(self, mock_openai):
        """Test fetching when some models exist and some are new"""
        # Create an existing model
        AIModel.objects.create(
            provider=self.openai_provider,
            name='gpt-4',
            model_id='gpt-4',
            active=True
        )
        
        # Mock OpenAI API response with existing and new models
        mock_model1 = Mock()
        mock_model1.id = 'gpt-4'  # Existing
        
        mock_model2 = Mock()
        mock_model2.id = 'gpt-3.5-turbo'  # New
        
        mock_models_list = Mock()
        mock_models_list.data = [mock_model1, mock_model2]
        
        mock_client = Mock()
        mock_client.models.list.return_value = mock_models_list
        mock_openai.return_value = mock_client
        
        response = self.client.post(
            reverse('ai-provider-fetch-models', kwargs={'id': self.openai_provider.id})
        )
        
        # Check response - now returns HTML not JSON
        self.assertEqual(response.status_code, 200)
        
        # Check total models count
        models = AIModel.objects.filter(provider=self.openai_provider)
        self.assertEqual(models.count(), 2)
    
    @patch('core.views.openai.OpenAI')
    def test_fetch_models_deactivates_removed_models(self, mock_openai):
        """Test that models no longer in API are deactivated"""
        # Create existing models
        model1 = AIModel.objects.create(
            provider=self.openai_provider,
            name='gpt-4',
            model_id='gpt-4',
            active=True
        )
        model2 = AIModel.objects.create(
            provider=self.openai_provider,
            name='gpt-3.5-turbo',
            model_id='gpt-3.5-turbo',
            active=True
        )
        model3 = AIModel.objects.create(
            provider=self.openai_provider,
            name='old-model',
            model_id='old-model',
            active=True
        )
        
        # Mock OpenAI API response - only returns gpt-4 and gpt-3.5-turbo
        # old-model is no longer available
        mock_model1 = Mock()
        mock_model1.id = 'gpt-4'
        
        mock_model2 = Mock()
        mock_model2.id = 'gpt-3.5-turbo'
        
        mock_models_list = Mock()
        mock_models_list.data = [mock_model1, mock_model2]
        
        mock_client = Mock()
        mock_client.models.list.return_value = mock_models_list
        mock_openai.return_value = mock_client
        
        response = self.client.post(
            reverse('ai-provider-fetch-models', kwargs={'id': self.openai_provider.id})
        )
        
        # Check response
        self.assertEqual(response.status_code, 200)
        
        # Refresh models from database
        model1.refresh_from_db()
        model2.refresh_from_db()
        model3.refresh_from_db()
        
        # Check that gpt-4 and gpt-3.5-turbo are still active
        self.assertTrue(model1.active)
        self.assertTrue(model2.active)
        
        # Check that old-model was deactivated
        self.assertFalse(model3.active)
        
        # Check that the response contains deactivation info
        self.assertContains(response, 'old-model')
        self.assertContains(response, 'deactivated')


class AIModelInlineEditingTestCase(TestCase):
    """Test cases for inline editing of AI models"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test provider
        self.provider = AIProvider.objects.create(
            name='Test Provider',
            provider_type='OpenAI',
            api_key='test-key',
            active=True
        )
        
        # Create test model
        self.model = AIModel.objects.create(
            provider=self.provider,
            name='Test Model',
            model_id='test-model',
            input_price_per_1m_tokens=1.50,
            output_price_per_1m_tokens=2.00,
            active=True,
            is_default=False
        )
    
    def test_update_input_price_field(self):
        """Test updating input price via HTMX"""
        response = self.client.post(
            reverse('ai-model-update-field', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            }),
            {
                'field': 'input_price_per_1m_tokens',
                'value': '2.50'
            }
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Check model was updated
        self.model.refresh_from_db()
        self.assertEqual(float(self.model.input_price_per_1m_tokens), 2.50)
    
    def test_update_output_price_field(self):
        """Test updating output price via HTMX"""
        response = self.client.post(
            reverse('ai-model-update-field', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            }),
            {
                'field': 'output_price_per_1m_tokens',
                'value': '3.00'
            }
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Check model was updated
        self.model.refresh_from_db()
        self.assertEqual(float(self.model.output_price_per_1m_tokens), 3.00)
    
    def test_update_field_with_empty_value(self):
        """Test updating field with empty value sets it to None"""
        response = self.client.post(
            reverse('ai-model-update-field', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            }),
            {
                'field': 'input_price_per_1m_tokens',
                'value': ''
            }
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Check model was updated
        self.model.refresh_from_db()
        self.assertIsNone(self.model.input_price_per_1m_tokens)
    
    def test_update_invalid_field(self):
        """Test that updating invalid field returns error"""
        response = self.client.post(
            reverse('ai-model-update-field', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            }),
            {
                'field': 'invalid_field',
                'value': '1.00'
            }
        )
        
        self.assertEqual(response.status_code, 400)
    
    def test_update_field_with_invalid_decimal(self):
        """Test that updating field with invalid decimal returns error"""
        response = self.client.post(
            reverse('ai-model-update-field', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            }),
            {
                'field': 'input_price_per_1m_tokens',
                'value': 'not-a-number'
            }
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Invalid price value', response.content)
    
    def test_update_field_with_negative_price(self):
        """Test that updating field with negative price returns error"""
        response = self.client.post(
            reverse('ai-model-update-field', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            }),
            {
                'field': 'input_price_per_1m_tokens',
                'value': '-1.00'
            }
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'cannot be negative', response.content)
    
    def test_toggle_active_status(self):
        """Test toggling active status"""
        # Model is initially active
        self.assertTrue(self.model.active)
        
        response = self.client.post(
            reverse('ai-model-toggle-active', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            })
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Check model was toggled
        self.model.refresh_from_db()
        self.assertFalse(self.model.active)
        
        # Toggle again
        response = self.client.post(
            reverse('ai-model-toggle-active', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            })
        )
        
        self.assertEqual(response.status_code, 200)
        
        # Check model was toggled back
        self.model.refresh_from_db()
        self.assertTrue(self.model.active)


class AIJobsHistoryViewTestCase(TestCase):
    """Test cases for AI Jobs History view"""
    
    def setUp(self):
        """Set up test data"""
        self.client = Client()
        
        # Create test provider and model
        self.provider = AIProvider.objects.create(
            name='Test Provider',
            provider_type='OpenAI',
            api_key='test-key',
            active=True
        )
        
        self.model = AIModel.objects.create(
            provider=self.provider,
            name='gpt-4',
            model_id='gpt-4',
            active=True,
            is_default=True
        )
    
    def test_ai_jobs_history_view_loads(self):
        """Test that the AI Jobs History view loads successfully"""
        from core.models import AIJobsHistory, User, AIJobStatus
        
        # Create a test user
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        # Create some test job history entries
        AIJobsHistory.objects.create(
            agent='core.ai',
            user=user,
            provider=self.provider,
            model=self.model,
            status=AIJobStatus.COMPLETED,
            input_tokens=100,
            output_tokens=50,
            costs=0.001500,
            duration_ms=1234
        )
        
        AIJobsHistory.objects.create(
            agent='core.ai',
            user=user,
            provider=self.provider,
            model=self.model,
            status=AIJobStatus.ERROR,
            input_tokens=50,
            output_tokens=0,
            costs=0.000500,
            duration_ms=500,
            error_message='Test error'
        )
        
        # Get the view
        response = self.client.get(reverse('ai-jobs-history'))
        
        # Check response
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'ai_jobs_history.html')
        
        # Check context contains page_obj
        self.assertIn('page_obj', response.context)
        
        # Check pagination (should have 2 jobs on page 1)
        page_obj = response.context['page_obj']
        self.assertEqual(len(page_obj), 2)
    
    def test_ai_jobs_history_filtering_by_status(self):
        """Test filtering jobs by status"""
        from core.models import AIJobsHistory, User, AIJobStatus
        
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        # Create jobs with different statuses
        AIJobsHistory.objects.create(
            agent='core.ai',
            user=user,
            provider=self.provider,
            model=self.model,
            status=AIJobStatus.COMPLETED,
            input_tokens=100,
            output_tokens=50,
            costs=0.001500,
            duration_ms=1234
        )
        
        AIJobsHistory.objects.create(
            agent='core.ai',
            user=user,
            provider=self.provider,
            model=self.model,
            status=AIJobStatus.ERROR,
            input_tokens=50,
            output_tokens=0,
            costs=0.000500,
            duration_ms=500
        )
        
        # Filter by completed status
        response = self.client.get(reverse('ai-jobs-history') + '?status=Completed')
        
        self.assertEqual(response.status_code, 200)
        page_obj = response.context['page_obj']
        
        # Should only have 1 completed job
        self.assertEqual(len(page_obj), 1)
        self.assertEqual(page_obj[0].status, AIJobStatus.COMPLETED)
    
    def test_ai_jobs_history_pagination(self):
        """Test pagination with 25 items per page"""
        from core.models import AIJobsHistory, User, AIJobStatus
        
        user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        
        # Create 30 jobs to test pagination
        for i in range(30):
            AIJobsHistory.objects.create(
                agent='core.ai',
                user=user,
                provider=self.provider,
                model=self.model,
                status=AIJobStatus.COMPLETED,
                input_tokens=100,
                output_tokens=50,
                costs=0.001500,
                duration_ms=1234
            )
        
        # Get first page
        response = self.client.get(reverse('ai-jobs-history'))
        page_obj = response.context['page_obj']
        
        # Should have 25 items on first page
        self.assertEqual(len(page_obj), 25)
        self.assertTrue(page_obj.has_next())
        self.assertFalse(page_obj.has_previous())
        
        # Get second page
        response = self.client.get(reverse('ai-jobs-history') + '?page=2')
        page_obj = response.context['page_obj']
        
        # Should have 5 items on second page
        self.assertEqual(len(page_obj), 5)
        self.assertFalse(page_obj.has_next())
        self.assertTrue(page_obj.has_previous())


class AIProviderUpdateTestCase(TestCase):
    """Test cases for AI Provider update functionality"""
    
    def setUp(self):
        """Set up test data"""
        from core.models import User
        
        self.client = Client()
        
        # Create and login test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass'
        )
        self.client.force_login(self.user)
        
        # Create test provider with known API key
        self.provider = AIProvider.objects.create(
            name='Test Provider',
            provider_type='OpenAI',
            api_key='original-secret-key-12345',
            organization_id='org-123',
            active=True
        )
    
    def test_provider_update_preserves_api_key_when_masked(self):
        """Test that updating provider with masked API key preserves the original key"""
        original_key = self.provider.api_key
        
        # Update provider with masked API key (as shown in the UI)
        response = self.client.post(
            reverse('ai-provider-update', kwargs={'id': self.provider.id}),
            {
                'name': 'Updated Provider Name',
                'provider_type': 'OpenAI',
                'api_key': '********************',  # Masked value from UI
                'organization_id': 'org-123',
                'active': 'on'
            }
        )
        
        # Check response is successful
        self.assertEqual(response.status_code, 200)
        
        # Verify API key was NOT changed
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.api_key, original_key)
        
        # Verify other fields were updated
        self.assertEqual(self.provider.name, 'Updated Provider Name')
    
    def test_provider_update_preserves_api_key_when_empty(self):
        """Test that updating provider with empty API key preserves the original key"""
        original_key = self.provider.api_key
        
        # Update provider with empty API key
        response = self.client.post(
            reverse('ai-provider-update', kwargs={'id': self.provider.id}),
            {
                'name': 'Updated Provider Name',
                'provider_type': 'OpenAI',
                'api_key': '',  # Empty value
                'organization_id': 'org-123',
                'active': 'on'
            }
        )
        
        # Check response is successful
        self.assertEqual(response.status_code, 200)
        
        # Verify API key was NOT changed
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.api_key, original_key)
    
    def test_provider_update_changes_api_key_when_new_key_provided(self):
        """Test that updating provider with new API key actually updates it"""
        original_key = self.provider.api_key
        new_key = 'new-secret-key-67890'
        
        # Update provider with new API key
        response = self.client.post(
            reverse('ai-provider-update', kwargs={'id': self.provider.id}),
            {
                'name': 'Test Provider',
                'provider_type': 'OpenAI',
                'api_key': new_key,
                'organization_id': 'org-123',
                'active': 'on'
            }
        )
        
        # Check response is successful
        self.assertEqual(response.status_code, 200)
        
        # Verify API key WAS changed
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.api_key, new_key)
        self.assertNotEqual(self.provider.api_key, original_key)
