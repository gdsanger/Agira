"""Tests for the OpenAI provider data model (#1297)."""

from unittest.mock import Mock

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import (
    AgentProvider,
    ClaudeCredentialSource,
    ClaudeQueueJob,
    ClaudeQueueJobModel,
    Item,
    ItemType,
    OpenAIQueueJobModel,
    Project,
    models_for_provider,
    openai_cli_model_id,
    provider_for_model,
)
from core.services.claude_queue.credentials import (
    MissingOpenAICredential,
    resolve_openai_credential,
)
from core.services.claude_queue.model_classifier import suggest_model

User = get_user_model()


class ProviderDefaultsTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='P')
        self.type = ItemType.objects.create(key='task', name='Task')
        self.item = Item.objects.create(title='t', project=self.project, type=self.type)

    def test_item_defaults(self):
        self.assertEqual(self.item.implementation_provider, AgentProvider.CLAUDE)
        self.assertEqual(self.item.review_provider, '')

    def test_job_defaults_to_claude(self):
        job = ClaudeQueueJob.objects.create(item=self.item, project=self.project)
        self.assertEqual(job.provider, AgentProvider.CLAUDE)

    def test_job_accepts_openai_model(self):
        job = ClaudeQueueJob.objects.create(
            item=self.item, project=self.project,
            provider=AgentProvider.OPENAI, model=OpenAIQueueJobModel.GPT_5_CODEX,
        )
        job.full_clean()


class ModelMappingTests(TestCase):
    def test_every_openai_slug_maps_to_cli_id(self):
        for m in OpenAIQueueJobModel:
            self.assertTrue(openai_cli_model_id(m.value))

    def test_unknown_slug_falls_back(self):
        self.assertEqual(openai_cli_model_id('nope'), 'gpt-5-codex')
        self.assertEqual(openai_cli_model_id(''), 'gpt-5-codex')

    def test_provider_is_unambiguous(self):
        claude = {m.value for m in ClaudeQueueJobModel}
        openai = {m.value for m in OpenAIQueueJobModel}
        self.assertFalse(claude & openai)
        self.assertEqual(provider_for_model('sonnet'), AgentProvider.CLAUDE)
        self.assertEqual(provider_for_model('gpt-5-codex'), AgentProvider.OPENAI)
        self.assertIsNone(provider_for_model('x'))

    def test_models_for_provider(self):
        self.assertEqual(models_for_provider(AgentProvider.OPENAI), OpenAIQueueJobModel.choices)
        self.assertEqual(models_for_provider(AgentProvider.CLAUDE), ClaudeQueueJobModel.choices)


class OpenAICredentialTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='pw', name='U',
        )

    def test_flags_default_false(self):
        self.assertFalse(self.user.has_openai_api_key())
        self.assertEqual(self.user.openai_credential_for(), '')

    def test_whitespace_key_does_not_count(self):
        self.user.openai_api_key = '  '
        self.assertFalse(self.user.has_openai_api_key())

    @override_settings(OPENAI_API_KEY='sk-host')
    def test_personal_key_wins(self):
        self.user.openai_api_key = 'sk-personal'
        cred = resolve_openai_credential(self.user)
        self.assertEqual((cred.value, cred.source), ('sk-personal', ClaudeCredentialSource.USER))
        self.assertTrue(cred.is_personal)

    @override_settings(OPENAI_API_KEY='sk-host', OPENAI_REQUIRE_USER_CREDENTIALS=False)
    def test_shared_fallback(self):
        cred = resolve_openai_credential(self.user)
        self.assertEqual((cred.value, cred.source), ('sk-host', ClaudeCredentialSource.SHARED))

    @override_settings(OPENAI_API_KEY='sk-host', OPENAI_REQUIRE_USER_CREDENTIALS=True)
    def test_require_user_credentials_blocks_shared(self):
        with self.assertRaises(MissingOpenAICredential):
            resolve_openai_credential(self.user)

    @override_settings(OPENAI_API_KEY='')
    def test_no_key_anywhere_raises(self):
        with self.assertRaises(MissingOpenAICredential):
            with self.settings(OPENAI_REQUIRE_USER_CREDENTIALS=False):
                import os
                from unittest.mock import patch
                with patch.dict(os.environ, {}, clear=True):
                    resolve_openai_credential(self.user)

    def test_key_is_encrypted_at_rest(self):
        self.user.openai_api_key = 'sk-secret-value'
        self.user.save()
        from django.db import connection
        with connection.cursor() as cur:
            cur.execute('SELECT openai_api_key FROM core_user WHERE id = %s', [self.user.pk])
            raw = cur.fetchone()[0]
        self.assertNotIn('sk-secret-value', raw)
        self.user.refresh_from_db()
        self.assertEqual(self.user.openai_api_key, 'sk-secret-value')


class OpenAIProfileTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='u', email='u@example.com', password='pw', name='U',
        )
        self.client = Client()
        self.client.force_login(self.user)

    def test_store_keep_clear_never_rendered(self):
        url = reverse('user-settings-update')
        self.client.post(url, {'openai_api_key': 'sk-abc123'})
        self.user.refresh_from_db()
        self.assertTrue(self.user.has_openai_api_key())

        page = self.client.get(reverse('user-settings'))
        self.assertNotContains(page, 'sk-abc123')

        self.client.post(url, {'openai_api_key': ''})
        self.user.refresh_from_db()
        self.assertEqual(self.user.openai_api_key, 'sk-abc123')

        self.client.post(url, {'clear_openai_api_key': 'true'})
        self.user.refresh_from_db()
        self.assertFalse(self.user.has_openai_api_key())


class SuggestModelProviderTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='P')
        self.type = ItemType.objects.create(key='task', name='Task')

    def test_openai_skips_classifier(self):
        item = Item.objects.create(
            title='t', project=self.project, type=self.type,
            implementation_provider=AgentProvider.OPENAI,
        )
        classifier = Mock()
        self.assertEqual(suggest_model(item, classifier), OpenAIQueueJobModel.GPT_5_CODEX)
        classifier.classify.assert_not_called()

    def test_claude_uses_classifier(self):
        item = Item.objects.create(title='t', project=self.project, type=self.type)
        classifier = Mock()
        classifier.classify.return_value = ClaudeQueueJobModel.OPUS_4_8
        self.assertEqual(suggest_model(item, classifier), ClaudeQueueJobModel.OPUS_4_8)
