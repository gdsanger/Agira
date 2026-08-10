"""Tests for the hierarchical epic orchestration in the Claude queue (#1079).

The rule under test throughout is the advancement rule: the chain moves on
unambiguous success and on nothing else. Most of these tests are therefore
about the *non*-advancing cases — a failed run, a run flagged "Ggf.
unvollständig", a run whose PR has not merged — because that is where a chain
would otherwise stack a layer on a foundation that is not there.
"""

from unittest.mock import patch

from django.test import TestCase

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobKind,
    ClaudeQueueJobStatus,
    ExternalIssueKind,
    ExternalIssueMapping,
    Item,
    ItemStatus,
    ItemType,
    Project,
)
from core.services.claude_queue.enqueue import (
    SubIssueOutsideEpic,
    enqueue_epic_for_claude,
    enqueue_item_for_claude,
)
from core.services.claude_queue.orchestration import (
    ADVANCE_FINISHED,
    ADVANCE_HALTED,
    ADVANCE_INACTIVE,
    ADVANCE_RELEASED,
    ADVANCE_WAITING,
    SUB_BLOCKED,
    SUB_HALTED,
    SUB_SUCCESS,
    SUB_WAITING_MERGE,
    advance_all_epics,
    advance_epic,
    advance_epic_for_item,
    build_epic_chain,
    chain_state,
    start_epic,
    sub_job_state,
    sub_jobs_in_order,
)


class OrchestrationTestBase(TestCase):
    """An epic with three ordered sub-issues, plus an enqueued epic node."""

    def setUp(self):
        self.project = Project.objects.create(
            name='Test Project', github_owner='testowner', github_repo='testrepo',
        )
        self.item_type = ItemType.objects.create(key='feature', name='Feature')
        self.epic = self._item('Kundenportal Freigaben')
        self.data_model = self._item('Datenmodell', parent=self.epic, epic_order=10)
        self.logic = self._item('Logik', parent=self.epic, epic_order=20)
        self.ui = self._item('UI', parent=self.epic, epic_order=30)

    def _item(self, title, *, parent=None, epic_order=0):
        return Item.objects.create(
            title=title,
            project=self.project,
            type=self.item_type,
            parent=parent,
            epic_order=epic_order,
        )

    def _epic_node(self, status=ClaudeQueueJobStatus.ORCHESTRATING):
        node = ClaudeQueueJob.objects.create(
            item=self.epic,
            project=self.project,
            kind=ClaudeQueueJobKind.EPIC,
            status=status,
        )
        build_epic_chain(node)
        return node

    def _merge(self, item, number=None):
        """Record a merged PR mapping — what "the layer landed" looks like."""
        number = number or item.id
        return ExternalIssueMapping.objects.create(
            item=item,
            github_id=-number,
            number=number,
            kind=ExternalIssueKind.PR,
            state='merged',
            html_url=f'https://github.com/testowner/testrepo/pull/{number}',
        )

    def _entry(self, node, item):
        return node.sub_jobs.get(item=item)

    def _finish(self, job, *, uncertain=False, merged=True):
        """Drive a sub-entry through a full run to ``done``."""
        if job.status == ClaudeQueueJobStatus.BLOCKED:
            job.transition_to(ClaudeQueueJobStatus.QUEUED)
        job.transition_to(ClaudeQueueJobStatus.RUNNING)
        if uncertain:
            job.completion_uncertain = True
            job.completion_uncertain_reason = 'Claude spricht von Hintergrund-Job'
            job.save(update_fields=[
                'completion_uncertain', 'completion_uncertain_reason',
            ])
        job.transition_to(ClaudeQueueJobStatus.DONE)
        if merged:
            self._merge(job.item)
        return job


class ChainBuildTests(OrchestrationTestBase):

    def test_chain_is_derived_from_the_sub_issues_in_order(self):
        node = self._epic_node()
        entries = sub_jobs_in_order(node)
        self.assertEqual(
            [e.item_id for e in entries],
            [self.data_model.id, self.logic.id, self.ui.id],
        )
        self.assertEqual([e.epic_order for e in entries], [10, 20, 30])

    def test_every_entry_starts_blocked_and_leaves_its_item_alone(self):
        node = self._epic_node()
        self.assertTrue(all(
            e.status == ClaudeQueueJobStatus.BLOCKED for e in node.sub_jobs.all()
        ))
        self.data_model.refresh_from_db()
        self.assertEqual(self.data_model.status, ItemStatus.INBOX)

    def test_rebuilding_the_chain_does_not_duplicate_entries(self):
        node = self._epic_node()
        build_epic_chain(node)
        self.assertEqual(node.sub_jobs.count(), 3)


