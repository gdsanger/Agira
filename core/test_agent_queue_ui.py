"""View tests for the provider-aware Agent Queue UI (#1300)."""

import json
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobStatus,
    ExternalIssueKind,
    ExternalIssueMapping,
    Item,
    ItemStatus,
    ItemType,
    Project,
    User,
)


class AgentQueueUiTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='u', password='pw', email='u@example.com',
        )
        self.user.name = 'U'
        self.user.active = True
        self.user.role = 'Agent'
        self.user.save()
        self.client.login(username='u', password='pw')
        self.project = Project.objects.create(name='P')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')

    def item(self, status=ItemStatus.BACKLOG, pr=False, **kw):
        item = Item.objects.create(
            title='Item', description='d', project=self.project,
            type=self.item_type, status=status, **kw,
        )
        if pr:
            ExternalIssueMapping.objects.create(
                item=item, github_id=1000 + item.id, number=item.id,
                kind=ExternalIssueKind.PR, state='open',
                html_url='https://github.com/o/r/pull/1',
            )
        return item

    def job(self, item, provider, **kw):
        return ClaudeQueueJob.objects.create(
            item=item, project=self.project, provider=provider,
            status=ClaudeQueueJobStatus.DONE, **kw,
        )

    # --- Rename ------------------------------------------------------------ #

    def test_queue_page_and_navigation_say_agent_queue(self):
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertContains(response, 'Agent Queue')
        self.assertNotContains(response, 'Claude Queue')

    def test_job_detail_says_agent_queue(self):
        job = self.job(self.item(), 'openai', model='gpt-5-codex')
        response = self.client.get(reverse('claude-queue-job-detail', args=[job.id]))
        self.assertContains(response, 'Agent Queue')
        self.assertNotContains(response, 'Claude Queue')

    # --- Queue list: badge + filter ---------------------------------------- #

    def test_rows_show_provider_and_model_badge(self):
        self.job(self.item(), 'openai', model='gpt-5-codex')
        self.job(self.item(), 'claude', model='opus-5')
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertContains(response, 'OpenAI Codex')
        self.assertContains(response, 'GPT-5 Codex')
        self.assertContains(response, 'Claude Code')

    def test_provider_filter(self):
        oa = self.job(self.item(), 'openai', model='gpt-5-codex')
        cl = self.job(self.item(), 'claude')
        response = self.client.get(reverse('claude-queue-jobs'), {'provider': 'openai'})
        self.assertEqual([j.pk for j in response.context['jobs']], [oa.pk])
        self.assertEqual(response.context['selected_provider'], 'openai')
        response = self.client.get(reverse('claude-queue-jobs'), {'provider': 'bogus'})
        self.assertEqual({j.pk for j in response.context['jobs']}, {oa.pk, cl.pk})

    def test_openai_job_shows_api_auth_badge(self):
        job = self.job(self.item(), 'openai', model='gpt-5-codex', auth_mode='api_key')
        response = self.client.get(reverse('claude-queue-job-row', args=[job.id]))
        self.assertContains(response, 'OpenAI-API-Key')

    # --- Item detail ------------------------------------------------------- #

    def test_detail_offers_both_providers_for_run_and_review(self):
        item = self.item(status=ItemStatus.TESTING, pr=True)
        response = self.client.get(reverse('item-detail', args=[item.id]))
        for call in (
            "enqueueToAgent('claude')", "enqueueToAgent('openai')",
            "reviewByAgent('claude')", "reviewByAgent('openai')",
        ):
            self.assertContains(response, f'onclick="{call}"')
        self.assertContains(response, 'Umsetzung durch OpenAI')
        self.assertContains(response, 'Automatik (aktuell: OpenAI Codex)')

    def test_detail_model_select_matches_provider(self):
        item = self.item(implementation_provider='openai', suggested_model='gpt-5-codex')
        response = self.client.get(reverse('item-detail', args=[item.id]))
        values = [v for v, _ in response.context['suggested_model_choices']]
        self.assertEqual(values, ['gpt-5-codex', 'gpt-5-codex-mini'])

    def test_review_buttons_hidden_outside_review_states(self):
        response = self.client.get(reverse('item-detail', args=[self.item().id]))
        self.assertNotContains(response, "onclick=\"reviewByAgent('openai')\"")

    def test_form_renders_provider_selects(self):
        response = self.client.get(reverse('item-edit', args=[self.item().id]))
        self.assertContains(response, 'name="implementation_provider"')
        self.assertContains(response, 'name="review_provider"')
        self.assertContains(response, 'data-provider="openai"')

    # --- Enqueue views ----------------------------------------------------- #

    @override_settings(OPENAI_API_KEY='sk-test')
    def test_enqueue_view_with_openai_provider(self):
        item = self.item()
        response = self.client.post(
            reverse('item-claude-enqueue', args=[item.id]), {'provider': 'openai'},
        )
        self.assertEqual(response.status_code, 200)
        job = ClaudeQueueJob.objects.get(item=item)
        self.assertEqual(job.provider, 'openai')
        self.assertIn('OpenAI Codex', response.json()['message'])

    @override_settings(OPENAI_API_KEY='')
    def test_enqueue_view_without_openai_key_is_user_error(self):
        item = self.item()
        response = self.client.post(
            reverse('item-claude-enqueue', args=[item.id]), {'provider': 'openai'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('OpenAI', response.json()['error'])
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.BACKLOG)

    def test_enqueue_view_closed_guard_unchanged(self):
        item = self.item(status=ItemStatus.CLOSED)
        response = self.client.post(
            reverse('item-claude-enqueue', args=[item.id]), {'provider': 'openai'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ClaudeQueueJob.objects.exists())

    @override_settings(OPENAI_API_KEY='sk-test')
    def test_review_view_default_is_other_provider(self):
        item = self.item(status=ItemStatus.TESTING, pr=True)
        self.job(item, 'claude')
        response = self.client.post(reverse('item-claude-review', args=[item.id]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ClaudeQueueJob.objects.get(item=item, kind='review').provider, 'openai',
        )

    def test_review_view_explicit_claude_overrides_rule(self):
        item = self.item(status=ItemStatus.TESTING, pr=True)
        self.job(item, 'claude')
        response = self.client.post(
            reverse('item-claude-review', args=[item.id]), {'provider': 'claude'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ClaudeQueueJob.objects.get(item=item, kind='review').provider, 'claude',
        )

    # --- Field updates / API ----------------------------------------------- #

    def test_inline_provider_change_resets_foreign_model_and_refreshes(self):
        item = self.item(suggested_model='opus-5')
        response = self.client.post(
            reverse('item-update-field', args=[item.id]),
            {'field': 'implementation_provider', 'value': 'openai'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['HX-Refresh'], 'true')
        item.refresh_from_db()
        self.assertEqual(item.implementation_provider, 'openai')
        self.assertEqual(item.suggested_model, 'gpt-5-codex')

    def test_inline_review_provider_accepts_automatic_and_rejects_garbage(self):
        item = self.item(review_provider='claude')
        url = reverse('item-update-field', args=[item.id])
        self.assertEqual(
            self.client.post(url, {'field': 'review_provider', 'value': ''}).status_code, 200,
        )
        item.refresh_from_db()
        self.assertEqual(item.review_provider, '')
        self.assertEqual(
            self.client.post(url, {'field': 'review_provider', 'value': 'x'}).status_code, 400,
        )

    def test_inline_model_accepts_openai_slug(self):
        item = self.item(implementation_provider='openai')
        response = self.client.post(
            reverse('item-update-field', args=[item.id]),
            {'field': 'suggested_model', 'value': 'gpt-5-codex-mini'},
        )
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.suggested_model, 'gpt-5-codex-mini')
