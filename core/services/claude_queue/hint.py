"""Forced git-workflow hint on an item's description (#833, #1076).

Every item handed off to the Claude queue must carry a human- and
CLI-readable reminder of the git conventions the worker enforces (branch
naming, PR target, no direct commits to main). The hint is force-appended to
``item.description`` on enqueue and guarded by a marker so re-enqueueing an
item never duplicates it.

Since #1076 the hint also spells out the *base* branch, because that is no
longer always ``main``: a sub-issue of an epic branches off — and targets —
its parent's epic branch. This text ends up in the agent's prompt, so a wrong
base here is what would produce a PR against the wrong branch.
"""

from core.services.claude_queue.branch import (
    DEFAULT_BASE_BRANCH,
    build_branch_name,
    resolve_base_branch,
)

GIT_WORKFLOW_HINT_MARKER = '<!-- claude-queue:git-workflow-hint -->'


def build_git_workflow_hint(
    branch_name: str, base_branch: str = DEFAULT_BASE_BRANCH,
) -> str:
    """Render the git-workflow hint block for a branch and its base.

    The ``main``-based wording is unchanged from #833 (draft PR, merged by
    hand). A sub-issue of an epic gets the epic wording instead: a normal —
    not draft — PR against the epic branch that squash-auto-merges once CI and
    the review pass agree, because what a human reviews is the assembled epic,
    not the single layer.
    """
    if base_branch == DEFAULT_BASE_BRANCH:
        detail = (
            f"Branch `{branch_name}` von `{DEFAULT_BASE_BRANCH}`, Draft-PR, "
            f"keine direkten Commits auf `{DEFAULT_BASE_BRANCH}`."
        )
    else:
        detail = (
            f"Branch `{branch_name}` vom Epic-Branch `{base_branch}`, PR gegen "
            f"`{base_branch}` (kein Draft, Squash-Auto-Merge), keine direkten "
            f"Commits auf `{base_branch}` oder `{DEFAULT_BASE_BRANCH}`."
        )
    return f"{GIT_WORKFLOW_HINT_MARKER}\n---\n**Git-Workflow:** {detail}"


def ensure_git_workflow_hint(item) -> bool:
    """Force-append the git-workflow hint to ``item.description`` if missing.

    Idempotent: detects a prior hint via ``GIT_WORKFLOW_HINT_MARKER`` and
    leaves the description untouched on re-enqueue. Mutates ``item`` in
    place but does not save it — the caller controls persistence.

    Returns True if the hint was appended, False if it was already present.
    """
    description = item.description or ''
    if GIT_WORKFLOW_HINT_MARKER in description:
        return False

    hint = build_git_workflow_hint(
        build_branch_name(item), resolve_base_branch(item)
    )
    separator = '\n\n' if description.strip() else ''
    item.description = f"{description.rstrip()}{separator}{hint}\n"
    return True
