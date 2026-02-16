"""
Tests for the AI Core Service.
"""

from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase
from django.contrib.auth import get_user_model
import openai

from core.models import AIProvider, AIModel, AIJobsHistory
from core.services.ai import AIRouter, AIResponse
from core.services.ai.schemas import ProviderResponse
from core.services.ai.pricing import calculate_cost
from core.services.exceptions import ServiceNotConfigured

User = get_user_model()


class PricingTestCase(TestCase):
    """Test cost calculation."""
    
    def test_calculate_cost_with_all_data(self):
        """Test cost calculation with complete data."""
        cost = calculate_cost(
            input_tokens=1000,
            output_tokens=500,
            input_price_per_1m=Decimal('10.00'),
            output_price_per_1m=Decimal('30.00')
        )
        
        # (1000/1M * 10) + (500/1M * 30) = 0.01 + 0.015 = 0.025
        self.assertEqual(cost, Decimal('0.025000'))
    
    def test_calculate_cost_with_missing_tokens(self):
        """Test that None is returned when token counts are missing."""
        cost = calculate_cost(
            input_tokens=None,
            output_tokens=500,
            input_price_per_1m=Decimal('10.00'),
            output_price_per_1m=Decimal('30.00')
        )
        self.assertIsNone(cost)
        
        cost = calculate_cost(
            input_tokens=1000,
            output_tokens=None,
            input_price_per_1m=Decimal('10.00'),
            output_price_per_1m=Decimal('30.00')
        )
        self.assertIsNone(cost)
    
    def test_calculate_cost_with_missing_prices(self):
        """Test that None is returned when prices are missing."""
        cost = calculate_cost(
            input_tokens=1000,
            output_tokens=500,
            input_price_per_1m=None,
            output_price_per_1m=Decimal('30.00')
        )
        self.assertIsNone(cost)
        
        cost = calculate_cost(
            input_tokens=1000,
            output_tokens=500,
            input_price_per_1m=Decimal('10.00'),
            output_price_per_1m=None
        )
        self.assertIsNone(cost)


