"""Tests for the epic-branch workflow (#1076): branch derivation, the strict
order gate inside an epic, and the final epic → main draft PR."""

from unittest.mock import patch

from django.test import TestCase

from core.models import (
    ExternalIssueKind,
    ExternalIssueMapping,
    Item,
    ItemType,
    Project,
)
from core.services.claude_queue.branch import (
    DEFAULT_BASE_BRANCH,
    build_epic_branch_name,
    is_epic_branch,
    resolve_base_branch,
)
from core.services.claude_queue.epic import (
    all_sub_issues_merged,
    blocking_predecessors,
    can_start,
    ensure_epic_pr,
    epic_pr_body,
    is_epic,
    next_sub_issue,
    ordered_sub_issues,
    sub_issue_position,
)
from core.services.claude_queue.hint import (
    GIT_WORKFLOW_HINT_MARKER,
    ensure_git_workflow_hint,
)


class EpicTestBase(TestCase):
    """Fixture: an epic with three ordered sub-issues (data model → logic → UI)."""

    def setUp(self):
        self.project = Project.objects.create(
            name='Test Project', github_owner='testowner', github_repo='testrepo',
        )
        self.item_type = ItemType.objects.create(key='feature', name='Feature')
        self.epic = self._item('Kundenportal Freigaben')
        self.data_model = self._item('Datenmodell', parent=self.epic, epic_order=10)
        self.logic = self._item('Methoden und Logik', parent=self.epic, epic_order=20)
        self.ui = self._item('UI', parent=self.epic, epic_order=30)

    def _item(self, title, *, parent=None, epic_order=0):
        return Item.objects.create(
            title=title,
            project=self.project,
            type=self.item_type,
            parent=parent,
            epic_order=epic_order,
        )

    def _merge(self, item, number=None):
        """Record a merged PR mapping for ``item``, as the webhook would."""
        number = number or item.id
        return ExternalIssueMapping.objects.create(
            item=item,
            github_id=100000 + number,
            number=number,
            kind=ExternalIssueKind.PR,
            state='merged',
            html_url=f'https://github.com/testowner/testrepo/pull/{number}',
        )


class EpicBranchNameTestCase(EpicTestBase):
    def test_epic_branch_is_derived_from_the_parent_item(self):
        self.assertEqual(
            build_epic_branch_name(self.epic),
            f'feature/{self.epic.id}-kundenportal-freigaben',
        )

    def test_epic_branch_falls_back_to_bare_id_for_an_empty_slug(self):
        epic = self._item('???')
        self.assertEqual(build_epic_branch_name(epic), f'feature/{epic.id}')

    def test_sub_issue_branches_off_the_parents_epic_branch(self):
        self.assertEqual(
            resolve_base_branch(self.data_model), build_epic_branch_name(self.epic),
        )

    def test_item_without_parent_keeps_branching_off_main(self):
        self.assertEqual(resolve_base_branch(self.epic), DEFAULT_BASE_BRANCH)
        self.assertEqual(resolve_base_branch(self._item('Standalone')), DEFAULT_BASE_BRANCH)

    def test_is_epic_branch_distinguishes_feature_from_main_and_fix(self):
        self.assertTrue(is_epic_branch(build_epic_branch_name(self.epic)))
        self.assertFalse(is_epic_branch(DEFAULT_BASE_BRANCH))
        self.assertFalse(is_epic_branch('fix/12-something'))


class GitWorkflowHintTestCase(EpicTestBase):
    def test_sub_issue_hint_names_the_epic_branch_as_base(self):
        ensure_git_workflow_hint(self.data_model)

        epic_branch = build_epic_branch_name(self.epic)
        self.assertIn(GIT_WORKFLOW_HINT_MARKER, self.data_model.description)
        self.assertIn(f'vom Epic-Branch `{epic_branch}`', self.data_model.description)
        self.assertIn(f'PR gegen `{epic_branch}`', self.data_model.description)
        self.assertNotIn('Draft-PR', self.data_model.description)

    def test_item_without_parent_keeps_the_main_based_hint(self):
        standalone = self._item('Standalone')
        ensure_git_workflow_hint(standalone)

        self.assertIn('von `main`, Draft-PR', standalone.description)
        self.assertNotIn('Epic-Branch', standalone.description)


class EpicOrderingTestCase(EpicTestBase):
    def test_is_epic_is_true_only_for_items_with_sub_issues(self):
        self.assertTrue(is_epic(self.epic))
        self.assertFalse(is_epic(self.data_model))

    def test_sub_issues_are_ordered_by_epic_order_not_creation(self):
        late_but_first = self._item('Migration', parent=self.epic, epic_order=5)

        self.assertEqual(
            [i.id for i in ordered_sub_issues(self.epic)],
            [late_but_first.id, self.data_model.id, self.logic.id, self.ui.id],
        )

    def test_equal_order_falls_back_to_item_id(self):
        epic = self._item('Flat epic')
        first = self._item('A', parent=epic)
        second = self._item('B', parent=epic)

        self.assertEqual(
            [i.id for i in ordered_sub_issues(epic)], [first.id, second.id],
        )