class SubJobStateTests(OrchestrationTestBase):

    def test_done_and_merged_is_success(self):
        node = self._epic_node()
        entry = self._finish(self._entry(node, self.data_model))
        self.assertEqual(sub_job_state(entry), SUB_SUCCESS)

    def test_done_but_flagged_uncertain_halts_even_when_merged(self):
        node = self._epic_node()
        entry = self._finish(self._entry(node, self.data_model), uncertain=True)
        self.assertEqual(sub_job_state(entry), SUB_HALTED)

    def test_done_without_a_merge_waits_rather_than_advancing(self):
        node = self._epic_node()
        entry = self._finish(self._entry(node, self.data_model), merged=False)
        self.assertEqual(sub_job_state(entry), SUB_WAITING_MERGE)

    def test_failed_halts(self):
        node = self._epic_node()
        entry = self._entry(node, self.data_model)
        entry.transition_to(ClaudeQueueJobStatus.QUEUED)
        entry.transition_to(ClaudeQueueJobStatus.RUNNING)
        entry.transition_to(ClaudeQueueJobStatus.FAILED)
        self.assertEqual(sub_job_state(entry), SUB_HALTED)


class AdvancementTests(OrchestrationTestBase):

    def test_first_advance_releases_the_lowest_order_sub_issue(self):
        node = self._epic_node()
        self.assertEqual(advance_epic(node), ADVANCE_RELEASED)

        first = self._entry(node, self.data_model)
        self.assertEqual(first.status, ClaudeQueueJobStatus.QUEUED)
        self.assertEqual(
            self._entry(node, self.logic).status, ClaudeQueueJobStatus.BLOCKED,
        )
        self.data_model.refresh_from_db()
        self.assertEqual(self.data_model.status, ItemStatus.WORKING)

    def test_release_writes_the_git_workflow_hint_onto_the_sub_issue(self):
        from core.services.claude_queue.hint import GIT_WORKFLOW_HINT_MARKER

        node = self._epic_node()
        advance_epic(node)
        self.data_model.refresh_from_db()
        self.assertIn(GIT_WORKFLOW_HINT_MARKER, self.data_model.description)

    def test_next_sub_issue_is_released_only_after_a_clean_merged_run(self):
        node = self._epic_node()
        advance_epic(node)
        self._finish(self._entry(node, self.data_model))

        self.assertEqual(advance_epic(node), ADVANCE_RELEASED)
        self.assertEqual(
            self._entry(node, self.logic).status, ClaudeQueueJobStatus.QUEUED,
        )
        self.assertEqual(
            self._entry(node, self.ui).status, ClaudeQueueJobStatus.BLOCKED,
        )

    def test_uncertain_completion_halts_the_chain(self):
        node = self._epic_node()
        advance_epic(node)
        self._finish(self._entry(node, self.data_model), uncertain=True)

        self.assertEqual(advance_epic(node), ADVANCE_HALTED)
        self.assertEqual(
            self._entry(node, self.logic).status, ClaudeQueueJobStatus.BLOCKED,
        )

    def test_failure_halts_the_chain(self):
        node = self._epic_node()
        advance_epic(node)
        entry = self._entry(node, self.data_model)
        entry.transition_to(ClaudeQueueJobStatus.RUNNING)
        entry.error_text = 'Merge-Konflikt gegen den Epic-Branch'
        entry.transition_to(ClaudeQueueJobStatus.FAILED)

        self.assertEqual(advance_epic(node), ADVANCE_HALTED)
        state = chain_state(node)
        self.assertTrue(state.is_halted)
        self.assertEqual(state.current.item_id, self.data_model.id)
        self.assertIn('Merge-Konflikt', state.reason)

    def test_done_but_unmerged_waits_without_releasing(self):
        node = self._epic_node()
        advance_epic(node)
        self._finish(self._entry(node, self.data_model), merged=False)

        self.assertEqual(advance_epic(node), ADVANCE_WAITING)
        self.assertEqual(
            self._entry(node, self.logic).status, ClaudeQueueJobStatus.BLOCKED,
        )

    def test_a_retriggered_sub_run_rejoins_the_chain_and_unblocks_it(self):
        node = self._epic_node()
        advance_epic(node)
        entry = self._entry(node, self.data_model)
        entry.transition_to(ClaudeQueueJobStatus.RUNNING)
        entry.transition_to(ClaudeQueueJobStatus.FAILED)
        self.assertEqual(advance_epic(node), ADVANCE_HALTED)

        retry, created = enqueue_item_for_claude(self.data_model)
        self.assertTrue(created)
        self.assertEqual(retry.parent_job_id, node.pk)
        self.assertEqual(retry.epic_order, 10)

        self._finish(retry)
        self.assertEqual(advance_epic(node), ADVANCE_RELEASED)
        self.assertEqual(
            self._entry(node, self.logic).status, ClaudeQueueJobStatus.QUEUED,
        )

    def test_a_closed_sub_issue_halts_instead_of_being_worked(self):
        node = self._epic_node()
        self.data_model.status = ItemStatus.CLOSED
        self.data_model.save(update_fields=['status'])

        self.assertEqual(advance_epic(node), ADVANCE_HALTED)
        self.assertEqual(
            self._entry(node, self.data_model).status, ClaudeQueueJobStatus.BLOCKED,
        )
        node.refresh_from_db()
        self.assertIn('geschlossen', node.error_text)
        # Still orchestrating: fixing the item and letting the sweep retry is
        # the intended recovery, not restarting the whole epic.
        self.assertEqual(node.status, ClaudeQueueJobStatus.ORCHESTRATING)

    def test_a_node_that_is_not_orchestrating_never_advances(self):
        node = self._epic_node(status=ClaudeQueueJobStatus.QUEUED)
        self.assertEqual(advance_epic(node), ADVANCE_INACTIVE)
        self.assertEqual(
            self._entry(node, self.data_model).status, ClaudeQueueJobStatus.BLOCKED,
        )


