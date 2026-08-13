"""Tests for the per-user MCP token, its profile UI and the soft auth phase (#1119).

Covers auto-generation on user creation, rotation (model + HTMX endpoint), the
30-day rotation nudge, and the deliberately non-blocking token resolution on the
API side (missing/unknown token -> anonymous access + warning, never a 401).
"""

import json
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    MCP_TOKEN_ROTATION_DAYS,
    Item,
    ItemType,
    Project,
    ProjectStatus,
    User,
    UserRole,
)
from core.views_api import resolve_mcp_user


class McpTokenModelTests(TestCase):
    def test_new_user_gets_token_and_rotation_date(self):
        user = User.objects.create_user(
            username='u', email='u@example.com', password='pw', name='U',
        )

        self.assertTrue(user.mcp_token)
        self.assertIsNotNone(user.mcp_token_last_rotated)
        self.assertEqual(user.mcp_token_age_days, 0)
        self.assertFalse(user.mcp_token_needs_rotation)

    def test_tokens_are_unique_per_user(self):
        first = User.objects.create_user(username='a', email='a@example.com', name='A')
        second = User.objects.create_user(username='b', email='b@example.com', name='B')

        self.assertNotEqual(first.mcp_token, second.mcp_token)

    def test_explicit_token_is_kept(self):
        user = User.objects.create_user(
            username='u', email='u@example.com', name='U', mcp_token='explicit-token',
        )

        self.assertEqual(user.mcp_token, 'explicit-token')

    def test_cleared_token_is_not_regenerated_on_save(self):
        """Clearing the token revokes MCP access — saving must not undo that."""
        user = User.objects.create_user(username='u', email='u@example.com', name='U')
        User.objects.filter(pk=user.pk).update(mcp_token=None)

        user.refresh_from_db()
        user.name = 'Renamed'
        user.save()

        user.refresh_from_db()
        self.assertIsNone(user.mcp_token)

    def test_rotation_replaces_token_and_stamps_date(self):
        user = User.objects.create_user(username='u', email='u@example.com', name='U')
        old_token = user.mcp_token
        User.objects.filter(pk=user.pk).update(
            mcp_token_last_rotated=timezone.now() - timedelta(days=90)
        )
        user.refresh_from_db()

        new_token = user.rotate_mcp_token()

        user.refresh_from_db()
        self.assertNotEqual(new_token, old_token)
        self.assertEqual(user.mcp_token, new_token)
        self.assertEqual(user.mcp_token_age_days, 0)
        self.assertFalse(User.objects.filter(mcp_token=old_token).exists())

    def test_rotation_hint_after_30_days(self):
        user = User.objects.create_user(username='u', email='u@example.com', name='U')

        user.mcp_token_last_rotated = timezone.now() - timedelta(
            days=MCP_TOKEN_ROTATION_DAYS - 1
        )
        self.assertFalse(user.mcp_token_needs_rotation)

        user.mcp_token_last_rotated = timezone.now() - timedelta(
            days=MCP_TOKEN_ROTATION_DAYS
        )
        self.assertTrue(user.mcp_token_needs_rotation)
        self.assertEqual(user.mcp_token_age_days, MCP_TOKEN_ROTATION_DAYS)

    def test_unknown_rotation_date_nudges(self):
        """Tokens from before #1119 have no date — nudge instead of staying silent."""
        user = User.objects.create_user(username='u', email='u@example.com', name='U')
        user.mcp_token_last_rotated = None

        self.assertIsNone(user.mcp_token_age_days)
        self.assertTrue(user.mcp_token_needs_rotation)

    def test_no_token_means_no_nudge_and_no_url(self):
        user = User.objects.create_user(username='u', email='u@example.com', name='U')
        user.mcp_token = None

        self.assertFalse(user.mcp_token_needs_rotation)
        self.assertEqual(user.get_mcp_connector_url(), '')
        self.assertEqual(user.get_mcp_token_masked(), '')

    @override_settings(MCP_CONNECTOR_URL='https://agira.example.com/mcp/')
    def test_connector_url_carries_the_token(self):
        user = User.objects.create_user(username='u', email='u@example.com', name='U')

        self.assertEqual(
            user.get_mcp_connector_url(),
            f'https://agira.example.com/mcp/?token={user.mcp_token}',
        )

    def test_masked_token_only_shows_the_last_characters(self):
        user = User.objects.create_user(
            username='u', email='u@example.com', name='U', mcp_token='abcdefghijkl9876',
        )

        masked = user.get_mcp_token_masked()
        self.assertTrue(masked.endswith('9876'))
        self.assertNotIn('abcdefgh', masked)


