"""
Tests for RBAC (Role-Based Access Control) on AIProvider and AIAgent
"""

from django.test import TestCase, Client
from django.urls import reverse
from core.models import AIProvider, AIModel, User
from core.services.agents import AgentService
import os
import tempfile


class AIProviderRBACTestCase(TestCase):
    """Test RBAC for AIProvider operations"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()

        # Create admin user (superuser)
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='adminpass',
            is_superuser=True
        )

        # Create non-admin user (regular user)
        self.regular_user = User.objects.create_user(
            username='regular',
            email='regular@example.com',
            password='regularpass',
            is_superuser=False
        )

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
            model_id='gpt-4',
            active=True
        )

    # AIProvider READ tests (should be allowed for everyone)

    def test_regular_user_can_list_providers(self):
        """Non-admin can list AIProviders"""
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse('ai-providers'))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_list_providers(self):
        """Admin can list AIProviders"""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('ai-providers'))
        self.assertEqual(response.status_code, 200)

    def test_regular_user_can_view_provider_detail(self):
        """Non-admin can view AIProvider details"""
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse('ai-provider-detail', kwargs={'id': self.provider.id}))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_view_provider_detail(self):
        """Admin can view AIProvider details"""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('ai-provider-detail', kwargs={'id': self.provider.id}))
        self.assertEqual(response.status_code, 200)

    # AIProvider CREATE tests

    def test_regular_user_cannot_create_provider_get(self):
        """Non-admin cannot access create provider page"""
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse('ai-provider-create'))
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)

    def test_regular_user_cannot_create_provider_post(self):
        """Non-admin cannot create AIProvider via POST"""
        self.client.force_login(self.regular_user)
        response = self.client.post(reverse('ai-provider-create'), {
            'name': 'New Provider',
            'provider_type': 'OpenAI',
            'api_key': 'new-key',
            'active': 'on'
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)
        # Verify no new provider was created
        self.assertEqual(AIProvider.objects.filter(name='New Provider').count(), 0)

    def test_admin_can_create_provider(self):
        """Admin can create AIProvider"""
        self.client.force_login(self.admin_user)
        initial_count = AIProvider.objects.count()
        response = self.client.post(reverse('ai-provider-create'), {
            'name': 'New Provider',
            'provider_type': 'OpenAI',
            'api_key': 'new-key',
            'active': 'on'
        })
        # Should redirect to detail page
        self.assertIn(response.status_code, [200, 302])
        # Verify provider was created
        self.assertEqual(AIProvider.objects.count(), initial_count + 1)
        self.assertTrue(AIProvider.objects.filter(name='New Provider').exists())

    # AIProvider UPDATE tests

    def test_regular_user_cannot_update_provider(self):
        """Non-admin cannot update AIProvider"""
        self.client.force_login(self.regular_user)
        response = self.client.post(reverse('ai-provider-update', kwargs={'id': self.provider.id}), {
            'name': 'Updated Name',
            'provider_type': 'OpenAI',
            'api_key': 'test-key',
            'active': 'on'
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)
        # Verify provider was not updated
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.name, 'Test Provider')

    def test_admin_can_update_provider(self):
        """Admin can update AIProvider"""
        self.client.force_login(self.admin_user)
        response = self.client.post(reverse('ai-provider-update', kwargs={'id': self.provider.id}), {
            'name': 'Updated Name',
            'provider_type': 'OpenAI',
            'api_key': 'test-key',
            'active': 'on'
        })
        self.assertEqual(response.status_code, 200)
        # Verify provider was updated
        self.provider.refresh_from_db()
        self.assertEqual(self.provider.name, 'Updated Name')

    # AIProvider DELETE tests

    def test_regular_user_cannot_delete_provider(self):
        """Non-admin cannot delete AIProvider"""
        self.client.force_login(self.regular_user)
        provider_id = self.provider.id
        response = self.client.post(reverse('ai-provider-delete', kwargs={'id': provider_id}))
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)
        # Verify provider still exists
        self.assertTrue(AIProvider.objects.filter(id=provider_id).exists())

    def test_admin_can_delete_provider(self):
        """Admin can delete AIProvider"""
        self.client.force_login(self.admin_user)
        provider_id = self.provider.id
        response = self.client.post(reverse('ai-provider-delete', kwargs={'id': provider_id}))
        self.assertIn(response.status_code, [200, 302])
        # Verify provider was deleted
        self.assertFalse(AIProvider.objects.filter(id=provider_id).exists())

    # AIProvider FETCH MODELS tests

    def test_regular_user_cannot_fetch_models(self):
        """Non-admin cannot fetch models from provider API"""
        self.client.force_login(self.regular_user)
        response = self.client.post(reverse('ai-provider-fetch-models', kwargs={'id': self.provider.id}))
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)


class AIModelRBACTestCase(TestCase):
    """Test RBAC for AIModel operations"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()

        # Create admin user
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='adminpass',
            is_superuser=True
        )

        # Create non-admin user
        self.regular_user = User.objects.create_user(
            username='regular',
            email='regular@example.com',
            password='regularpass',
            is_superuser=False
        )

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
            model_id='gpt-4',
            active=True
        )

    # AIModel CREATE tests

    def test_regular_user_cannot_create_model(self):
        """Non-admin cannot create AIModel"""
        self.client.force_login(self.regular_user)
        response = self.client.post(
            reverse('ai-model-create', kwargs={'provider_id': self.provider.id}),
            {
                'name': 'New Model',
                'model_id': 'gpt-3.5-turbo',
                'active': 'on'
            }
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)
        # Verify no new model was created
        self.assertEqual(AIModel.objects.filter(model_id='gpt-3.5-turbo').count(), 0)

    def test_admin_can_create_model(self):
        """Admin can create AIModel"""
        self.client.force_login(self.admin_user)
        initial_count = AIModel.objects.count()
        response = self.client.post(
            reverse('ai-model-create', kwargs={'provider_id': self.provider.id}),
            {
                'name': 'New Model',
                'model_id': 'gpt-3.5-turbo',
                'active': 'on'
            }
        )
        self.assertEqual(response.status_code, 200)
        # Verify model was created
        self.assertEqual(AIModel.objects.count(), initial_count + 1)
        self.assertTrue(AIModel.objects.filter(model_id='gpt-3.5-turbo').exists())

    # AIModel UPDATE tests

    def test_regular_user_cannot_update_model(self):
        """Non-admin cannot update AIModel"""
        self.client.force_login(self.regular_user)
        response = self.client.post(
            reverse('ai-model-update', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            }),
            {
                'name': 'Updated Model',
                'model_id': 'gpt-4',
                'active': 'on'
            }
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)
        # Verify model was not updated
        self.model.refresh_from_db()
        self.assertEqual(self.model.name, 'Test Model')

    def test_admin_can_update_model(self):
        """Admin can update AIModel"""
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('ai-model-update', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            }),
            {
                'name': 'Updated Model',
                'model_id': 'gpt-4',
                'active': 'on'
            }
        )
        self.assertEqual(response.status_code, 200)
        # Verify model was updated
        self.model.refresh_from_db()
        self.assertEqual(self.model.name, 'Updated Model')

    # AIModel DELETE tests

    def test_regular_user_cannot_delete_model(self):
        """Non-admin cannot delete AIModel"""
        self.client.force_login(self.regular_user)
        model_id = self.model.id
        response = self.client.post(
            reverse('ai-model-delete', kwargs={
                'provider_id': self.provider.id,
                'model_id': model_id
            })
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)
        # Verify model still exists
        self.assertTrue(AIModel.objects.filter(id=model_id).exists())

    def test_admin_can_delete_model(self):
        """Admin can delete AIModel"""
        self.client.force_login(self.admin_user)
        model_id = self.model.id
        response = self.client.post(
            reverse('ai-model-delete', kwargs={
                'provider_id': self.provider.id,
                'model_id': model_id
            })
        )
        self.assertEqual(response.status_code, 200)
        # Verify model was deleted
        self.assertFalse(AIModel.objects.filter(id=model_id).exists())

    # AIModel UPDATE FIELD tests

    def test_regular_user_cannot_update_model_field(self):
        """Non-admin cannot update individual AIModel field"""
        self.client.force_login(self.regular_user)
        response = self.client.post(
            reverse('ai-model-update-field', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            }),
            {
                'field': 'input_price_per_1m_tokens',
                'value': '5.0'
            }
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)

    def test_admin_can_update_model_field(self):
        """Admin can update individual AIModel field"""
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('ai-model-update-field', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            }),
            {
                'field': 'input_price_per_1m_tokens',
                'value': '5.0'
            }
        )
        self.assertEqual(response.status_code, 200)

    # AIModel TOGGLE ACTIVE tests

    def test_regular_user_cannot_toggle_model_active(self):
        """Non-admin cannot toggle AIModel active status"""
        self.client.force_login(self.regular_user)
        original_active = self.model.active
        response = self.client.post(
            reverse('ai-model-toggle-active', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            })
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)
        # Verify active status unchanged
        self.model.refresh_from_db()
        self.assertEqual(self.model.active, original_active)

    def test_admin_can_toggle_model_active(self):
        """Admin can toggle AIModel active status"""
        self.client.force_login(self.admin_user)
        original_active = self.model.active
        response = self.client.post(
            reverse('ai-model-toggle-active', kwargs={
                'provider_id': self.provider.id,
                'model_id': self.model.id
            })
        )
        self.assertEqual(response.status_code, 200)
        # Verify active status toggled
        self.model.refresh_from_db()
        self.assertEqual(self.model.active, not original_active)