class FinalEpicPrTests(OrchestrationTestBase):

    def _complete_all_subs(self, node):
        for item in (self.data_model, self.logic, self.ui):
            advance_epic(node)
            self._finish(self._entry(node, item))

    @patch('core.services.claude_queue.orchestration.ensure_epic_pr')
    def test_last_merge_opens_the_draft_epic_pr_and_finishes_the_node(self, ensure):
        ensure.return_value = ExternalIssueMapping(
            number=99, state='open',
            html_url='https://github.com/testowner/testrepo/pull/99',
        )
        node = self._epic_node()
        self._complete_all_subs(node)

        self.assertEqual(advance_epic(node), ADVANCE_FINISHED)
        ensure.assert_called_once()
        node.refresh_from_db()
        self.assertEqual(node.status, ClaudeQueueJobStatus.DONE)
        self.assertEqual(node.pr_number, 99)

    @patch('core.services.claude_queue.orchestration.ensure_epic_pr')
    def test_an_unreachable_github_keeps_the_node_orchestrating(self, ensure):
        ensure.return_value = None
        node = self._epic_node()
        self._complete_all_subs(node)

        self.assertEqual(advance_epic(node), ADVANCE_WAITING)
        node.refresh_from_db()
        self.assertEqual(node.status, ClaudeQueueJobStatus.ORCHESTRATING)
        self.assertIn('Epic-PR', node.error_text)


class ChainStateTests(OrchestrationTestBase):

    def test_label_names_the_sub_issue_the_chain_is_paused_at(self):
        node = self._epic_node()
        advance_epic(node)
        self._finish(self._entry(node, self.data_model))
        advance_epic(node)
        self._finish(self._entry(node, self.logic), uncertain=True)

        state = chain_state(node)
        self.assertTrue(state.is_halted)
        self.assertEqual(state.done, 1)
        self.assertEqual(state.total, 3)
        self.assertEqual(state.position, '2/3')
        self.assertIn(f'#{self.logic.id}', state.label)
        self.assertIn('Pausiert', state.label)

    def test_blocked_chain_reports_the_next_entry_awaiting_release(self):
        state = chain_state(self._epic_node())
        self.assertEqual(state.current_state, SUB_BLOCKED)
        self.assertEqual(state.done, 0)
        self.assertFalse(state.finished)

    def test_epic_chain_property_is_none_for_a_plain_issue_run(self):
        job = ClaudeQueueJob.objects.create(item=self.ui, project=self.project)
        self.assertIsNone(job.epic_chain)


