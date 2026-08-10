"""Enqueue an item for Claude Code processing (#833, #1079).

The UI entry point into the Claude queue pipeline: creates a queued
``ClaudeQueueJob``, force-appends the git-workflow hint to the item's
description, and moves the item to ``Working``. Re-enqueueing an item that
already has an active job is a no-op (returns the existing job) so a stray
double-click can't spawn duplicate jobs for the same item.

An item that has sub-issues takes a different route (#1079): handing an epic
to Claude enqueues an *epic node*, which implements nothing and orchestrates
the chain of its sub-issues instead. Which of the two happens is decided by the
item alone (does it have children?) — the same rule that already decides
whether an item branches off ``main`` or off an epic branch, so there is no
second switch that could disagree with the first.
"""

from django.db import transaction

from core.models import (
    CLAUDE_CLI_MODEL_IDS,
    ClaudeQueueJob,
    ClaudeQueueJobAuthMode,
    ClaudeQueueJobKind,
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
    from core.services.claude_queue.orchestration import active_epic_job_for

    with transaction.atomic():
        locked_item = Item.objects.select_for_update().get(pk=item.pk)

        existing_job = ClaudeQueueJob.objects.filter(
            item=locked_item,
            status__in=[
                ClaudeQueueJobStatus.BLOCKED,
                ClaudeQueueJobStatus.QUEUED,
                ClaudeQueueJobStatus.RUNNING,
            ],
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

        # Re-triggering a halted sub-issue by hand must rejoin its chain, not
        # start a run beside it (#1079): the epic node reads the *newest* entry
        # per sub-issue, so an unattached retry would leave the chain stuck on
        # the failed attempt forever.
        parent_job = active_epic_job_for(locked_item)

        job = ClaudeQueueJob.objects.create(
            item=locked_item,
            project=locked_item.project,
            status=ClaudeQueueJobStatus.QUEUED,
            model=model,
            auth_user=auth_user,
            requested_auth_mode=auth_mode,
            auth_mode=auth_mode,
            allow_api_key_fallback=allow_api_key_fallback,
            parent_job=parent_job,
            epic_order=locked_item.epic_order if parent_job else 0,
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


def create_sub_issue_job(sub_issue: Item, epic_job: ClaudeQueueJob, *, actor=None):
    """Create the blocked chain entry for one sub-issue of an epic (#1079).

    Same freezing rules as a normal enqueue — model and auth are taken from the
    sub-issue now, not when the entry is eventually released — but the item is
    left where it is and no hint is written: both belong to the moment the
    entry actually starts (see ``orchestration.release_sub_job``), which may be
    days later.

    A missing credential or an unmappable model does *not* raise here. The
    chain is planned in one go, and refusing to plan it because layer three's
    model is stale would hide the two layers that are perfectly fine; the entry
    is created and fails at its own release, where the message is about it.
    """
    auth_mode = _resolve_auth_mode(sub_issue)
    auth_user = resolve_credential_user(sub_issue, actor=actor)
    try:
        model = _resolve_model(sub_issue)
    except InvalidClaudeModel:
        model = DEFAULT_CLAUDE_MODEL

    return ClaudeQueueJob.objects.create(
        item=sub_issue,
        project=sub_issue.project,
        status=ClaudeQueueJobStatus.BLOCKED,
        kind=ClaudeQueueJobKind.ISSUE,
        parent_job=epic_job,
        epic_order=sub_issue.epic_order,
        model=model,
        auth_user=auth_user,
        requested_auth_mode=auth_mode,
        auth_mode=auth_mode,
        allow_api_key_fallback=epic_job.allow_api_key_fallback,
    )


def enqueue_epic_for_claude(
    item: Item, *, actor=None, allow_api_key_fallback: bool = False,
) -> tuple[ClaudeQueueJob, bool]:
    """Enqueue ``item`` as an epic node that orchestrates its sub-issues (#1079).

    The node has nothing to implement, so nothing about the item's own code is
    prepared here — no git-workflow hint in particular, which would describe a
    ``fix/`` branch the epic never gets. What the node does get is ``Working``
    on its item: the epic *is* in progress from now on, and it leaves Working
    only when its own PR to ``main`` merges (#1076).

    The chain itself is built by the worker's start step, not here, so the
    sub-entries appear together with the epic branch they will target.

    Returns ``(job, created)``, with ``created`` False for an epic that is
    already queued or orchestrating — the chain is resumed, never doubled.
    """
    with transaction.atomic():
        locked_item = Item.objects.select_for_update().get(pk=item.pk)

        existing_job = ClaudeQueueJob.objects.filter(
            item=locked_item,
            kind=ClaudeQueueJobKind.EPIC,
            status__in=[
                ClaudeQueueJobStatus.QUEUED,
                ClaudeQueueJobStatus.RUNNING,
                ClaudeQueueJobStatus.ORCHESTRATING,
            ],
        ).order_by('-created_at').first()
        if existing_job is not None:
            return existing_job, False

        auth_mode = _resolve_auth_mode(locked_item)
        auth_user = resolve_credential_user(locked_item, actor=actor)
        # The node runs no CLI itself, but every sub-run below it will — so a
        # missing credential is worth rejecting at the button rather than one
        # layer in.
        resolve_claude_credential(auth_user, auth_mode)

        ItemWorkflowGuard().transition(locked_item, ItemStatus.WORKING, actor=actor)

        job = ClaudeQueueJob.objects.create(
            item=locked_item,
            project=locked_item.project,
            status=ClaudeQueueJobStatus.QUEUED,
            kind=ClaudeQueueJobKind.EPIC,
            model=_resolve_model_or_default(locked_item),
            auth_user=auth_user,
            requested_auth_mode=auth_mode,
            auth_mode=auth_mode,
            allow_api_key_fallback=allow_api_key_fallback,
        )

    ActivityService().log(
        verb='item.claude_epic_enqueued',
        target=locked_item,
        actor=actor,
        summary=f'Epic enqueued for Claude Code orchestration (job #{job.pk})',
    )
    return job, True


def _resolve_model_or_default(item) -> str:
    """Model for an epic node: the item's, or the default if it is unusable.

    An epic node never invokes a model, so a stale slug on the epic item is no
    reason to refuse the chain — unlike on an issue run, where it is.
    """
    try:
        return _resolve_model(item)
    except InvalidClaudeModel:
        return DEFAULT_CLAUDE_MODEL