class AIAgentRBACTestCase(TestCase):
    """Test RBAC for AIAgent operations"""

    def setUp(self):
        """Set up test data"""
        self.client = Client()

        # Create admin user
        self.admin_user = User.objects.create_user(
            username='admin',
            email='admin@example.com',
            password='adminpass',
            is_superuser=True
        )

        # Create non-admin user
        self.regular_user = User.objects.create_user(
            username='regular',
            email='regular@example.com',
            password='regularpass',
            is_superuser=False
        )

        # Create test provider for agent
        self.provider = AIProvider.objects.create(
            name='Test Provider',
            provider_type='OpenAI',
            api_key='test-key',
            active=True
        )

        self.model = AIModel.objects.create(
            provider=self.provider,
            name='Test Model',
            model_id='gpt-4',
            active=True
        )

        # Create test agent
        self.agent_service = AgentService()
        self.test_agent_filename = 'test-agent.yml'
        self.agent_data = {
            'name': 'Test Agent',
            'description': 'A test agent',
            'provider': 'openai',
            'model': 'gpt-4',
            'role': 'Test role',
            'task': 'Test task',
        }
        self.agent_service.save_agent(self.test_agent_filename, self.agent_data)

    def tearDown(self):
        """Clean up test agent files"""
        try:
            self.agent_service.delete_agent(self.test_agent_filename)
        except:
            pass

    # AIAgent READ tests (should be allowed for everyone)

    def test_regular_user_can_list_agents(self):
        """Non-admin can list AIAgents"""
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse('agents'))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_list_agents(self):
        """Admin can list AIAgents"""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('agents'))
        self.assertEqual(response.status_code, 200)

    def test_regular_user_can_view_agent_detail(self):
        """Non-admin can view AIAgent details"""
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse('agent-detail', kwargs={'filename': self.test_agent_filename}))
        self.assertEqual(response.status_code, 200)

    def test_admin_can_view_agent_detail(self):
        """Admin can view AIAgent details"""
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse('agent-detail', kwargs={'filename': self.test_agent_filename}))
        self.assertEqual(response.status_code, 200)

    # AIAgent CREATE tests

    def test_regular_user_cannot_access_create_agent_page(self):
        """Non-admin cannot access create agent page"""
        self.client.force_login(self.regular_user)
        response = self.client.get(reverse('agent-create'))
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)

    def test_regular_user_cannot_create_agent(self):
        """Non-admin cannot create AIAgent"""
        self.client.force_login(self.regular_user)
        new_agent_name = 'New Test Agent'
        response = self.client.post(reverse('agent-create-save'), {
            'name': new_agent_name,
            'description': 'New agent description',
            'provider': 'openai',
            'model': 'gpt-4',
            'role': 'New role',
            'task': 'New task',
        })
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)
        # Verify agent was not created
        agents = self.agent_service.list_agents()
        self.assertFalse(any(a['name'] == new_agent_name for a in agents))

    def test_admin_can_create_agent(self):
        """Admin can create AIAgent"""
        self.client.force_login(self.admin_user)
        new_agent_name = 'New Test Agent'
        response = self.client.post(reverse('agent-create-save'), {
            'name': new_agent_name,
            'description': 'New agent description',
            'provider': 'openai',
            'model': 'gpt-4',
            'role': 'New role',
            'task': 'New task',
        })
        # Should redirect to detail page
        self.assertIn(response.status_code, [200, 302])
        # Verify agent was created
        agents = self.agent_service.list_agents()
        self.assertTrue(any(a['name'] == new_agent_name for a in agents))
        # Clean up
        for agent in agents:
            if agent['name'] == new_agent_name:
                self.agent_service.delete_agent(agent['filename'])

    # AIAgent UPDATE tests

    def test_regular_user_cannot_update_agent(self):
        """Non-admin cannot update AIAgent"""
        self.client.force_login(self.regular_user)
        response = self.client.post(
            reverse('agent-save', kwargs={'filename': self.test_agent_filename}),
            {
                'name': 'Updated Agent',
                'description': 'Updated description',
                'provider': 'openai',
                'model': 'gpt-4',
                'role': 'Updated role',
                'task': 'Updated task',
            }
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)
        # Verify agent was not updated
        agent = self.agent_service.get_agent(self.test_agent_filename)
        self.assertEqual(agent['name'], 'Test Agent')

    def test_admin_can_update_agent(self):
        """Admin can update AIAgent"""
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('agent-save', kwargs={'filename': self.test_agent_filename}),
            {
                'name': 'Updated Agent',
                'description': 'Updated description',
                'provider': 'openai',
                'model': 'gpt-4',
                'role': 'Updated role',
                'task': 'Updated task',
            }
        )
        self.assertIn(response.status_code, [200, 302])
        # Verify agent was updated
        agent = self.agent_service.get_agent(self.test_agent_filename)
        self.assertEqual(agent['name'], 'Updated Agent')

    # AIAgent DELETE tests

    def test_regular_user_cannot_delete_agent(self):
        """Non-admin cannot delete AIAgent"""
        self.client.force_login(self.regular_user)
        response = self.client.post(
            reverse('agent-delete', kwargs={'filename': self.test_agent_filename})
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn(b'Forbidden', response.content)
        # Verify agent still exists
        agent = self.agent_service.get_agent(self.test_agent_filename)
        self.assertIsNotNone(agent)

    def test_admin_can_delete_agent(self):
        """Admin can delete AIAgent"""
        self.client.force_login(self.admin_user)
        response = self.client.post(
            reverse('agent-delete', kwargs={'filename': self.test_agent_filename})
        )
        self.assertIn(response.status_code, [200, 302])
        # Verify agent was deleted
        agent = self.agent_service.get_agent(self.test_agent_filename)
        self.assertIsNone(agent)
