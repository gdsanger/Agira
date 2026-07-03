"""Tests for the Claude queue enqueue pipeline (#833): branch-name slug,
git-workflow hint injection, and the enqueue orchestration."""

from django.test import TestCase

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobStatus,
    Item,
    ItemStatus,
    ItemType,
    Project,
    User,
)
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
