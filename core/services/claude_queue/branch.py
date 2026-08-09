"""Deterministic branch-name derivation for the Claude queue (#833, #1076).

The branch name is a contract shared with the worker/PR-bootstrap step
(#832): both sides must derive the exact same value from an item,
independently, without either one calling into the other.

Two branch kinds exist:

* ``fix/<id>-<slug>`` — the work branch of a single item.
* ``feature/<id>-<slug>`` — the long-lived *epic branch* of an item that has
  sub-issues (#1076). Sub-issues branch off it instead of ``main`` and their
  PRs target it, so a chain of layers can be worked without waiting for each
  layer to land on ``main`` first.

Which of the two an item branches *from* is decided by one rule and one rule
only: does it have a parent? No parent ⇒ ``main``, and the pre-#1076 flow is
unchanged — that is what keeps the epic workflow a capability rather than an
obligation.
"""

from django.utils.text import slugify

# The repository's protected trunk. The only branch a PR is never auto-merged
# into, and the fallback base for every item without a parent.
DEFAULT_BASE_BRANCH = 'main'

EPIC_BRANCH_PREFIX = 'feature/'


def _branch_slug(item) -> str:
    """Slugified item title, truncated to keep the ref sane."""
    return slugify(item.title or '')[:60].strip('-')


def build_branch_name(item) -> str:
    """Return the contract branch name ``fix/<id>-<slug>`` for an item.

    The item id prefix keeps the branch unique and greppable even when two
    items share a title; the slug is truncated to keep the ref sane.
    """
    slug = _branch_slug(item)
    return f"fix/{item.id}-{slug}" if slug else f"fix/{item.id}"


def build_epic_branch_name(item) -> str:
    """Return the epic branch ``feature/<id>-<slug>`` derived from an item.

    Derived from the epic item, never stored: the name has to be reproducible
    from the parent alone by every participant (enqueue, worker, webhook)
    without a shared record to look up and keep in sync.
    """
    slug = _branch_slug(item)
    if slug:
        return f"{EPIC_BRANCH_PREFIX}{item.id}-{slug}"
    return f"{EPIC_BRANCH_PREFIX}{item.id}"


def resolve_base_branch(item) -> str:
    """Return the branch ``item``'s work branch is cut from and its PR targets.

    An item with a parent is a sub-issue: it branches off the parent's epic
    branch. An item without a parent keeps the pre-#1076 behaviour and
    branches off ``main`` — the epic workflow is opted into by simply setting
    a parent, so a standalone or exploratory item is never dragged into it.
    """
    parent = getattr(item, 'parent', None)
    if parent is None:
        return DEFAULT_BASE_BRANCH
    return build_epic_branch_name(parent)


def is_epic_branch(branch_name: str) -> bool:
    """True for a ``feature/*`` epic branch (as opposed to ``main`` or a fix branch)."""
    return bool(branch_name) and branch_name.startswith(EPIC_BRANCH_PREFIX)
