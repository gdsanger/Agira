"""Enqueue an item for Claude Code processing (#833).

The UI entry point into the Claude queue pipeline: creates a queued
``ClaudeQueueJob``, force-appends the git-workflow hint to the item's
description, and moves the item to ``Working``. Re-enqueueing an item that
already has an active job is a no-op (returns the existing job) so a stray
double-click can't spawn duplicate jobs for the same item.
"""

from django.db import transaction

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobModel,
    ClaudeQueueJobStatus,
    Item,
    ItemStatus,
)
from core.services.activity import ActivityService
from core.services.claude_queue.hint import ensure_git_workflow_hint
from core.services.workflow.item_workflow_guard import ItemWorkflowGuard

# TODO(#834): once the model-selection agent lands, read `item.suggested_model`
# here instead of always defaulting to sonnet.
DEFAULT_CLAUDE_MODEL = ClaudeQueueJobModel.SONNET


def _resolve_model(item) -> str:
    """Return the Claude model to run this item with.

    Degrades gracefully to DEFAULT_CLAUDE_MODEL until #834 adds
    `suggested_model` to Item.
    """
    return getattr(item, 'suggested_model', None) or DEFAULT_CLAUDE_MODEL


def enqueue_item_for_claude(item: Item, *, actor=None) -> tuple[ClaudeQueueJob, bool]:
    """Hand ``item`` off to the Claude queue.

    Returns ``(job, created)``. ``created`` is False when the item already
    had a queued/running job — that job is returned unchanged instead of
    creating a duplicate.
    """
    with transaction.atomic():
        locked_item = Item.objects.select_for_update().get(pk=item.pk)

        existing_job = ClaudeQueueJob.objects.filter(
            item=locked_item,
            status__in=[ClaudeQueueJobStatus.QUEUED, ClaudeQueueJobStatus.RUNNING],
        ).order_by('-created_at').first()
        if existing_job is not None:
            return existing_job, False

        if ensure_git_workflow_hint(locked_item):
            locked_item.save()

        ItemWorkflowGuard().transition(locked_item, ItemStatus.WORKING, actor=actor)

        model = _resolve_model(locked_item)
        job = ClaudeQueueJob.objects.create(
            item=locked_item,
            project=locked_item.project,
            status=ClaudeQueueJobStatus.QUEUED,
            model=model,
        )

    ActivityService().log(
        verb='item.claude_enqueued',
        target=locked_item,
        actor=actor,
        summary=f'Enqueued for Claude Code (job #{job.pk}, model={model})',
    )
    return job, True
