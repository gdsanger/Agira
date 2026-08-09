"""Tests for per-user Claude credential resolution (#1083)."""

import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import (
    ClaudeCredentialSource,
    ClaudeQueueJobAuthMode,
    Item,
    ItemStatus,
    ItemType,
    Project,
    UserRole,
)
from core.services.claude_queue.credentials import (
    MissingClaudeCredential,
    resolve_claude_credential,
    resolve_credential_user,
)

User = get_user_model()


class CredentialUserResolutionTests(TestCase):
    """Who a job is billed to must not depend on who filled in their profile."""

    def setUp(self):
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.project = Project.objects.create(name='P', github_owner='o', github_repo='r')
        self.trigger = User.objects.create_user(
            username='trigger', email='t@example.com', password='x', name='Trigger',
        )
        self.responsible = User.objects.create_user(
            username='resp', email='r@example.com', password='x', name='Resp',
            role=UserRole.AGENT,
        )
        self.assignee = User.objects.create_user(
            username='assignee', email='a@example.com', password='x', name='Assignee',
        )
        self.requester = User.objects.create_user(
            username='requester', email='q@example.com', password='x', name='Requester',
        )

    def _item(self, **kwargs):
        return Item.objects.create(
            project=self.project, title='I', type=self.item_type,
            status=ItemStatus.BACKLOG, **kwargs,
        )

    def test_actor_wins_over_every_item_role(self):
        item = self._item(
            responsible=self.responsible,
            assigned_to=self.assignee,
            requester=self.requester,
        )
        self.assertEqual(resolve_credential_user(item, actor=self.trigger), self.trigger)

    def test_falls_back_to_responsible_then_assignee_then_requester(self):
        item = self._item(
            responsible=self.responsible,
            assigned_to=self.assignee,
            requester=self.requester,
        )
        self.assertEqual(resolve_credential_user(item), self.responsible)

        item.responsible = None
        self.assertEqual(resolve_credential_user(item), self.assignee)

        item.assigned_to = None
        self.assertEqual(resolve_credential_user(item), self.requester)

    def test_order_ignores_whether_a_candidate_has_credentials(self):
        # The responsible user has a token, the actor has none — the actor still
        # wins. Otherwise attribution would move whenever someone edits a profile.
        self.responsible.claude_oauth_token = 'oauth-resp'
        self.responsible.save()
        item = self._item(responsible=self.responsible)

        self.assertEqual(resolve_credential_user(item, actor=self.trigger), self.trigger)

    def test_no_user_at_all_resolves_to_none(self):
        self.assertIsNone(resolve_credential_user(self._item()))


@override_settings(ANTHROPIC_API_KEY='', CLAUDE_CODE_OAUTH_TOKEN='')
class CredentialResolutionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='x', name='U',
        )
        # Neutralise a host-wide credential leaking in from the real environment.
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop('ANTHROPIC_API_KEY', None)
        os.environ.pop('CLAUDE_CODE_OAUTH_TOKEN', None)
        self.addCleanup(self.env.stop)

    def test_personal_oauth_token_is_used_for_a_subscription_run(self):
        self.user.claude_oauth_token = 'oauth-personal'
        credential = resolve_claude_credential(self.user, ClaudeQueueJobAuthMode.OAUTH)

        self.assertEqual(credential.value, 'oauth-personal')
        self.assertEqual(credential.env_var, 'CLAUDE_CODE_OAUTH_TOKEN')
        self.assertEqual(credential.source, ClaudeCredentialSource.USER)
        self.assertTrue(credential.is_personal)

    def test_personal_api_key_is_used_for_an_api_run(self):
        self.user.claude_api_key = 'sk-personal'
        credential = resolve_claude_credential(self.user, ClaudeQueueJobAuthMode.API_KEY)

        self.assertEqual(credential.value, 'sk-personal')
        self.assertEqual(credential.env_var, 'ANTHROPIC_API_KEY')
        self.assertEqual(credential.source, ClaudeCredentialSource.USER)

    def test_api_key_is_never_used_for_a_subscription_run(self):
        # The whole point of the mode split: a stored API key must not turn an
        # ABO run into a paid one.
        self.user.claude_api_key = 'sk-personal'
        credential = resolve_claude_credential(self.user, ClaudeQueueJobAuthMode.OAUTH)

        self.assertEqual(credential.value, '')
        self.assertEqual(credential.source, ClaudeCredentialSource.HOST_LOGIN)

    def test_api_run_without_any_key_fails_instead_of_falling_back(self):
        self.user.claude_oauth_token = 'oauth-personal'
        with self.assertRaises(MissingClaudeCredential):
            resolve_claude_credential(self.user, ClaudeQueueJobAuthMode.API_KEY)

    @override_settings(CLAUDE_CODE_OAUTH_TOKEN='oauth-host')
    def test_host_wide_token_is_the_fallback_by_default(self):
        credential = resolve_claude_credential(self.user, ClaudeQueueJobAuthMode.OAUTH)

        self.assertEqual(credential.value, 'oauth-host')
        self.assertEqual(credential.source, ClaudeCredentialSource.SHARED)
        self.assertFalse(credential.is_personal)

    @override_settings(CLAUDE_CODE_OAUTH_TOKEN='oauth-host',
                       CLAUDE_REQUIRE_USER_CREDENTIALS=True)
    def test_required_mode_refuses_the_shared_fallback(self):
        with self.assertRaises(MissingClaudeCredential) as ctx:
            resolve_claude_credential(self.user, ClaudeQueueJobAuthMode.OAUTH)

        message = str(ctx.exception)
        self.assertIn('U', message)          # names the user
        self.assertIn('User Settings', message)  # says where to fix it

    @override_settings(CLAUDE_CODE_OAUTH_TOKEN='oauth-host',
                       CLAUDE_REQUIRE_USER_CREDENTIALS=True)
    def test_required_mode_still_allows_a_job_without_a_user(self):
        credential = resolve_claude_credential(None, ClaudeQueueJobAuthMode.OAUTH)
        self.assertEqual(credential.source, ClaudeCredentialSource.SHARED)

    def test_subscription_run_without_any_token_falls_back_to_host_login(self):
        credential = resolve_claude_credential(self.user, ClaudeQueueJobAuthMode.OAUTH)

        self.assertEqual(credential.value, '')
        self.assertEqual(credential.source, ClaudeCredentialSource.HOST_LOGIN)