@override_settings(MCP_CONNECTOR_URL='https://agira.example.com/mcp/')
class McpTokenProfileViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='pw', name='U',
        )
        self.client = Client()
        self.client.login(username='u', password='pw')

    def test_settings_page_shows_connector_url_and_masked_token(self):
        response = self.client.get(reverse('user-settings'))

        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn('Claude MCP Integration', content)
        self.assertIn(f'https://agira.example.com/mcp/?token={self.user.mcp_token}', content)
        self.assertIn(self.user.get_mcp_token_masked(), content)
        self.assertIn('Token rollieren', content)

    def test_settings_page_shows_rotation_hint_for_old_token(self):
        User.objects.filter(pk=self.user.pk).update(
            mcp_token_last_rotated=timezone.now() - timedelta(days=45)
        )

        response = self.client.get(reverse('user-settings'))

        self.assertContains(response, 'zuletzt vor 45 Tagen rotiert')

    def test_settings_page_hides_hint_for_fresh_token(self):
        response = self.client.get(reverse('user-settings'))

        self.assertNotContains(response, 'empfehlen wir eine monatliche Erneuerung')

    def test_settings_page_nudges_when_rotation_date_is_unknown(self):
        User.objects.filter(pk=self.user.pk).update(mcp_token_last_rotated=None)

        response = self.client.get(reverse('user-settings'))

        self.assertContains(response, 'kein Rotationsdatum bekannt')
        self.assertContains(response, 'empfehlen wir eine monatliche Erneuerung')

    def test_settings_page_without_token_offers_generation(self):
        User.objects.filter(pk=self.user.pk).update(mcp_token=None)

        response = self.client.get(reverse('user-settings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Token erzeugen')
        self.assertContains(response, 'kein MCP-Token hinterlegt')

    def test_htmx_rotation_returns_the_new_url(self):
        old_token = self.user.mcp_token

        response = self.client.post(
            reverse('user-mcp-token-rotate'), **{'HTTP_HX_REQUEST': 'true'}
        )

        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertNotEqual(self.user.mcp_token, old_token)
        content = response.content.decode()
        self.assertIn(f'?token={self.user.mcp_token}', content)
        self.assertNotIn(old_token, content)

    def test_rotation_without_htmx_redirects_to_settings(self):
        response = self.client.post(reverse('user-mcp-token-rotate'))

        self.assertRedirects(response, reverse('user-settings'))

    def test_rotation_requires_post(self):
        response = self.client.get(reverse('user-mcp-token-rotate'))

        self.assertEqual(response.status_code, 405)

    def test_rotation_requires_login(self):
        self.client.logout()

        response = self.client.post(reverse('user-mcp-token-rotate'))

        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response['Location'])

    def test_rotation_does_not_touch_other_users(self):
        other = User.objects.create_user(
            username='other', email='other@example.com', name='Other',
        )
        other_token = other.mcp_token

        self.client.post(reverse('user-mcp-token-rotate'))

        other.refresh_from_db()
        self.assertEqual(other.mcp_token, other_token)


