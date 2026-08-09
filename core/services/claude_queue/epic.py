"""Epic-branch workflow: ordering, start gate and the final epic PR (#1076).

An *epic* here is one vertical slice cut into layers — data model, then
logic, then UI — where the sub-issues are not independent features but parts
of a single thing. Two consequences drive this module:

**The epic is the unit of testability, not the sub-issue.** A data-model-only
sub-issue cannot be run, so there is nothing to verify per layer. Sub-issue
PRs therefore squash-merge into the epic branch on CI-green alone, and the
one human review happens on the assembled epic before it reaches ``main``.

**The order is not arbitrary.** Building the UI before its model exists is
how an agent ends up inventing a mock for the missing foundation: CI goes
green, the PR looks fine, and nobody notices the layer was stacked on a prop.
:func:`blocking_predecessors` is the gate that prevents it — a sub-issue may
only start once every lower-ordered sibling has actually merged into the epic
branch. The order comes from ``Item.epic_order``, a flat number rather than a
dependency graph, deliberately: a graph is more expressive and much harder to
see wrong at a glance.

The queue-side orchestration that drives a chain forward (advancement only on
unambiguous success, halt on error) lives in #1079; this module owns only the
branch-model facts it needs to answer.
"""

import logging

from core.models import ExternalIssueKind, ExternalIssueMapping
from core.services.claude_queue.branch import (
    DEFAULT_BASE_BRANCH,
    build_epic_branch_name,
)

logger = logging.getLogger(__name__)

# ``ExternalIssueMapping.state`` value that means "landed". Written by the
# GitHub PR webhook (see GitHubService._map_state).
MERGED_STATE = 'merged'


def is_epic(item) -> bool:
    """True if ``item`` has sub-issues, i.e. it drives an epic branch.

    An epic is recognised implicitly by having children rather than by a
    dedicated flag: the parent relation is already the thing that makes the
    sub-issues branch off the epic branch, so a second, independently
    settable marker could only ever disagree with it.
    """
    return item.children.exists()


def ordered_sub_issues(epic):
    """Sub-issues of ``epic`` in execution order.

    ``epic_order`` ascending, item id as the tie-breaker so equal (or
    all-default zero) order values still yield a stable, reproducible
    sequence instead of whatever the database feels like returning.
    """
    return epic.children.order_by('epic_order', 'id')


def is_merged(item) -> bool:
    """True if a PR of ``item`` has merged (into the epic branch, or ``main``)."""
    return item.external_mappings.filter(
        kind=ExternalIssueKind.PR, state=MERGED_STATE,
    ).exists()


def blocking_predecessors(item) -> list:
    """Sub-issues that must merge before ``item`` may start.

    Empty for an item without a parent — an item outside an epic is never
    gated, which is what keeps the pre-#1076 flow untouched.
    """
    if item.parent_id is None:
        return []

    position = (item.epic_order, item.id)
    predecessors = [
        sibling
        for sibling in ordered_sub_issues(item.parent)
        if (sibling.epic_order, sibling.id) < position
    ]
    if not predecessors:
        return []

    merged_ids = set(
        ExternalIssueMapping.objects.filter(
            item_id__in=[p.id for p in predecessors],
            kind=ExternalIssueKind.PR,
            state=MERGED_STATE,
        ).values_list('item_id', flat=True)
    )
    return [p for p in predecessors if p.id not in merged_ids]


def can_start(item) -> bool:
    """True if every predecessor of ``item`` inside its epic has merged."""
    return not blocking_predecessors(item)


def next_sub_issue(epic):
    """The sub-issue of ``epic`` that is up next, or None if the epic is done.

    The first not-yet-merged sub-issue in order. By construction everything
    before it has merged, so the answer is always startable — there is no
    "skip the blocked one and take a later layer", because a later layer
    without its foundation is precisely the case this workflow rules out.
    """
    for sub_issue in ordered_sub_issues(epic):
        if not is_merged(sub_issue):
            return sub_issue
    return None


def all_sub_issues_merged(epic) -> bool:
    """True if ``epic`` has sub-issues and every one of them has merged."""
    sub_issues = list(ordered_sub_issues(epic))
    return bool(sub_issues) and all(is_merged(s) for s in sub_issues)


def epic_pr_body(epic) -> str:
    """Body for the final epic → ``main`` PR."""
    lines = [
        f"Epic-PR für Agira Item #{epic.id}: **{epic.title}**",
        '',
        'Sammelt die Sub-Issues dieses Epics, die einzeln in den Epic-Branch '
        'gemergt wurden. Bewusst als **Draft**: Review und Merge nach '
        f'`{DEFAULT_BASE_BRANCH}` erfolgen manuell.',
        '',
        '## Sub-Issues (in Reihenfolge)',
        '',
    ]
    for sub_issue in ordered_sub_issues(epic):
        marker = 'x' if is_merged(sub_issue) else ' '
        lines.append(
            f"- [{marker}] `{sub_issue.epic_order}` #{sub_issue.id} {sub_issue.title}"
        )
    return '\n'.join(lines) + '\n'


def ensure_epic_pr(epic, *, actor=None):
    """Open the final epic → ``main`` PR as a Draft, exactly once.

    Draft on purpose: the epic PR is the *only* place the assembled slice is
    reviewed by a human, so it must not be auto-mergeable. Returns the
    ``ExternalIssueMapping`` of the new or already-open PR, or None when
    GitHub could not be reached — a failure here is a missing convenience,
    not a reason to fail the merge event that triggered it.
    """
    from core.services.github.service import GitHubService

    branch = build_epic_branch_name(epic)
    service = GitHubService()

    try:
        existing = service.find_open_pr_for_branch(epic, branch)
        if existing is not None:
            return existing
        return service.create_draft_pr_for_item(
            epic,
            branch_name=branch,
            base=DEFAULT_BASE_BRANCH,
            title=f"Epic #{epic.id}: {epic.title}",
            body=epic_pr_body(epic),
            actor=actor,
        )
    except Exception as exc:  # noqa: BLE001 — best effort, never break the caller
        logger.warning(
            "Could not open the epic PR for item #%s (branch %s): %s",
            epic.id, branch, exc,
        )
        return None


def sub_issue_position(item) -> str:
    """Human-readable position of a sub-issue inside its epic, e.g. "2/3"."""
    if item.parent_id is None:
        return ''
    siblings = list(ordered_sub_issues(item.parent).values_list('id', flat=True))
    try:
        return f"{siblings.index(item.id) + 1}/{len(siblings)}"
    except ValueError:  # pragma: no cover — item is always among its siblings
        return ''