class AIRouterTestCase(TestCase):
    """Test the AI Router."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass',
            name='Test User'
        )
        
        # Create OpenAI provider
        self.openai_provider = AIProvider.objects.create(
            name='Test OpenAI',
            provider_type='OpenAI',
            api_key='test-openai-key',
            active=True
        )
        
        # Create OpenAI model
        self.openai_model = AIModel.objects.create(
            provider=self.openai_provider,
            name='GPT-4 Test',
            model_id='gpt-4',
            input_price_per_1m_tokens=Decimal('10.00'),
            output_price_per_1m_tokens=Decimal('30.00'),
            active=True,
            is_default=True
        )
        
        # Create Gemini provider
        self.gemini_provider = AIProvider.objects.create(
            name='Test Gemini',
            provider_type='Gemini',
            api_key='test-gemini-key',
            active=True
        )
        
        # Create Gemini model
        self.gemini_model = AIModel.objects.create(
            provider=self.gemini_provider,
            name='Gemini Pro Test',
            model_id='gemini-pro',
            input_price_per_1m_tokens=Decimal('0.50'),
            output_price_per_1m_tokens=Decimal('1.50'),
            active=True,
            is_default=True
        )
    
    def test_select_model_with_explicit_provider_and_model(self):
        """Test model selection with explicit provider and model."""
        router = AIRouter()
        provider, model = router._select_model(
            provider_type='OpenAI',
            model_id='gpt-4'
        )
        
        self.assertEqual(provider.id, self.openai_provider.id)
        self.assertEqual(model.id, self.openai_model.id)
    
    def test_select_model_with_provider_only(self):
        """Test model selection with provider type only."""
        router = AIRouter()
        provider, model = router._select_model(provider_type='Gemini')
        
        self.assertEqual(provider.id, self.gemini_provider.id)
        self.assertEqual(model.id, self.gemini_model.id)
    
    def test_select_model_default(self):
        """Test default model selection (should prefer OpenAI)."""
        router = AIRouter()
        provider, model = router._select_model()
        
        # Should select OpenAI as it's checked first
        self.assertEqual(provider.provider_type, 'OpenAI')
    
    def test_select_model_raises_when_not_found(self):
        """Test that ServiceNotConfigured is raised when model not found."""
        router = AIRouter()
        
        with self.assertRaises(ServiceNotConfigured):
            router._select_model(
                provider_type='OpenAI',
                model_id='nonexistent-model'
            )
    
    def test_select_model_raises_when_no_active_models(self):
        """Test that ServiceNotConfigured is raised when no active models."""
        # Deactivate all models
        AIModel.objects.all().update(active=False)
        
        router = AIRouter()
        
        with self.assertRaises(ServiceNotConfigured) as cm:
            router._select_model()
        
        self.assertIn("No active AI model configured", str(cm.exception))
    
    @patch('core.services.ai.openai_provider.openai.OpenAI')
    def test_chat_creates_job_and_logs_success(self, mock_openai_client):
        """Test that chat creates job and logs successful completion."""
        # Mock OpenAI client response
        mock_client_instance = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = 'Test response'
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 100
        mock_response.usage.completion_tokens = 50
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai_client.return_value = mock_client_instance
        
        router = AIRouter()
        
        # Execute chat
        response = router.chat(
            messages=[{'role': 'user', 'content': 'Test prompt'}],
            user=self.user,
            client_ip='127.0.0.1',
            agent='test_agent'
        )
        
        # Check response
        self.assertEqual(response.text, 'Test response')
        self.assertEqual(response.input_tokens, 100)
        self.assertEqual(response.output_tokens, 50)
        self.assertEqual(response.provider, 'OpenAI')
        
        # Check job was created and completed
        jobs = AIJobsHistory.objects.all()
        self.assertEqual(jobs.count(), 1)
        
        job = jobs.first()
        self.assertEqual(job.agent, 'test_agent')
        self.assertEqual(job.user, self.user)
        self.assertEqual(job.client_ip, '127.0.0.1')
        self.assertEqual(job.status, 'Completed')
        self.assertEqual(job.input_tokens, 100)
        self.assertEqual(job.output_tokens, 50)
        self.assertIsNotNone(job.duration_ms)
        
        # Check cost calculation
        expected_cost = Decimal('0.002500')  # (100/1M * 10) + (50/1M * 30)
        self.assertEqual(job.costs, expected_cost)
    
    @patch('core.services.ai.openai_provider.openai.OpenAI')
    def test_chat_logs_error_on_failure(self, mock_openai_client):
        """Test that chat logs errors when API call fails."""
        # Mock OpenAI client to raise exception
        mock_client_instance = Mock()
        mock_client_instance.chat.completions.create.side_effect = Exception('API Error')
        mock_openai_client.return_value = mock_client_instance
        
        router = AIRouter()
        
        # Execute chat and expect exception
        with self.assertRaises(Exception) as cm:
            router.chat(
                messages=[{'role': 'user', 'content': 'Test'}],
                user=self.user
            )
        
        self.assertEqual(str(cm.exception), 'API Error')
        
        # Check job was created with error
        jobs = AIJobsHistory.objects.all()
        self.assertEqual(jobs.count(), 1)
        
        job = jobs.first()
        self.assertEqual(job.status, 'Error')
        self.assertEqual(job.error_message, 'API Error')
        self.assertIsNone(job.input_tokens)
        self.assertIsNone(job.output_tokens)
        self.assertIsNone(job.costs)
    
    @patch('core.services.ai.openai_provider.openai.OpenAI')
    def test_chat_logs_timeout_error(self, mock_openai_client):
        """Test that chat logs timeout errors correctly and sets job to Error status."""
        # Mock OpenAI client to raise APITimeoutError
        mock_client_instance = Mock()
        # Create a proper APITimeoutError with a Mock request
        mock_request = Mock()
        mock_request.url = "https://api.openai.com/v1/chat/completions"
        timeout_error = openai.APITimeoutError(request=mock_request)
        mock_client_instance.chat.completions.create.side_effect = timeout_error
        mock_openai_client.return_value = mock_client_instance
        
        router = AIRouter()
        
        # Execute chat and expect timeout exception
        with self.assertRaises(openai.APITimeoutError) as cm:
            router.chat(
                messages=[{'role': 'user', 'content': 'Test'}],
                user=self.user,
                agent='timeout_test'
            )
        
        self.assertIn('timed out', str(cm.exception).lower())
        
        # Check job was created with error status (NOT Pending)
        jobs = AIJobsHistory.objects.all()
        self.assertEqual(jobs.count(), 1)
        
        job = jobs.first()
        self.assertEqual(job.agent, 'timeout_test')
        self.assertEqual(job.status, 'Error')
        self.assertIn('timed out', job.error_message.lower())
        self.assertIsNone(job.input_tokens)
        self.assertIsNone(job.output_tokens)
        self.assertIsNone(job.costs)
        self.assertIsNotNone(job.duration_ms)
    
    
    @patch('core.services.ai.gemini_provider.genai.Client')
    def test_chat_with_gemini_provider(self, mock_gemini_client):
        """Test chat with Gemini provider."""
        # Mock Gemini client response (no token counts)
        mock_client_instance = Mock()
        mock_response = Mock()
        mock_response.text = 'Gemini response'
        mock_response.usage_metadata = None
        mock_client_instance.models.generate_content.return_value = mock_response
        mock_gemini_client.return_value = mock_client_instance
        
        router = AIRouter()
        
        # Execute chat with explicit Gemini
        response = router.chat(
            messages=[{'role': 'user', 'content': 'Test'}],
            provider_type='Gemini'
        )
        
        self.assertEqual(response.text, 'Gemini response')
        self.assertEqual(response.provider, 'Gemini')
        
        # Check job
        job = AIJobsHistory.objects.first()
        self.assertEqual(job.status, 'Completed')
        self.assertIsNone(job.input_tokens)
        self.assertIsNone(job.output_tokens)
        self.assertIsNone(job.costs)  # No cost without tokens
    
    @patch('core.services.ai.openai_provider.openai.OpenAI')
    def test_generate_shortcut(self, mock_openai_client):
        """Test generate method as shortcut for chat."""
        # Mock OpenAI client
        mock_client_instance = Mock()
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message.content = 'Generated text'
        mock_response.usage = Mock()
        mock_response.usage.prompt_tokens = 50
        mock_response.usage.completion_tokens = 25
        mock_client_instance.chat.completions.create.return_value = mock_response
        mock_openai_client.return_value = mock_client_instance
        
        router = AIRouter()
        
        # Execute generate
        response = router.generate(
            prompt='Simple prompt',
            temperature=0.7,
            max_tokens=100
        )
        
        self.assertEqual(response.text, 'Generated text')
        
        # Verify chat.completions.create was called with proper parameters
        mock_client_instance.chat.completions.create.assert_called_once()
        call_kwargs = mock_client_instance.chat.completions.create.call_args[1]
        self.assertEqual(call_kwargs['messages'], [
            {'role': 'user', 'content': 'Simple prompt'}
        ])
        self.assertEqual(call_kwargs['temperature'], 0.7)
        self.assertEqual(call_kwargs['max_tokens'], 100)
    
    
    def test_provider_instance_creation(self):
        """Test creating provider instances from DB config."""
        router = AIRouter()
        
        # Test OpenAI provider creation
        provider_instance = router._get_provider_instance(self.openai_provider)
        self.assertEqual(provider_instance.provider_type, 'OpenAI')
        self.assertEqual(provider_instance.api_key, 'test-openai-key')
        
        # Test Gemini provider creation
        provider_instance = router._get_provider_instance(self.gemini_provider)
        self.assertEqual(provider_instance.provider_type, 'Gemini')
        self.assertEqual(provider_instance.api_key, 'test-gemini-key')
    
    def test_provider_instance_raises_for_unsupported_type(self):
        """Test that unsupported provider type raises error."""
        # Create unsupported provider
        unsupported = AIProvider.objects.create(
            name='Unsupported',
            provider_type='Claude',  # Not implemented yet
            api_key='test-key',
            active=True
        )
        
        router = AIRouter()
        
        with self.assertRaises(ServiceNotConfigured) as cm:
            router._get_provider_instance(unsupported)
        
        self.assertIn('not supported', str(cm.exception))


class OpenAIProviderTestCase(TestCase):
    """Test OpenAI provider implementation."""
    
    @patch('core.services.ai.openai_provider.openai.OpenAI')
    def test_openai_client_timeout_default(self, mock_openai_class):
        """Test that OpenAI client is initialized with default timeout of 1200s."""
        from core.services.ai.openai_provider import OpenAIProvider
        
        # Create provider without timeout parameter
        provider = OpenAIProvider(api_key='test-key')
        
        # Verify OpenAI was called with timeout=1200
        mock_openai_class.assert_called_once()
        call_kwargs = mock_openai_class.call_args[1]
        self.assertEqual(call_kwargs['timeout'], 1200)
        self.assertEqual(call_kwargs['api_key'], 'test-key')
    
    @patch('core.services.ai.openai_provider.openai.OpenAI')
    def test_openai_client_timeout_custom(self, mock_openai_class):
        """Test that OpenAI client can use custom timeout."""
        from core.services.ai.openai_provider import OpenAIProvider
        
        # Create provider with custom timeout
        provider = OpenAIProvider(api_key='test-key', timeout=600)
        
        # Verify OpenAI was called with custom timeout
        mock_openai_class.assert_called_once()
        call_kwargs = mock_openai_class.call_args[1]
        self.assertEqual(call_kwargs['timeout'], 600)
    
    @patch('core.services.ai.openai_provider.openai.OpenAI')
    def test_openai_client_with_organization(self, mock_openai_class):
        """Test that OpenAI client is initialized with organization and timeout."""
        from core.services.ai.openai_provider import OpenAIProvider
        
        # Create provider with organization
        provider = OpenAIProvider(api_key='test-key', organization_id='org-123')
        
        # Verify OpenAI was called with organization and timeout
        mock_openai_class.assert_called_once()
        call_kwargs = mock_openai_class.call_args[1]
        self.assertEqual(call_kwargs['timeout'], 1200)
        self.assertEqual(call_kwargs['api_key'], 'test-key')
        self.assertEqual(call_kwargs['organization'], 'org-123')
