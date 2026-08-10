"""Epic orchestration through the Claude queue itself (#1079).

#1076 defines the *branch* model of an epic — sub-issues as layers of one
vertical slice, squash-merged into a long-lived epic branch, one manual draft
PR to ``main`` at the end. This module is the thing that actually drives that
chain forward, and the decision it embodies is *where* the orchestration
lives: in the queue.

Not a long-running orchestrator job, because one would have to sit in
``running`` while waiting for the runs it orchestrates — and the worker allows
exactly one running job per repo, so the orchestrator would be waiting for
something it is itself blocking. Not GitHub webhooks either, because the queue
already knows what a webhook would have to reconstruct: whether a run finished
cleanly (``done``), broke (``failed``), or came back looking suspicious
(``completion_uncertain`` — "Ggf. unvollständig"). A merge webhook confirms
that a merge really happened; it does not decide anything.

The shape is deliberately flat. An **epic node** (``kind=epic``) implements
nothing. It carries the epic branch, holds the chain, and advances it. Below it
hang the **sub-entries**, one per Agira sub-issue, in ``epic_order``. The
worker's contract — one item per run — is untouched; the hierarchy is
structure *around* single runs, not a new kind of run.

**Advancement happens only on unambiguous success**: ``done``, not flagged
uncertain, and the sub-issue's PR actually merged. Everything else halts the
chain. That includes the soft case, and that is the point — a chain that
advances over a half-finished layer puts the next layer on a foundation that
may be a mock, which is exactly the failure #1076 exists to prevent. The
uncertainty heuristic does not have to be right, only conservative: in doubt it
stops, and a human looks. What used to be noise in the queue ("Ggf.
unvollständig") becomes the brake.

There is no automatic retry past an unclear state. The developer inspects the
sub-run and re-triggers it; a re-triggered run re-attaches to the same chain
(see :func:`active_epic_job_for`), and once it succeeds unambiguously the chain
continues on its own.
"""

import logging
from dataclasses import dataclass

from django.db import transaction

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobKind,
    ClaudeQueueJobStatus,
    ItemStatus,
)
from core.services.claude_queue.epic import (
    ensure_epic_pr,
    is_merged,
    ordered_sub_issues,
)

logger = logging.getLogger(__name__)

# --- Per-sub-entry chain states ---------------------------------------- #
# What one sub-entry means *for the chain*, which is not the same question as
# its job status: ``done`` alone is not success here (the merge may still be
# pending), and ``done`` with an uncertainty flag is a stop, not a pass.
SUB_SUCCESS = 'success'          # done, not flagged, PR merged → advance
SUB_PENDING = 'pending'          # queued/running/parked → nothing to decide yet
SUB_BLOCKED = 'blocked'          # not released yet → the next one to release
SUB_WAITING_MERGE = 'waiting_merge'  # done and clean, but the PR has not landed
SUB_HALTED = 'halted'            # failed/cancelled/uncertain → chain stops here

# Chain-level outcomes of one advancement attempt, returned for logging/tests.
ADVANCE_RELEASED = 'released'
ADVANCE_WAITING = 'waiting'
ADVANCE_HALTED = 'halted'
ADVANCE_FINISHED = 'finished'
ADVANCE_INACTIVE = 'inactive'

_PENDING_STATUSES = frozenset({
    ClaudeQueueJobStatus.QUEUED,
    ClaudeQueueJobStatus.RUNNING,
    ClaudeQueueJobStatus.WAITING_LIMIT,
})


# ---------------------------------------------------------------------- #
# Reading the chain
# ---------------------------------------------------------------------- #
def sub_jobs_in_order(epic_job) -> list:
    """The chain below ``epic_job``: the *current* entry per sub-issue, in order.

    A sub-issue can have more than one entry — a halted run that the developer
    re-triggered leaves the old one behind as history. Only the newest entry
    per item speaks for that layer; the older ones are superseded and must not
    keep the chain halted after a successful retry.
    """
    current_by_item = {}
    entries = epic_job.sub_jobs.select_related('item').order_by('created_at', 'id')
    for entry in entries:
        current_by_item[entry.item_id] = entry
    return sorted(
        current_by_item.values(), key=lambda j: (j.epic_order, j.item_id)
    )