class EpicStartGateTestCase(EpicTestBase):
    def test_first_sub_issue_may_start_immediately(self):
        self.assertEqual(blocking_predecessors(self.data_model), [])
        self.assertTrue(can_start(self.data_model))

    def test_later_layer_is_blocked_while_its_foundation_is_open(self):
        self.assertFalse(can_start(self.ui))
        self.assertEqual(
            [i.id for i in blocking_predecessors(self.ui)],
            [self.data_model.id, self.logic.id],
        )

    def test_layer_unblocks_once_every_predecessor_merged(self):
        self._merge(self.data_model)
        self.assertTrue(can_start(self.logic))
        self.assertFalse(can_start(self.ui))

        self._merge(self.logic)
        self.assertTrue(can_start(self.ui))

    def test_an_open_pr_does_not_unblock_the_next_layer(self):
        ExternalIssueMapping.objects.create(
            item=self.data_model,
            github_id=555,
            number=555,
            kind=ExternalIssueKind.PR,
            state='open',
            html_url='https://github.com/testowner/testrepo/pull/555',
        )
        self.assertFalse(can_start(self.logic))

    def test_item_outside_an_epic_is_never_gated(self):
        self.assertTrue(can_start(self._item('Standalone')))
        self.assertTrue(can_start(self.epic))

    def test_next_sub_issue_follows_the_order_field(self):
        self.assertEqual(next_sub_issue(self.epic), self.data_model)

        self._merge(self.data_model)
        self.assertEqual(next_sub_issue(self.epic), self.logic)

        self._merge(self.logic)
        self._merge(self.ui)
        self.assertIsNone(next_sub_issue(self.epic))

    def test_next_sub_issue_never_skips_ahead_to_an_unblocked_later_layer(self):
        # UI merged out of band; the data model is still open. The next
        # sub-issue must stay the open foundation, not the merged top layer.
        self._merge(self.ui)
        self.assertEqual(next_sub_issue(self.epic), self.data_model)

    def test_all_sub_issues_merged_requires_sub_issues_to_exist(self):
        self.assertFalse(all_sub_issues_merged(self._item('Childless')))

        for sub_issue in (self.data_model, self.logic, self.ui):
            self.assertFalse(all_sub_issues_merged(self.epic))
            self._merge(sub_issue)
        self.assertTrue(all_sub_issues_merged(self.epic))

    def test_sub_issue_position_is_human_readable(self):
        self.assertEqual(sub_issue_position(self.logic), '2/3')
        self.assertEqual(sub_issue_position(self.epic), '')


class EnsureEpicPrTestCase(EpicTestBase):
    def test_opens_a_draft_pr_from_the_epic_branch_to_main(self):
        with patch('core.services.github.service.GitHubService') as service_cls:
            service = service_cls.return_value
            service.find_open_pr_for_branch.return_value = None

            ensure_epic_pr(self.epic)

        kwargs = service.create_draft_pr_for_item.call_args.kwargs
        self.assertEqual(kwargs['branch_name'], build_epic_branch_name(self.epic))
        self.assertEqual(kwargs['base'], DEFAULT_BASE_BRANCH)
        # No draft=False override: the epic PR is the one a human reviews.
        self.assertNotIn('draft', kwargs)

    def test_reuses_an_already_open_epic_pr(self):
        with patch('core.services.github.service.GitHubService') as service_cls:
            service = service_cls.return_value
            service.find_open_pr_for_branch.return_value = 'existing-mapping'

            self.assertEqual(ensure_epic_pr(self.epic), 'existing-mapping')

        service.create_draft_pr_for_item.assert_not_called()

    def test_github_failure_is_swallowed(self):
        with patch('core.services.github.service.GitHubService') as service_cls:
            service_cls.return_value.find_open_pr_for_branch.side_effect = RuntimeError('boom')

            self.assertIsNone(ensure_epic_pr(self.epic))

    def test_body_lists_the_sub_issues_in_order_with_merge_state(self):
        self._merge(self.data_model)
        body = epic_pr_body(self.epic)

        self.assertIn(f'- [x] `10` #{self.data_model.id} Datenmodell', body)
        self.assertIn(f'- [ ] `20` #{self.logic.id} Methoden und Logik', body)
        self.assertLess(
            body.index(f'#{self.data_model.id}'), body.index(f'#{self.ui.id}'),
        )
