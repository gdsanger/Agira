"""Enqueue an item for agent processing (#833, #1079, #1300).

The UI entry point into the agent queue pipeline (Claude Code or OpenAI Codex, see ``provider``): creates a queued
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
    AgentProvider,
    ClaudeQueueJob,
    ClaudeQueueJobAuthMode,
    ClaudeQueueJobKind,
    ClaudeQueueJobModel,
    ClaudeQueueJobStatus,
    ExternalIssueKind,
    Item,
    ItemStatus,
    OpenAIQueueJobModel,
    provider_for_model,
)
from core.services.activity import ActivityService
from core.services.claude_queue.credentials import (
    resolve_claude_credential,
    resolve_credential_user,
    resolve_openai_credential,
)
from core.services.claude_queue.hint import ensure_git_workflow_hint
from core.services.claude_queue.provider_rule import effective_review_provider
from core.services.workflow.item_workflow_guard import ItemWorkflowGuard

DEFAULT_CLAUDE_MODEL = ClaudeQueueJobModel.SONNET
DEFAULT_OPENAI_MODEL = OpenAIQueueJobModel.GPT_5_CODEX


class InvalidClaudeModel(ValueError):
    """The item's resolved Claude model has no known CLI translation (#1090).

    Raised before the job — and the item's transition to Working — is
    created, so a stale or unmapped model slug is rejected at the button
    instead of reaching the CLI and failing minutes into a run (see #1090:
    ``opus-5``/``opus-4-8`` reaching the CLI unmapped burned two jobs on
    Item #1085). The message is user-facing.
    """


class SubIssueOutsideEpic(ValueError):
    """A sub-issue was handed to Claude standalone but cannot run yet (#1109).

    The item has a parent (it is a layer of an epic) and predecessors that
    have not merged, yet there is no active epic node to ever release it. Such
    a job would be excluded by the worker's ``_blocked_job_ids`` gate and sit
    in ``queued`` forever — indistinguishable from a claimable job, with no
    log, no status change, no error (#1109: Job #169 stalled silently for
    exactly this reason).

    Rejecting it at the button turns that silent dead-end into an actionable
    message: start the epic (which orchestrates the sub-issues in order and
    *does* advance the chain), or merge the predecessors first. The message is
    user-facing.
    """


class ReviewNotAllowed(ValueError):
    """The item cannot be handed to Claude for a review (#1286).

    Raised for an item outside ``Integrated``/``Testing`` or without a linked
    pull request. The message is user-facing.
    """


REVIEWABLE_STATUSES = (ItemStatus.INTEGRATED, ItemStatus.TESTING)


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


def _normalize_provider(provider) -> str:
    """Return a valid provider slug; unknown/empty falls back to Claude."""
    return provider if provider in AgentProvider.values else AgentProvider.CLAUDE


def _provider_label(provider) -> str:
    return 'OpenAI Codex' if provider == AgentProvider.OPENAI else 'Claude Code'


def _resolve_run_model(item, provider) -> str:
    """Model for a run of ``provider``.

    The item's ``suggested_model`` is used when it belongs to that provider.
    A model of the *other* provider (e.g. a review by OpenAI on an item with a
    Claude suggestion) is no error — it is simply not applicable, so the
    provider's default applies.
    """
    suggested = getattr(item, 'suggested_model', None)
    if provider == AgentProvider.OPENAI:
        if provider_for_model(suggested) == AgentProvider.OPENAI:
            return suggested
        return DEFAULT_OPENAI_MODEL
    if provider_for_model(suggested) == AgentProvider.OPENAI:
        return DEFAULT_CLAUDE_MODEL
    return _resolve_model(item)


def _resolve_run_auth(item, provider) -> str:
    """Auth mode frozen on a job: the item's for Claude, always API key for OpenAI."""
    if provider == AgentProvider.OPENAI:
        return ClaudeQueueJobAuthMode.API_KEY
    return _resolve_auth_mode(item)


def _check_credential(auth_user, provider, auth_mode) -> None:
    """Raise the provider's missing-credential error before anything is created."""
    if provider == AgentProvider.OPENAI:
        resolve_openai_credential(auth_user)
    else:
        resolve_claude_credential(auth_user, auth_mode)


def enqueue_item_for_claude(
    item: Item, *, actor=None, allow_api_key_fallback: bool = False, provider=None,
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
    from core.services.claude_queue.epic import can_start
    from core.services.claude_queue.orchestration import active_epic_job_for

    with transaction.atomic():
        locked_item = Item.objects.select_for_update().get(pk=item.pk)

        # A review job is not an implementation run (#1286); it must not make
        # the item look "already enqueued".
        existing_job = ClaudeQueueJob.objects.filter(
            item=locked_item,
            status__in=[
                ClaudeQueueJobStatus.BLOCKED,
                ClaudeQueueJobStatus.QUEUED,
                ClaudeQueueJobStatus.RUNNING,
            ],
        ).exclude(kind=ClaudeQueueJobKind.REVIEW).order_by('-created_at').first()
        if existing_job is not None:
            return existing_job, False

        # Re-triggering a halted sub-issue by hand must rejoin its chain, not
        # start a run beside it (#1079): the epic node reads the *newest* entry
        # per sub-issue, so an unattached retry would leave the chain stuck on
        # the failed attempt forever.
        parent_job = active_epic_job_for(locked_item)

        # Guard against the silent dead-end (#1109). A sub-issue with unmerged
        # predecessors and no epic node to release it would be blocked at claim
        # time (``_blocked_job_ids``) and never become claimable — ``can_start``
        # only turns True when a *predecessor* merges, and nothing here drives
        # that. It would sit in ``queued`` forever, looking exactly like a
        # normal one. Refuse it with an actionable message instead. A sub-issue
        # whose predecessors have all merged (``can_start``) is safe to run on
        # its own and is deliberately left alone, as is any item already
        # attached to an active chain.
        if (
            parent_job is None
            and locked_item.parent_id is not None
            and not can_start(locked_item)
        ):
            raise SubIssueOutsideEpic(
                f'Item #{locked_item.id} ist ein Sub-Issue von Epic '
                f'#{locked_item.parent_id} und hat noch nicht gemergte '
                f'Vorgänger. Bitte das Epic #{locked_item.parent_id} starten '
                f'– es orchestriert die Sub-Issues der Reihe nach – statt das '
                f'Sub-Issue einzeln einzureihen.'
            )

        # An explicit provider (the "Umsetzung durch …" button) wins and is
        # remembered on the item; otherwise the item's own choice applies.
        provider = _normalize_provider(provider or locked_item.implementation_provider)
        auth_mode = _resolve_run_auth(locked_item, provider)
        auth_user = resolve_credential_user(locked_item, actor=actor)
        # Raises when the mode cannot be served — before the item is moved.
        _check_credential(auth_user, provider, auth_mode)
        # Raises when the model has no known CLI translation — same reasoning.
        model = _resolve_run_model(locked_item, provider)

        changed = ensure_git_workflow_hint(locked_item)
        if locked_item.implementation_provider != provider:
            locked_item.implementation_provider = provider
            changed = True
        if changed:
            locked_item.save()

        ItemWorkflowGuard().transition(locked_item, ItemStatus.WORKING, actor=actor)

        job = ClaudeQueueJob.objects.create(
            item=locked_item,
            project=locked_item.project,
            status=ClaudeQueueJobStatus.QUEUED,
            provider=provider,
            model=model,
            auth_user=auth_user,
            requested_auth_mode=auth_mode,
            auth_mode=auth_mode,
            allow_api_key_fallback=allow_api_key_fallback and provider == AgentProvider.CLAUDE,
            parent_job=parent_job,
            epic_order=locked_item.epic_order if parent_job else 0,
        )

    who = auth_user.username if auth_user else 'host'
    ActivityService().log(
        verb='item.claude_enqueued',
        target=locked_item,
        actor=actor,
        summary=(
            f'Enqueued for {_provider_label(provider)} (job #{job.pk}, model={model}, '
            f'auth={auth_mode} via {who})'
        ),
    )
    return job, True


def enqueue_review_for_claude(
    item: Item, actor=None, *, allow_api_key_fallback: bool = False, provider=None,
) -> tuple[ClaudeQueueJob, bool]:
    """Enqueue a read-only ``review`` job for ``item`` (#1286).

    Only items in ``Integrated`` (a sub-issue, reviewed against its own
    sub-issue PR) or ``Testing`` (a single issue, or an epic reviewed as one
    unit against the epic PR to ``main``) qualify, and the item must have a
    linked PR. Unlike an implementation run this neither moves the item nor
    touches its description (no git-workflow hint), and the job stays outside
    the epic chain (``parent_job`` empty), so it never blocks or joins it.

    Raises :class:`ReviewNotAllowed` for the status/PR guards (before anything
    is created), and the credential/model errors of a normal enqueue.

    Returns ``(job, created)``; ``created`` is False when an active review job
    for the item already exists — that job is returned instead of a second one.
    """
    with transaction.atomic():
        locked_item = Item.objects.select_for_update().get(pk=item.pk)

        existing_job = ClaudeQueueJob.objects.filter(
            item=locked_item,
            kind=ClaudeQueueJobKind.REVIEW,
            status__in=[
                ClaudeQueueJobStatus.QUEUED,
                ClaudeQueueJobStatus.RUNNING,
                ClaudeQueueJobStatus.WAITING_LIMIT,
            ],
        ).order_by('-created_at').first()
        if existing_job is not None:
            return existing_job, False

        if locked_item.status not in REVIEWABLE_STATUSES:
            raise ReviewNotAllowed(
                f'Ein Review ist nur für Items im Status „Integrated“ oder '
                f'„Testing“ möglich. Item #{locked_item.id} hat den Status '
                f'„{locked_item.status}“.'
            )
        if not locked_item.external_mappings.filter(
            kind=ExternalIssueKind.PR,
        ).exists():
            raise ReviewNotAllowed(
                f'Für Item #{locked_item.id} ist kein PR verknüpft – ohne PR '
                f'gibt es nichts zu reviewen.'
            )

        # Explicit provider (button) > item.review_provider > "the other one
        # than the implementation" (see provider_rule).
        provider = _normalize_provider(
            provider or effective_review_provider(locked_item)
        )
        auth_mode = _resolve_run_auth(locked_item, provider)
        auth_user = resolve_credential_user(locked_item, actor=actor)
        _check_credential(auth_user, provider, auth_mode)
        model = _resolve_run_model(locked_item, provider)

        job = ClaudeQueueJob.objects.create(
            item=locked_item,
            project=locked_item.project,
            status=ClaudeQueueJobStatus.QUEUED,
            kind=ClaudeQueueJobKind.REVIEW,
            provider=provider,
            model=model,
            auth_user=auth_user,
            requested_auth_mode=auth_mode,
            auth_mode=auth_mode,
            allow_api_key_fallback=allow_api_key_fallback and provider == AgentProvider.CLAUDE,
        )

    who = auth_user.username if auth_user else 'host'
    ActivityService().log(
        verb='item.claude_review_enqueued',
        target=locked_item,
        actor=actor,
        summary=(
            f'Review enqueued for {_provider_label(provider)} (job #{job.pk}, model={model}, '
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
    # The chain runs on the provider chosen for the epic node.
    provider = _normalize_provider(epic_job.provider)
    auth_mode = _resolve_run_auth(sub_issue, provider)
    # The whole chain runs on the credential of whoever started the epic: they
    # pressed the button, so it is their quota. The worker builds the chain
    # without an interactive actor, and falling back to the sub-issue's
    # responsible/assignee would silently move the runs to somebody else's
    # account — or to none at all ("Not logged in").
    auth_user = resolve_credential_user(sub_issue, actor=actor or epic_job.auth_user)
    try:
        model = _resolve_run_model(sub_issue, provider)
    except InvalidClaudeModel:
        model = DEFAULT_OPENAI_MODEL if provider == AgentProvider.OPENAI else DEFAULT_CLAUDE_MODEL

    return ClaudeQueueJob.objects.create(
        item=sub_issue,
        project=sub_issue.project,
        status=ClaudeQueueJobStatus.BLOCKED,
        kind=ClaudeQueueJobKind.ISSUE,
        parent_job=epic_job,
        epic_order=sub_issue.epic_order,
        provider=provider,
        model=model,
        auth_user=auth_user,
        requested_auth_mode=auth_mode,
        auth_mode=auth_mode,
        allow_api_key_fallback=epic_job.allow_api_key_fallback and provider == AgentProvider.CLAUDE,
    )


def enqueue_epic_for_claude(
    item: Item, *, actor=None, allow_api_key_fallback: bool = False, provider=None,
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

        provider = _normalize_provider(provider or locked_item.implementation_provider)
        auth_mode = _resolve_run_auth(locked_item, provider)
        auth_user = resolve_credential_user(locked_item, actor=actor)
        # The node runs no CLI itself, but every sub-run below it will — so a
        # missing credential is worth rejecting at the button rather than one
        # layer in.
        _check_credential(auth_user, provider, auth_mode)

        if locked_item.implementation_provider != provider:
            locked_item.implementation_provider = provider
            locked_item.save()

        ItemWorkflowGuard().transition(locked_item, ItemStatus.WORKING, actor=actor)

        job = ClaudeQueueJob.objects.create(
            item=locked_item,
            project=locked_item.project,
            status=ClaudeQueueJobStatus.QUEUED,
            kind=ClaudeQueueJobKind.EPIC,
            provider=provider,
            model=_resolve_model_or_default(locked_item, provider),
            auth_user=auth_user,
            requested_auth_mode=auth_mode,
            auth_mode=auth_mode,
            allow_api_key_fallback=allow_api_key_fallback and provider == AgentProvider.CLAUDE,
        )

    ActivityService().log(
        verb='item.claude_epic_enqueued',
        target=locked_item,
        actor=actor,
        summary=f'Epic enqueued for {_provider_label(provider)} orchestration (job #{job.pk})',
    )
    return job, True


def _resolve_model_or_default(item, provider=AgentProvider.CLAUDE) -> str:
    """Model for an epic node: the item's, or the default if it is unusable.

    An epic node never invokes a model, so a stale slug on the epic item is no
    reason to refuse the chain — unlike on an issue run, where it is.
    """
    try:
        return _resolve_run_model(item, provider)
    except InvalidClaudeModel:
        return DEFAULT_OPENAI_MODEL if provider == AgentProvider.OPENAI else DEFAULT_CLAUDE_MODEL
