"""Which agent provider reviews an item (#1300).

One rule, one place: the UI, the enqueue guards and the tests all ask
:func:`effective_review_provider`.

* ``item.review_provider`` set → that provider (manual override).
* otherwise the *other* one than the provider of the item's last successful
  implementation run. Without such a run (or if its provider is unknown) the
  item's ``implementation_provider`` stands in for it.
"""

from core.models import (
    AgentProvider,
    ClaudeQueueJob,
    ClaudeQueueJobKind,
    ClaudeQueueJobStatus,
)


def other_provider(provider) -> str:
    """The provider that is not ``provider`` (unknown values count as Claude)."""
    if provider == AgentProvider.CLAUDE:
        return AgentProvider.OPENAI
    if provider == AgentProvider.OPENAI:
        return AgentProvider.CLAUDE
    return AgentProvider.OPENAI


def last_implementation_provider(item):
    """Provider of the newest successful implementation job, else ``None``.

    Only ``issue`` jobs count: review jobs and epic nodes implement nothing.
    A run flagged ``completion_uncertain`` is not a clean success.
    """
    provider = (
        ClaudeQueueJob.objects.filter(
            item=item,
            kind=ClaudeQueueJobKind.ISSUE,
            status=ClaudeQueueJobStatus.DONE,
            completion_uncertain=False,
        )
        .order_by('-created_at', '-id')
        .values_list('provider', flat=True)
        .first()
    )
    return provider or None


def effective_review_provider(item) -> str:
    """Resolve the provider that reviews ``item`` (see module docstring)."""
    explicit = getattr(item, 'review_provider', '') or ''
    if explicit in AgentProvider.values:
        return explicit
    implemented_by = last_implementation_provider(item)
    if implemented_by not in AgentProvider.values:
        implemented_by = getattr(item, 'implementation_provider', None)
    return other_provider(implemented_by)
