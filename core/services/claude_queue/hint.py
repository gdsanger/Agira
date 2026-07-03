"""Forced git-workflow hint on an item's description (#833).

Every item handed off to the Claude queue must carry a human- and
CLI-readable reminder of the git conventions the worker enforces (branch
naming, draft PR, no direct commits to main). The hint is force-appended to
``item.description`` on enqueue and guarded by a marker so re-enqueueing an
item never duplicates it.
"""

from core.services.claude_queue.branch import build_branch_name

GIT_WORKFLOW_HINT_MARKER = '<!-- claude-queue:git-workflow-hint -->'


def build_git_workflow_hint(branch_name: str) -> str:
    """Render the git-workflow hint block for a given branch name."""
    return (
        f"{GIT_WORKFLOW_HINT_MARKER}\n"
        "---\n"
        f"**Git-Workflow:** Branch `{branch_name}` von `main`, Draft-PR, "
        "keine direkten Commits auf `main`."
    )


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

    hint = build_git_workflow_hint(build_branch_name(item))
    separator = '\n\n' if description.strip() else ''
    item.description = f"{description.rstrip()}{separator}{hint}\n"
    return True