def sub_job_state(job) -> str:
    """Classify one sub-entry for the chain — see the ``SUB_*`` constants.

    ``done`` splits three ways on purpose. Flagged uncertain is a halt: the
    heuristic saw the run talk about waiting, backgrounding or asking a
    question, and a chain must not build on that. Clean but unmerged is not a
    halt — the sub PR squash-auto-merges once CI agrees, so this is the normal
    gap of a few minutes between "Claude finished" and "the layer landed".
    """
    if job.status == ClaudeQueueJobStatus.BLOCKED:
        return SUB_BLOCKED
    if job.status in _PENDING_STATUSES:
        return SUB_PENDING
    if job.status == ClaudeQueueJobStatus.DONE:
        if job.completion_uncertain:
            return SUB_HALTED
        return SUB_SUCCESS if is_merged(job.item) else SUB_WAITING_MERGE
    # failed / cancelled
    return SUB_HALTED


def halt_reason(job) -> str:
    """Short, user-facing reason a sub-entry stopped its chain."""
    if job.status == ClaudeQueueJobStatus.FAILED:
        return job.error_text.strip() or 'Sub-Run fehlgeschlagen'
    if job.status == ClaudeQueueJobStatus.CANCELLED:
        return 'Sub-Run abgebrochen'
    if job.completion_uncertain:
        return (
            job.completion_uncertain_reason.strip()
            or 'Ergebnis des Sub-Runs unklar („Ggf. unvollständig“)'
        )
    return 'Sub-Run nicht eindeutig erfolgreich'


@dataclass(frozen=True)
class EpicChainState:
    """Derived, display-ready state of an epic node's chain."""

    total: int
    done: int
    current: object          # the sub-entry the chain currently sits on, or None
    current_state: str       # one of the SUB_* constants, '' when there is none
    reason: str              # why it halted, empty otherwise
    finished: bool           # every sub-entry landed

    @property
    def is_halted(self) -> bool:
        return self.current_state == SUB_HALTED

    @property
    def position(self) -> str:
        """Position of the sub-entry the chain sits on, e.g. ``2/3``."""
        return f'{self.done + 1}/{self.total}' if self.current is not None else ''

    @property
    def label(self) -> str:
        """One line for the queue view: what this epic is doing right now."""
        if self.total == 0:
            return 'Keine Sub-Einträge'
        if self.finished:
            return f'Alle {self.total} Sub-Issues gemergt – Epic-PR offen'
        item_id = self.current.item_id
        if self.is_halted:
            return f'Pausiert bei Sub-Issue #{item_id} ({self.position})'
        if self.current_state == SUB_WAITING_MERGE:
            return f'Wartet auf Merge von Sub-Issue #{item_id} ({self.position})'
        if self.current_state == SUB_BLOCKED:
            return f'Nächstes Sub-Issue #{item_id} ({self.position}) wartet auf Freigabe'
        return f'Sub-Issue #{item_id} läuft ({self.position})'


def chain_state(epic_job) -> EpicChainState:
    """Summarise ``epic_job``'s chain: how far it got and what it sits on."""
    entries = sub_jobs_in_order(epic_job)
    done = 0
    for entry in entries:
        state = sub_job_state(entry)
        if state == SUB_SUCCESS:
            done += 1
            continue
        return EpicChainState(
            total=len(entries),
            done=done,
            current=entry,
            current_state=state,
            reason=halt_reason(entry) if state == SUB_HALTED else '',
            finished=False,
        )
    return EpicChainState(
        total=len(entries),
        done=done,
        current=None,
        current_state='',
        reason='',
        finished=bool(entries),
    )


def active_epic_job_for(item):
    """The epic node currently orchestrating ``item``'s parent, or None.

    This is what lets a manual re-trigger of a halted sub-issue rejoin its
    chain instead of becoming an orphan run next to it.
    """
    if item.parent_id is None:
        return None
    return (
        ClaudeQueueJob.objects
        .filter(
            item_id=item.parent_id,
            kind=ClaudeQueueJobKind.EPIC,
            status=ClaudeQueueJobStatus.ORCHESTRATING,
        )
        .order_by('-created_at')
        .first()
    )