class SweepTests(OrchestrationTestBase):

    def test_sweep_advances_orchestrating_nodes_only(self):
        node = self._epic_node()
        idle = self._epic_node(status=ClaudeQueueJobStatus.QUEUED)

        self.assertEqual(advance_all_epics(), 1)
        self.assertEqual(
            self._entry(node, self.data_model).status, ClaudeQueueJobStatus.QUEUED,
        )
        self.assertEqual(
            self._entry(idle, self.data_model).status, ClaudeQueueJobStatus.BLOCKED,
        )

    def test_merge_webhook_entry_point_advances_the_items_chain(self):
        node = self._epic_node()
        advance_epic(node)
        self._finish(self._entry(node, self.data_model))

        self.assertEqual(advance_epic_for_item(self.data_model), ADVANCE_RELEASED)

    def test_merge_webhook_entry_point_is_a_no_op_outside_an_epic(self):
        standalone = self._item('Einzel-Issue')
        self.assertEqual(advance_epic_for_item(standalone), ADVANCE_INACTIVE)


class EpicEnqueueTests(OrchestrationTestBase):

    def test_enqueueing_an_epic_creates_an_epic_node_without_a_hint(self):
        from core.services.claude_queue.hint import GIT_WORKFLOW_HINT_MARKER

        job, created = enqueue_epic_for_claude(self.epic)
        self.assertTrue(created)
        self.assertTrue(job.is_epic_node)
        self.assertEqual(job.status, ClaudeQueueJobStatus.QUEUED)

        self.epic.refresh_from_db()
        self.assertEqual(self.epic.status, ItemStatus.WORKING)
        self.assertNotIn(GIT_WORKFLOW_HINT_MARKER, self.epic.description)

    def test_re_enqueueing_a_running_epic_returns_the_same_node(self):
        job, _ = enqueue_epic_for_claude(self.epic)
        again, created = enqueue_epic_for_claude(self.epic)
        self.assertFalse(created)
        self.assertEqual(again.pk, job.pk)

    def test_start_step_builds_the_chain_and_releases_the_first_layer(self):
        node, _ = enqueue_epic_for_claude(self.epic)
        node.transition_to(ClaudeQueueJobStatus.RUNNING)

        self.assertEqual(start_epic(node), ADVANCE_RELEASED)
        node.refresh_from_db()
        self.assertEqual(node.status, ClaudeQueueJobStatus.ORCHESTRATING)
        self.assertEqual(node.sub_jobs.count(), 3)
        self.assertEqual(
            self._entry(node, self.data_model).status, ClaudeQueueJobStatus.QUEUED,
        )

    def test_a_blocked_entry_is_not_re_enqueued_as_a_duplicate(self):
        node = self._epic_node()
        job, created = enqueue_item_for_claude(self.data_model)
        self.assertFalse(created)
        self.assertEqual(job.pk, self._entry(node, self.data_model).pk)


class FlatFlowUnchangedTests(OrchestrationTestBase):
    """The pre-#1079 single-issue path must be bit-for-bit what it was."""

    def test_a_standalone_item_is_enqueued_flat(self):
        standalone = self._item('Einzel-Issue')
        job, created = enqueue_item_for_claude(standalone)

        self.assertTrue(created)
        self.assertFalse(job.is_epic_node)
        self.assertIsNone(job.parent_job_id)
        self.assertEqual(job.epic_order, 0)
        self.assertEqual(job.status, ClaudeQueueJobStatus.QUEUED)
        standalone.refresh_from_db()
        self.assertEqual(standalone.status, ItemStatus.WORKING)

    def test_a_sub_issue_enqueued_without_an_active_epic_stays_unattached(self):
        # ``data_model`` is the lowest-ordered layer: it has no predecessors, so
        # it can start on its own and a flat enqueue is legitimate.
        job, created = enqueue_item_for_claude(self.data_model)
        self.assertTrue(created)
        self.assertIsNone(job.parent_job_id)


