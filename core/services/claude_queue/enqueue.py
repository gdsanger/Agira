"""Enqueue an item for Claude Code processing (#833).

The UI entry point into the Claude queue pipeline: creates a queued
``ClaudeQueueJob``, force-appends the git-workflow hint to the item's
description, and moves the item to ``Working``. Re-enqueueing an item that
already has an active job is a no-op (returns the existing job) so a stray
double-click can't spawn duplicate jobs for the same item.
"""

from django.db import transaction

from core.models import (
    CLAUDE_CLI_MODEL_IDS,
    ClaudeQueueJob,
    ClaudeQueueJobAuthMode,
    ClaudeQueueJobModel,
    ClaudeQueueJobStatus,
    Item,
    ItemStatus,
)
from core.services.activity import ActivityService
from core.services.claude_queue.credentials import (
    resolve_claude_credential,
    resolve_credential_user,
)
from core.services.claude_queue.hint import ensure_git_workflow_hint
from core.services.workflow.item_workflow_guard import ItemWorkflowGuard

DEFAULT_CLAUDE_MODEL = ClaudeQueueJobModel.SONNET


class InvalidClaudeModel(ValueError):
    """The item's resolved Claude model has no known CLI translation (#1090).

    Raised before the job — and the item's transition to Working — is
    created, so a stale or unmapped model slug is rejected at the button
    instead of reaching the CLI and failing minutes into a run (see #1090:
    ``opus-5``/``opus-4-8`` reaching the CLI unmapped burned two jobs on
    Item #1085). The message is user-facing.
    """


def _resolve_model(item) -> str:
    """Return the Claude model to run this item with.

    The item's `suggested_model` wins; DEFAULT_CLAUDE_MODEL is the fallback for
    items that carry no suggestion at all. The result is guaranteed to have a
    known ``claude --model`` translation (see ``CLAUDE_CLI_MODEL_IDS``) —
    anything else is rejected here rather than passed through.
    """
    model = getattr(item, 'suggested_model', None) or DEFAULT_CLAUDE_MODEL
    if model not in CLAUDE_CLI_MODEL_IDS:
        raise InvalidClaudeModel(
            f'Ungültiges Claude-Modell „{model}“ – kein bekannter '
            f'CLI-Modellbezeichner hinterlegt. Bitte ein gültiges Modell wählen.'
        )
    return model


def _resolve_auth_mode(item) -> str:
    """Return the auth mode the item asks its Claude runs to use (#1083).

    The item's own field wins — that is the per-issue ABO/API switch. A blank
    value (rows predating the field) falls back to the subscription default.
    """
    return getattr(item, 'claude_auth_mode', None) or ClaudeQueueJobAuthMode.OAUTH


def enqueue_item_for_claude(
    item: Item, *, actor=None, allow_api_key_fallback: bool = False,
) -> tuple[ClaudeQueueJob, bool]:
    """Hand ``item`` off to the Claude queue.

    The run's auth is decided here and frozen on the job (#1083): the item's
    ``claude_auth_mode`` (ABO by default) plus the user whose credential pays
    for it (see ``resolve_credential_user``). Freezing both at enqueue time
    means a later edit of the item cannot retroactively re-attribute a run.

    ``allow_api_key_fallback`` is a static per-job property: when set, a run
    that hits the subscription limit is re-run on the paid API key instead of
    waiting for the quota rollover. It does not change the regular auth and is
    independent of current usage; default off = wait.

    Raises :class:`~core.services.claude_queue.credentials.MissingClaudeCredential`
    when the chosen mode has no usable credential, and :class:`InvalidClaudeModel`
    when the resolved model has no known CLI translation — both rejected at the
    button, before the item is moved, rather than a job that fails minutes later.

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

        auth_mode = _resolve_auth_mode(locked_item)
        auth_user = resolve_credential_user(locked_item, actor=actor)
        # Raises when the mode cannot be served — before the item is moved.
        resolve_claude_credential(auth_user, auth_mode)
        # Raises when the model has no known CLI translation — same reasoning.
        model = _resolve_model(locked_item)

        if ensure_git_workflow_hint(locked_item):
            locked_item.save()

        ItemWorkflowGuard().transition(locked_item, ItemStatus.WORKING, actor=actor)

        job = ClaudeQueueJob.objects.create(
            item=locked_item,
            project=locked_item.project,
            status=ClaudeQueueJobStatus.QUEUED,
            model=model,
            auth_user=auth_user,
            requested_auth_mode=auth_mode,
            auth_mode=auth_mode,
            allow_api_key_fallback=allow_api_key_fallback,
        )

    who = auth_user.username if auth_user else 'host'
    ActivityService().log(
        verb='item.claude_enqueued',
        target=locked_item,
        actor=actor,
        summary=(
            f'Enqueued for Claude Code (job #{job.pk}, model={model}, '
            f'auth={auth_mode} via {who})'
        ),
    )
    return job, True