# ---------------------------------------------------------------------- #
# Driving the chain
# ---------------------------------------------------------------------- #
def build_epic_chain(epic_job, *, actor=None) -> list:
    """Create the blocked sub-entries of ``epic_job`` from the Agira sub-issues.

    Derived from the sub-issues rather than filled in by hand: the parent
    relation and ``epic_order`` are already the plan, and a second, manually
    maintained list could only ever disagree with it.

    Every entry starts ``blocked`` — the whole chain is visible in the queue
    from the start, in order, plainly not about to run. The sub-issue's item is
    deliberately *not* moved to Working here: a layer that may only start in
    two days should not claim to be in progress today.

    Idempotent: sub-issues that already have an entry on this node are left
    alone, so re-running the start step cannot duplicate the chain.
    """
    from core.services.claude_queue.enqueue import create_sub_issue_job

    existing_item_ids = set(
        epic_job.sub_jobs.values_list('item_id', flat=True)
    )
    created = []
    for sub_issue in ordered_sub_issues(epic_job.item):
        if sub_issue.id in existing_item_ids:
            continue
        created.append(create_sub_issue_job(sub_issue, epic_job, actor=actor))
    return created


def start_epic(epic_job, *, actor=None) -> str:
    """Run the epic node's start step: build the chain and release the first sub.

    Called by the worker once it has materialised the epic branch. The node
    itself implements nothing, so this is all it does before stepping back into
    :data:`~core.models.ClaudeQueueJobStatus.ORCHESTRATING` — it must not stay
    ``running``, or it would hold the repo lane its own sub-runs need.
    """
    with transaction.atomic():
        build_epic_chain(epic_job, actor=actor)
        epic_job.transition_to(ClaudeQueueJobStatus.ORCHESTRATING, actor=actor)
    return advance_epic(epic_job, actor=actor)


def release_sub_job(job, *, actor=None):
    """Hand a blocked sub-entry to the worker: queue it and move its item.

    The git-workflow hint and the Working transition happen *here* rather than
    when the chain was built, so both describe something that is true now.

    A sub-issue closed since the chain was planned stops the chain instead of
    being worked anyway — somebody decided that layer is not wanted, and
    guessing whether the epic still makes sense without it is not this
    function's call.
    """
    from core.services.claude_queue.hint import ensure_git_workflow_hint
    from core.services.workflow.item_workflow_guard import ItemWorkflowGuard

    item = job.item
    if item.status == ItemStatus.CLOSED:
        raise ValueError(
            f'Sub-Issue #{item.id} ist geschlossen und kann nicht freigegeben '
            f'werden. Kette angehalten.'
        )

    with transaction.atomic():
        if ensure_git_workflow_hint(item):
            item.save()
        ItemWorkflowGuard().transition(item, ItemStatus.WORKING, actor=actor)
        job.transition_to(ClaudeQueueJobStatus.QUEUED, actor=actor)
    return job


def advance_epic(epic_job, *, actor=None) -> str:
    """Move ``epic_job``'s chain one step, if and only if it may move.

    The single place the advancement rule is applied: release the next
    sub-entry when everything before it is unambiguously successful, open the
    final draft PR when nothing is left, and otherwise do nothing at all.
    Idempotent and safe to call from anywhere — the worker's poll, the merge
    webhook — because it re-derives the decision from the chain every time
    instead of reacting to an event.
    """
    if epic_job.status != ClaudeQueueJobStatus.ORCHESTRATING:
        return ADVANCE_INACTIVE

    # Re-derive the chain first, so a layer slipped into the epic mid-run
    # (the reason ``epic_order`` is meant to be gapped 10/20/30) joins it
    # instead of being silently left out of the epic it was added to.
    build_epic_chain(epic_job, actor=actor)

    state = chain_state(epic_job)
    if state.finished:
        return _finish_epic(epic_job, actor=actor)
    if state.current is None:
        # An epic node whose item has no sub-issues at all: nothing to
        # orchestrate, and no epic PR worth opening on an empty branch.
        _fail_epic(epic_job, 'Epic hat keine Sub-Issues.', actor=actor)
        return ADVANCE_HALTED

    if state.current_state == SUB_BLOCKED:
        try:
            release_sub_job(state.current, actor=actor)
        except Exception as exc:  # noqa: BLE001 — a bad item must not kill the chain
            # Keep the node orchestrating: the chain is stuck, not broken, and
            # the next sweep retries once the item is fixed.
            logger.warning(
                'Could not release sub-entry #%s of epic node #%s: %s',
                state.current.pk, epic_job.pk, exc,
            )
            _record_epic_error(epic_job, f'Sub-Eintrag #{state.current.pk}: {exc}')
            return ADVANCE_HALTED
        _record_epic_error(epic_job, '')
        return ADVANCE_RELEASED

    if state.current_state == SUB_HALTED:
        return ADVANCE_HALTED
    return ADVANCE_WAITING


