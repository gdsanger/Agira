"""Tests for the per-user Claude credentials in the user profile (#1083).

Covers the profile round-trip (store / keep / clear, never rendered back) and
the enqueue endpoint's behaviour when the chosen mode has no credential.
"""

import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobAuthMode,
    Item,
    ItemStatus,
    ItemType,
    Project,
)

User = get_user_model()


class UserClaudeCredentialModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='pw', name='U',
        )

    def test_credential_flags_default_to_false(self):
        self.assertFalse(self.user.has_claude_oauth_token())
        self.assertFalse(self.user.has_claude_api_key())

    def test_whitespace_only_credential_does_not_count(self):
        self.user.claude_oauth_token = '   '
        self.assertFalse(self.user.has_claude_oauth_token())

    def test_credential_is_selected_per_mode(self):
        self.user.claude_oauth_token = 'oauth-tok'
        self.user.claude_api_key = 'sk-key'

        self.assertEqual(
            self.user.claude_credential_for(ClaudeQueueJobAuthMode.OAUTH), 'oauth-tok'
        )
        self.assertEqual(
            self.user.claude_credential_for(ClaudeQueueJobAuthMode.API_KEY), 'sk-key'
        )

    def test_credentials_are_encrypted_at_rest(self):
        self.user.claude_oauth_token = 'oauth-secret-value'
        self.user.save()

        with self.subTest('raw column'):
            from django.db import connection
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT claude_oauth_token FROM core_user WHERE id = %s',
                    [self.user.pk],
                )
                stored = cursor.fetchone()[0]
        self.assertNotIn('oauth-secret-value', str(stored))
        # ... and still readable through the ORM.
        self.assertEqual(
            User.objects.get(pk=self.user.pk).claude_oauth_token, 'oauth-secret-value'
        )


class UserSettingsClaudeCredentialViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='pw', name='U',
        )
        self.client = Client()
        self.client.login(username='u', password='pw')

    def test_settings_page_offers_both_credential_fields(self):
        response = self.client.get(reverse('user-settings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'claude_oauth_token')
        self.assertContains(response, 'claude_api_key')

    def test_stored_secret_is_never_rendered_back(self):
        self.user.claude_oauth_token = 'oauth-secret-value'
        self.user.claude_api_key = 'sk-secret-value'
        self.user.save()

        response = self.client.get(reverse('user-settings'))

        self.assertNotContains(response, 'oauth-secret-value')
        self.assertNotContains(response, 'sk-secret-value')
        self.assertContains(response, 'Token hinterlegt')

    def test_user_can_store_both_credentials(self):
        response = self.client.post(reverse('user-settings-update'), {
            'claude_oauth_token': 'oauth-new',
            'claude_api_key': 'sk-new',
        })

        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.claude_oauth_token, 'oauth-new')
        self.assertEqual(self.user.claude_api_key, 'sk-new')

    def test_empty_submission_keeps_the_stored_credential(self):
        self.user.claude_oauth_token = 'oauth-keep'
        self.user.save()

        self.client.post(reverse('user-settings-update'), {'claude_oauth_token': ''})

        self.user.refresh_from_db()
        self.assertEqual(self.user.claude_oauth_token, 'oauth-keep')

    def test_explicit_clear_removes_the_credential(self):
        self.user.claude_oauth_token = 'oauth-drop'
        self.user.save()

        self.client.post(reverse('user-settings-update'), {
            'claude_oauth_token': '',
            'clear_claude_oauth_token': 'true',
        })

        self.user.refresh_from_db()
        self.assertFalse(self.user.has_claude_oauth_token())

    def test_updating_claude_credentials_leaves_the_github_pat_alone(self):
        self.user.github_pat = 'ghp_keep'
        self.user.save()

        self.client.post(reverse('user-settings-update'), {'claude_api_key': 'sk-new'})

        self.user.refresh_from_db()
        self.assertEqual(self.user.github_pat, 'ghp_keep')

    def test_credentials_require_login(self):
        self.client.logout()
        response = self.client.post(reverse('user-settings-update'), {
            'claude_oauth_token': 'oauth-new',
        })
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_claude_oauth_token())


class ClaudeEnqueueCredentialViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='pw', name='U',
        )
        self.project = Project.objects.create(
            name='P', github_owner='o', github_repo='r',
        )
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.item = Item.objects.create(
            project=self.project, title='I', type=self.item_type,
            status=ItemStatus.BACKLOG,
        )
        self.client = Client()
        self.client.login(username='u', password='pw')

    def _enqueue(self):
        return self.client.post(reverse('item-claude-enqueue', args=[self.item.id]))

    @override_settings(CLAUDE_REQUIRE_USER_CREDENTIALS=True)
    def test_enqueue_without_a_credential_is_rejected_with_a_clear_message(self):
        response = self._enqueue()

        self.assertEqual(response.status_code, 400)
        payload = json.loads(response.content)
        self.assertFalse(payload['success'])
        self.assertIn('User Settings', payload['error'])
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.BACKLOG)

    @override_settings(CLAUDE_REQUIRE_USER_CREDENTIALS=True)
    def test_enqueue_with_a_personal_token_tags_the_job(self):
        self.user.claude_oauth_token = 'oauth-mine'
        self.user.save()

        response = self._enqueue()

        self.assertEqual(response.status_code, 200)
        job = ClaudeQueueJob.objects.get(item=self.item)
        self.assertEqual(job.auth_user, self.user)
        self.assertEqual(job.requested_auth_mode, ClaudeQueueJobAuthMode.OAUTH)

    @override_settings(CLAUDE_REQUIRE_USER_CREDENTIALS=True)
    def test_api_issue_needs_the_api_key_not_the_oauth_token(self):
        self.user.claude_oauth_token = 'oauth-mine'
        self.user.save()
        self.item.claude_auth_mode = ClaudeQueueJobAuthMode.API_KEY
        self.item.save()

        response = self._enqueue()

        self.assertEqual(response.status_code, 400)
        self.assertIn('API-Key', json.loads(response.content)['error'])
