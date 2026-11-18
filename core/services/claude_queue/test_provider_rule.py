"""Tests for the review-provider rule and provider-aware enqueue (#1300)."""

from django.test import TestCase, override_settings

from core.models import (
    AgentProvider,
    ClaudeQueueJob,
    ClaudeQueueJobAuthMode,
    ClaudeQueueJobKind,
    ClaudeQueueJobStatus,
    ExternalIssueKind,
    ExternalIssueMapping,
    Item,
    ItemStatus,
    ItemType,
    Project,
)
from core.services.claude_queue.credentials import MissingOpenAICredential
from core.services.claude_queue.enqueue import (
    ReviewNotAllowed,
    enqueue_epic_for_claude,
    enqueue_item_for_claude,
    enqueue_review_for_claude,
)
from core.services.claude_queue.provider_rule import (
    effective_review_provider,
    other_provider,
)

CLAUDE, OPENAI = AgentProvider.CLAUDE, AgentProvider.OPENAI


class ProviderTestBase(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='P')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')

    def make_item(self, status=ItemStatus.TESTING, pr=True, **kw):
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

    def make_job(self, item, provider, status=ClaudeQueueJobStatus.DONE, **kw):
        return ClaudeQueueJob.objects.create(
            item=item, project=self.project, provider=provider, status=status, **kw,
        )


class EffectiveReviewProviderTests(ProviderTestBase):
    def test_other_provider(self):
        self.assertEqual(other_provider(CLAUDE), OPENAI)
        self.assertEqual(other_provider(OPENAI), CLAUDE)

    def test_no_run_uses_other_than_implementation_provider(self):
        self.assertEqual(effective_review_provider(self.make_item()), OPENAI)
        self.assertEqual(
            effective_review_provider(self.make_item(implementation_provider=OPENAI)), CLAUDE,
        )

    def test_explicit_review_provider_wins(self):
        item = self.make_item(implementation_provider=CLAUDE, review_provider=CLAUDE)
        self.assertEqual(effective_review_provider(item), CLAUDE)

    def test_last_successful_implementation_decides(self):
        # implementation_provider says Claude, but OpenAI actually did the work.
        item = self.make_item(implementation_provider=CLAUDE)
        self.make_job(item, OPENAI)
        self.assertEqual(effective_review_provider(item), CLAUDE)

    def test_newest_successful_run_counts(self):
        item = self.make_item()
        self.make_job(item, CLAUDE)
        self.make_job(item, OPENAI)
        self.assertEqual(effective_review_provider(item), CLAUDE)

    def test_failed_review_epic_and_uncertain_runs_are_ignored(self):
        item = self.make_item(implementation_provider=CLAUDE)
        self.make_job(item, OPENAI, status=ClaudeQueueJobStatus.FAILED)
        self.make_job(item, OPENAI, kind=ClaudeQueueJobKind.REVIEW)
        self.make_job(item, OPENAI, kind=ClaudeQueueJobKind.EPIC)
        self.make_job(item, OPENAI, completion_uncertain=True)
        self.assertEqual(effective_review_provider(item), OPENAI)


@override_settings(OPENAI_API_KEY='sk-test')
class ReviewEnqueueProviderTests(ProviderTestBase):
    def test_claude_implementation_gets_openai_review(self):
        item = self.make_item()
        self.make_job(item, CLAUDE)
        job, created = enqueue_review_for_claude(item)
        self.assertTrue(created)
        self.assertEqual(job.provider, OPENAI)
        self.assertEqual(job.model, 'gpt-5-codex')
        self.assertEqual(job.auth_mode, ClaudeQueueJobAuthMode.API_KEY)

    def test_openai_implementation_gets_claude_review(self):
        item = self.make_item()
        self.make_job(item, OPENAI)
        job, _ = enqueue_review_for_claude(item)
        self.assertEqual(job.provider, CLAUDE)
        self.assertEqual(job.model, 'sonnet')

    def test_item_override_and_explicit_button_provider(self):
        item = self.make_item(review_provider=CLAUDE)
        self.assertEqual(enqueue_review_for_claude(item)[0].provider, CLAUDE)
        ClaudeQueueJob.objects.all().delete()
        self.assertEqual(enqueue_review_for_claude(item, provider=OPENAI)[0].provider, OPENAI)

    def test_model_follows_provider(self):
        item = self.make_item(suggested_model='gpt-5-codex-mini')
        self.assertEqual(enqueue_review_for_claude(item, provider=OPENAI)[0].model, 'gpt-5-codex-mini')
        ClaudeQueueJob.objects.all().delete()
        self.assertEqual(enqueue_review_for_claude(item, provider=CLAUDE)[0].model, 'sonnet')

    def test_status_and_pr_guards_unchanged(self):
        with self.assertRaises(ReviewNotAllowed):
            enqueue_review_for_claude(self.make_item(status=ItemStatus.WORKING))
        with self.assertRaises(ReviewNotAllowed):
            enqueue_review_for_claude(self.make_item(pr=False))

    def test_no_second_active_review(self):
        item = self.make_item()
        first, _ = enqueue_review_for_claude(item)
        second, created = enqueue_review_for_claude(item, provider=CLAUDE)
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)

    @override_settings(OPENAI_API_KEY='')
    def test_missing_openai_key_rejected_before_job_creation(self):
        with self.assertRaises(MissingOpenAICredential):
            enqueue_review_for_claude(self.make_item(), provider=OPENAI)
        self.assertFalse(ClaudeQueueJob.objects.exists())


@override_settings(OPENAI_API_KEY='sk-test')
class ImplementationEnqueueProviderTests(ProviderTestBase):
    def test_default_is_item_implementation_provider(self):
        item = self.make_item(status=ItemStatus.BACKLOG, pr=False)
        job, _ = enqueue_item_for_claude(item)
        self.assertEqual(job.provider, CLAUDE)

    def test_explicit_provider_is_used_and_remembered(self):
        item = self.make_item(status=ItemStatus.BACKLOG, pr=False)
        job, _ = enqueue_item_for_claude(item, provider=OPENAI)
        item.refresh_from_db()
        self.assertEqual(job.provider, OPENAI)
        self.assertEqual(job.model, 'gpt-5-codex')
        self.assertEqual(job.auth_mode, ClaudeQueueJobAuthMode.API_KEY)
        self.assertFalse(job.allow_api_key_fallback)
        self.assertEqual(item.implementation_provider, OPENAI)
        self.assertEqual(item.status, ItemStatus.WORKING)

    @override_settings(OPENAI_API_KEY='')
    def test_missing_openai_key_leaves_item_untouched(self):
        item = self.make_item(status=ItemStatus.BACKLOG, pr=False)
        with self.assertRaises(MissingOpenAICredential):
            enqueue_item_for_claude(item, provider=OPENAI)
        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.BACKLOG)
        self.assertEqual(item.implementation_provider, CLAUDE)
        self.assertFalse(ClaudeQueueJob.objects.exists())

    def test_epic_node_carries_provider(self):
        epic = self.make_item(status=ItemStatus.BACKLOG, pr=False)
        Item.objects.create(
            title='Sub', project=self.project, type=self.item_type, parent=epic,
        )
        job, _ = enqueue_epic_for_claude(epic, provider=OPENAI)
        self.assertEqual(job.provider, OPENAI)
        self.assertEqual(job.kind, ClaudeQueueJobKind.EPIC)