def advance_all_epics(*, actor=None) -> int:
    """Advance every orchestrating epic node. The queue's heartbeat.

    Called from the worker's poll loop, which makes the queue — not a webhook —
    the thing that drives a chain: a merge that no webhook ever reported still
    moves the chain on the next poll.
    """
    moved = 0
    nodes = ClaudeQueueJob.objects.filter(
        kind=ClaudeQueueJobKind.EPIC,
        status=ClaudeQueueJobStatus.ORCHESTRATING,
    ).select_related('item')
    for node in nodes:
        try:
            if advance_epic(node, actor=actor) in (ADVANCE_RELEASED, ADVANCE_FINISHED):
                moved += 1
        except Exception:  # noqa: BLE001 — one broken epic must not stop the rest
            logger.exception('Advancing epic node #%s failed', node.pk)
    return moved


def advance_epic_for_item(item, *, actor=None) -> str:
    """Advance the chain ``item`` belongs to. The merge webhook's entry point.

    Secondary by design: it only makes the chain react within seconds of a
    merge instead of within one poll interval. The decision itself is the same
    :func:`advance_epic` either way.
    """
    epic_job = active_epic_job_for(item)
    if epic_job is None:
        return ADVANCE_INACTIVE
    return advance_epic(epic_job, actor=actor)


def _finish_epic(epic_job, *, actor=None) -> str:
    """Closing step: open the epic → ``main`` draft PR, then finish the node.

    Done by the node itself rather than by a dedicated "epic wrap-up" sub-run:
    there is no code to write here, and a Claude run whose only job is to call
    ``gh pr create`` would cost a model invocation to do something the
    orchestration already has everything for.

    Draft, never auto-merged — the assembled slice is the one thing a human
    reviews. If GitHub cannot be reached the node stays orchestrating so the
    next sweep retries; reporting the epic finished without its PR would be
    the one lie the developer has no way to notice.
    """
    mapping = ensure_epic_pr(epic_job.item, actor=actor)
    if mapping is None:
        _record_epic_error(
            epic_job, 'Epic-PR konnte nicht angelegt werden – wird erneut versucht.'
        )
        return ADVANCE_WAITING

    epic_job.pr_number = mapping.number
    epic_job.pr_url = mapping.html_url or ''
    epic_job.pr_state = mapping.state or 'open'
    epic_job.error_text = ''
    epic_job.progress_text = f'Epic-PR #{mapping.number} als Draft angelegt'
    epic_job.save(update_fields=[
        'pr_number', 'pr_url', 'pr_state', 'error_text', 'progress_text',
    ])
    epic_job.transition_to(ClaudeQueueJobStatus.DONE, actor=actor)
    return ADVANCE_FINISHED


def _fail_epic(epic_job, message, *, actor=None):
    epic_job.error_text = message
    epic_job.save(update_fields=['error_text'])
    epic_job.transition_to(ClaudeQueueJobStatus.FAILED, actor=actor)


def _record_epic_error(epic_job, message):
    """Persist (or clear) the node's error line without changing its status."""
    if epic_job.error_text == message:
        return
    epic_job.error_text = message
    epic_job.save(update_fields=['error_text'])
