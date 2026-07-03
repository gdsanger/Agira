"""Deterministic branch-name derivation for the Claude queue (#833).

The branch name is a contract shared with the worker/PR-bootstrap step
(#832): both sides must derive the exact same ``fix/<id>-<slug>`` value from
an item, independently, without either one calling into the other.
"""

from django.utils.text import slugify


def build_branch_name(item) -> str:
    """Return the contract branch name ``fix/<id>-<slug>`` for an item.

    The item id prefix keeps the branch unique and greppable even when two
    items share a title; the slug is truncated to keep the ref sane.
    """
    slug = slugify(item.title or '')[:60].strip('-')
    return f"fix/{item.id}-{slug}" if slug else f"fix/{item.id}"
