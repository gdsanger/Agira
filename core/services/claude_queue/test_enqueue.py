"""Tests for the Claude queue enqueue pipeline (#833): branch-name slug,
git-workflow hint injection, and the enqueue orchestration."""

from django.test import TestCase, override_settings

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobAuthMode,
    ClaudeQueueJobStatus,
    Item,
    ItemStatus,
    ItemType,
    Project,
    User,
    UserRole,
)
from core.services.claude_queue.credentials import MissingClaudeCredential
from core.services.claude_queue.branch import build_branch_name
from core.services.claude_queue.enqueue import enqueue_item_for_claude
from core.services.claude_queue.hint import (
    GIT_WORKFLOW_HINT_MARKER,
    ensure_git_workflow_hint,
)


class BuildBranchNameTestCase(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')

    def _item(self, title):
        return Item.objects.create(
            title=title, description='desc', project=self.project, type=self.item_type,
        )

    def test_slugifies_title_and_prefixes_id(self):
        item = self._item('Fix the Login Bug!!')
        self.assertEqual(build_branch_name(item), f'fix/{item.id}-fix-the-login-bug')

    def test_truncates_long_titles(self):
        item = self._item('a' * 100)
        branch = build_branch_name(item)
        # fix/<id>- prefix + at most 60 chars of slug
        prefix = f'fix/{item.id}-'
        self.assertTrue(branch.startswith(prefix))
        self.assertLessEqual(len(branch) - len(prefix), 60)

    def test_falls_back_to_bare_id_for_empty_slug(self):
        item = self._item('!!!')
        self.assertEqual(build_branch_name(item), f'fix/{item.id}')

    def test_deterministic_for_same_item(self):
        item = self._item('Same title twice')
        self.assertEqual(build_branch_name(item), build_branch_name(item))


class EnsureGitWorkflowHintTestCase(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.item = Item.objects.create(
            title='Fix the login bug',
            description='Original description.',
            project=self.project,
            type=self.item_type,
        )

    def test_appends_hint_with_marker_and_branch_name(self):
        appended = ensure_git_workflow_hint(self.item)

        self.assertTrue(appended)
        self.assertIn(GIT_WORKFLOW_HINT_MARKER, self.item.description)
        self.assertIn('Original description.', self.item.description)
        self.assertIn(build_branch_name(self.item), self.item.description)
        self.assertIn('Draft-PR', self.item.description)
        self.assertIn('main', self.item.description)

    def test_idempotent_on_second_call(self):
        ensure_git_workflow_hint(self.item)
        first = self.item.description

        appended_again = ensure_git_workflow_hint(self.item)

        self.assertFalse(appended_again)
        self.assertEqual(self.item.description, first)
        self.assertEqual(self.item.description.count(GIT_WORKFLOW_HINT_MARKER), 1)

    def test_works_on_empty_description(self):
        self.item.description = ''
        appended = ensure_git_workflow_hint(self.item)

        self.assertTrue(appended)
        self.assertIn(GIT_WORKFLOW_HINT_MARKER, self.item.description)


class EnqueueItemForClaudeTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='agent1', password='pw12345', email='agent1@example.com',
        )
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.item = Item.objects.create(
            title='Fix the login bug',
            description='Original description.',
            project=self.project,
            type=self.item_type,
            status=ItemStatus.BACKLOG,
        )

    def test_creates_exactly_one_job(self):
        job, created = enqueue_item_for_claude(self.item, actor=self.user)

        self.assertTrue(created)
        self.assertEqual(ClaudeQueueJob.objects.filter(item=self.item).count(), 1)
        self.assertEqual(job.status, ClaudeQueueJobStatus.QUEUED)
        self.assertEqual(job.project, self.project)

    def test_api_key_fallback_flag_defaults_off(self):
        job, _ = enqueue_item_for_claude(self.item, actor=self.user)
        self.assertFalse(job.allow_api_key_fallback)

    def test_api_key_fallback_flag_can_be_set(self):
        job, _ = enqueue_item_for_claude(
            self.item, actor=self.user, allow_api_key_fallback=True,
        )
        self.assertTrue(job.allow_api_key_fallback)

    def test_appends_hint_exactly_once(self):
        enqueue_item_for_claude(self.item, actor=self.user)

        self.item.refresh_from_db()
        self.assertEqual(self.item.description.count(GIT_WORKFLOW_HINT_MARKER), 1)

    def test_sets_item_status_to_working(self):
        enqueue_item_for_claude(self.item, actor=self.user)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

    def test_defaults_model_to_sonnet_without_suggested_model_field(self):
        # TODO(#834): once Item.suggested_model exists, this should assert
        # that an explicit suggestion is respected instead of the default.
        job, _ = enqueue_item_for_claude(self.item, actor=self.user)

        self.assertEqual(job.model, 'sonnet')

    def test_reenqueue_is_idempotent_no_duplicate_job_or_hint(self):
        first_job, first_created = enqueue_item_for_claude(self.item, actor=self.user)
        second_job, second_created = enqueue_item_for_claude(self.item, actor=self.user)

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first_job.pk, second_job.pk)
        self.assertEqual(ClaudeQueueJob.objects.filter(item=self.item).count(), 1)

        self.item.refresh_from_db()
        self.assertEqual(self.item.description.count(GIT_WORKFLOW_HINT_MARKER), 1)

    def test_does_not_duplicate_job_while_one_is_running(self):
        first_job, _ = enqueue_item_for_claude(self.item, actor=self.user)
        first_job.transition_to(ClaudeQueueJobStatus.RUNNING)

        second_job, created = enqueue_item_for_claude(self.item, actor=self.user)

        self.assertFalse(created)
        self.assertEqual(second_job.pk, first_job.pk)
        self.assertEqual(ClaudeQueueJob.objects.filter(item=self.item).count(), 1)

    def test_allows_new_job_after_previous_one_finished(self):
        first_job, _ = enqueue_item_for_claude(self.item, actor=self.user)
        first_job.transition_to(ClaudeQueueJobStatus.RUNNING)
        first_job.transition_to(ClaudeQueueJobStatus.DONE)

        second_job, created = enqueue_item_for_claude(self.item, actor=self.user)

        self.assertTrue(created)
        self.assertNotEqual(second_job.pk, first_job.pk)
        self.assertEqual(ClaudeQueueJob.objects.filter(item=self.item).count(), 2)


