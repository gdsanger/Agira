"""Display slug -> `claude --model` identifier plumbing (#1082).

Covers the two halves of the promise made by the Suggested-Model field: every
selectable choice maps to a concrete CLI identifier, and that identifier is
what the worker actually hands to Claude Code.
"""

from django.test import TestCase

from core.management.commands.run_claude_worker import Command
from core.models import (
    CLAUDE_CLI_MODEL_IDS,
    ClaudeQueueJob,
    ClaudeQueueJobModel,
    Item,
    ItemType,
    Project,
    claude_cli_model_id,
)


class ClaudeCliModelIdTest(TestCase):
    """The slug -> CLI identifier mapping."""

    def test_every_choice_has_a_cli_identifier(self):
        self.assertEqual(
            set(CLAUDE_CLI_MODEL_IDS), set(ClaudeQueueJobModel.values),
        )

    def test_opus_generations_map_to_distinct_pinned_ids(self):
        self.assertEqual(
            claude_cli_model_id(ClaudeQueueJobModel.OPUS_4_8), 'claude-opus-4-8',
        )
        self.assertEqual(
            claude_cli_model_id(ClaudeQueueJobModel.OPUS_5), 'claude-opus-5',
        )

    def test_fable_5_maps_to_its_model_id(self):
        self.assertEqual(
            claude_cli_model_id(ClaudeQueueJobModel.FABLE_5), 'claude-fable-5',
        )

    def test_sonnet_keeps_the_floating_cli_alias(self):
        self.assertEqual(claude_cli_model_id(ClaudeQueueJobModel.SONNET), 'sonnet')

    def test_unknown_slug_degrades_to_sonnet(self):
        """A stale slug must not reach the CLI verbatim and break the run."""
        self.assertEqual(claude_cli_model_id('opus'), 'sonnet')
        self.assertEqual(claude_cli_model_id(''), 'sonnet')
        self.assertEqual(claude_cli_model_id(None), 'sonnet')


class BuildClaudeArgsModelTest(TestCase):
    """The worker passes the resolved identifier, not the stored slug."""

    def setUp(self):
        self.project = Project.objects.create(name='Test Project')
        self.item_type = ItemType.objects.create(key='task', name='Task')
        self.item = Item.objects.create(
            title='Some task', description='Do the thing.',
            project=self.project, type=self.item_type,
            suggested_model=ClaudeQueueJobModel.SONNET,
        )

    def _model_arg(self, job):
        args = Command()._build_claude_args(job)
        return args[args.index('--model') + 1]

    def test_job_model_is_translated(self):
        job = ClaudeQueueJob.objects.create(
            item=self.item, project=self.project,
            model=ClaudeQueueJobModel.OPUS_5,
        )
        self.assertEqual(self._model_arg(job), 'claude-opus-5')

    def test_falls_back_to_the_items_suggestion(self):
        job = ClaudeQueueJob.objects.create(
            item=self.item, project=self.project, model='',
        )
        self.item.suggested_model = ClaudeQueueJobModel.FABLE_5
        self.item.save()
        job.refresh_from_db()

        self.assertEqual(self._model_arg(job), 'claude-fable-5')