class SubIssueDeadEndTests(OrchestrationTestBase):
    """The #1109 dead-end: a sub-issue handed to Claude outside its epic.

    ``ui`` (order 30) has two unmerged predecessors and no epic node driving
    it. Before the fix such a job was created ``queued``, then silently
    excluded by the worker's block gate forever — no log, no status, no error.
    """

    def test_standalone_sub_issue_with_unmerged_predecessors_is_rejected(self):
        with self.assertRaises(SubIssueOutsideEpic) as ctx:
            enqueue_item_for_claude(self.ui)

        message = str(ctx.exception)
        self.assertIn(f'#{self.ui.id}', message)
        self.assertIn(f'#{self.epic.id}', message)
        # Rejected cleanly: no job, and the item was not dragged into Working.
        self.assertFalse(
            ClaudeQueueJob.objects.filter(item=self.ui).exists()
        )
        self.ui.refresh_from_db()
        self.assertNotEqual(self.ui.status, ItemStatus.WORKING)

    def test_startable_sub_issue_is_still_allowed_standalone(self):
        # The lowest layer has no predecessors — running it alone is fine and
        # must not be swept up by the guard.
        job, created = enqueue_item_for_claude(self.data_model)
        self.assertTrue(created)
        self.assertIsNone(job.parent_job_id)

    def test_sub_issue_becomes_enqueueable_once_predecessors_merged(self):
        self._merge(self.data_model)
        self._merge(self.logic)

        job, created = enqueue_item_for_claude(self.ui)

        self.assertTrue(created)
        self.assertIsNone(job.parent_job_id)

    def test_starting_the_epic_attaches_the_sub_issue_instead_of_dead_ending(self):
        # The recommended path: start the epic, then the same sub-issue enqueue
        # rejoins the chain rather than being refused or stranded.
        node = self._epic_node()

        job, created = enqueue_item_for_claude(self.ui)

        self.assertFalse(created)  # already has a blocked chain entry
        self.assertEqual(job.parent_job_id, node.pk)


class SubIssueReleaseOrderTests(OrchestrationTestBase):
    """AC2: starting an epic runs the sub-issues in order; none stays blocked."""

    @patch('core.services.claude_queue.orchestration.ensure_epic_pr')
    def test_each_layer_is_released_only_after_the_previous_one_merged(self, ensure):
        ensure.return_value = ExternalIssueMapping(
            number=99, state='open',
            html_url='https://github.com/testowner/testrepo/pull/99',
        )
        node, _ = enqueue_epic_for_claude(self.epic)
        node.transition_to(ClaudeQueueJobStatus.RUNNING)
        start_epic(node)

        order = [self.data_model, self.logic, self.ui]
        released = []
        for expected in order:
            entry = self._entry(node, expected)
            self.assertEqual(
                entry.status, ClaudeQueueJobStatus.QUEUED,
                f'sub-issue #{expected.id} was not released in turn',
            )
            released.append(entry.item_id)
            # Everything after it is still visibly blocked, not silently queued.
            for later in order[len(released):]:
                self.assertEqual(
                    self._entry(node, later).status,
                    ClaudeQueueJobStatus.BLOCKED,
                )
            self._finish(entry)
            advance_epic(node)

        self.assertEqual(released, [i.id for i in order])
        # No sub-entry is left stranded: all merged, node finished.
        self.assertFalse(
            node.sub_jobs.filter(status=ClaudeQueueJobStatus.BLOCKED).exists()
        )

    def test_blocked_entry_reports_which_predecessor_it_waits_on(self):
        # AC1: a blocked sub-entry is legible, not an anonymous queued row.
        node = self._epic_node()
        advance_epic(node)  # releases data_model; logic + ui stay blocked
        self._finish(self._entry(node, self.data_model))

        ui_entry = self._entry(node, self.ui)
        reason = ui_entry.blocked_reason
        # data_model merged, logic not — so logic is the pending predecessor.
        self.assertIn(f'#{self.logic.id}', reason)
        self.assertNotIn(f'#{self.data_model.id}', reason)