class EnqueueAuthTaggingTestCase(TestCase):
    """Every job is tagged with the auth mode and the user paying for it (#1083)."""

    def setUp(self):
        self.actor = User.objects.create_user(
            username='actor', password='pw12345', email='actor@example.com',
            name='Actor', claude_oauth_token='oauth-actor', claude_api_key='sk-actor',
        )
        self.responsible = User.objects.create_user(
            username='resp', password='pw12345', email='resp@example.com',
            name='Resp', role=UserRole.AGENT, claude_oauth_token='oauth-resp',
        )
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='bug', name='Bug')

    def _item(self, **kwargs):
        return Item.objects.create(
            title='Fix the login bug', description='Original description.',
            project=self.project, type=self.item_type, status=ItemStatus.BACKLOG,
            **kwargs,
        )

    def test_job_defaults_to_subscription_mode(self):
        job, _ = enqueue_item_for_claude(self._item(), actor=self.actor)

        self.assertEqual(job.requested_auth_mode, ClaudeQueueJobAuthMode.OAUTH)
        self.assertEqual(job.auth_mode, ClaudeQueueJobAuthMode.OAUTH)

    def test_job_inherits_the_items_api_choice(self):
        item = self._item(claude_auth_mode=ClaudeQueueJobAuthMode.API_KEY)

        job, _ = enqueue_item_for_claude(item, actor=self.actor)

        self.assertEqual(job.requested_auth_mode, ClaudeQueueJobAuthMode.API_KEY)
        self.assertEqual(job.auth_mode, ClaudeQueueJobAuthMode.API_KEY)

    def test_job_is_tagged_with_the_triggering_user(self):
        item = self._item(responsible=self.responsible)

        job, _ = enqueue_item_for_claude(item, actor=self.actor)

        self.assertEqual(job.auth_user, self.actor)

    def test_job_without_an_actor_falls_back_to_the_responsible_user(self):
        item = self._item(responsible=self.responsible)

        job, _ = enqueue_item_for_claude(item)

        self.assertEqual(job.auth_user, self.responsible)

    def test_frozen_mode_survives_a_later_item_change(self):
        item = self._item()
        job, _ = enqueue_item_for_claude(item, actor=self.actor)

        item.claude_auth_mode = ClaudeQueueJobAuthMode.API_KEY
        item.save()

        job.refresh_from_db()
        self.assertEqual(job.requested_auth_mode, ClaudeQueueJobAuthMode.OAUTH)

    @override_settings(CLAUDE_REQUIRE_USER_CREDENTIALS=True)
    def test_missing_credential_is_rejected_and_leaves_the_item_alone(self):
        no_credentials = User.objects.create_user(
            username='nocred', password='pw12345', email='nocred@example.com',
            name='No Cred',
        )
        item = self._item()

        with self.assertRaises(MissingClaudeCredential):
            enqueue_item_for_claude(item, actor=no_credentials)

        item.refresh_from_db()
        self.assertEqual(item.status, ItemStatus.BACKLOG)
        self.assertFalse(ClaudeQueueJob.objects.filter(item=item).exists())