class McpTokenResolutionTests(TestCase):
    """Soft phase: resolve the user when possible, never block the request."""

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            username='agent', email='agent@example.com', name='Agent',
            role=UserRole.AGENT, mcp_token='known-token',
        )

    def test_token_from_query_string_resolves_user(self):
        request = self.factory.get('/api/customgpt/projects', {'token': 'known-token'})

        self.assertEqual(resolve_mcp_user(request), self.user)
        self.assertEqual(request.mcp_user, self.user)

    def test_header_takes_precedence_over_query_string(self):
        request = self.factory.get(
            '/api/customgpt/projects',
            {'token': 'unknown'},
            HTTP_X_AGIRA_USER_TOKEN='known-token',
        )

        self.assertEqual(resolve_mcp_user(request), self.user)

    def test_missing_token_stays_anonymous_and_warns(self):
        request = self.factory.get('/api/customgpt/projects')

        with self.assertLogs('core.views_api', level='WARNING') as logs:
            self.assertIsNone(resolve_mcp_user(request))

        self.assertIsNone(request.mcp_user)
        self.assertIn('without a per-user token', '\n'.join(logs.output))

    def test_unknown_token_stays_anonymous_and_warns(self):
        request = self.factory.get('/api/customgpt/projects', {'token': 'nope'})

        with self.assertLogs('core.views_api', level='WARNING') as logs:
            self.assertIsNone(resolve_mcp_user(request))

        self.assertIsNone(request.mcp_user)
        self.assertIn('unknown or inactive', '\n'.join(logs.output))

    def test_inactive_user_token_stays_anonymous(self):
        self.user.active = False
        self.user.save()
        request = self.factory.get('/api/customgpt/projects', {'token': 'known-token'})

        with self.assertLogs('core.views_api', level='WARNING'):
            self.assertIsNone(resolve_mcp_user(request))


class McpTokenApiSoftPhaseTests(TestCase):
    """The item API keeps working for tokenless callers (no hard 401 yet)."""

    def setUp(self):
        self.client = Client()
        self.headers = {'HTTP_X_API_SECRET': 'test-secret-123'}
        self.project = Project.objects.create(
            name='MCP Project', description='', status=ProjectStatus.WORKING,
        )
        self.item_type = ItemType.objects.create(key='task', name='Task', description='')
        self.agent = User.objects.create_user(
            username='agent', email='agent@example.com', name='Agent',
            role=UserRole.AGENT, mcp_token='agent-token',
        )

    def _create(self, query=''):
        with patch.dict('os.environ', {'CUSTOMGPT_API_SECRET': 'test-secret-123'}):
            return self.client.post(
                f'/api/customgpt/projects/{self.project.id}/items{query}',
                data=json.dumps({'title': 'Via MCP', 'type_id': self.item_type.id}),
                content_type='application/json',
                **self.headers,
            )

    def test_query_token_attributes_the_item(self):
        response = self._create('?token=agent-token')

        self.assertEqual(response.status_code, 201)
        self.assertEqual(json.loads(response.content)['responsible_id'], self.agent.id)

    def test_missing_token_still_creates_the_item(self):
        response = self._create()

        self.assertEqual(response.status_code, 201)
        self.assertIsNone(json.loads(response.content)['responsible_id'])
        self.assertTrue(Item.objects.filter(title='Via MCP').exists())

    def test_middleware_exposes_mcp_user_on_the_request(self):
        from django.http import HttpResponse

        from core.middleware_api import CustomGPTAPIAuthMiddleware

        seen = {}

        def get_response(request):
            seen['user'] = request.mcp_user
            return HttpResponse('')

        with patch.dict('os.environ', {'CUSTOMGPT_API_SECRET': 'test-secret-123'}):
            middleware = CustomGPTAPIAuthMiddleware(get_response)

        request = RequestFactory().get(
            '/api/customgpt/projects', {'token': 'agent-token'},
            HTTP_X_API_SECRET='test-secret-123',
        )
        middleware(request)

        self.assertEqual(seen['user'], self.agent)
