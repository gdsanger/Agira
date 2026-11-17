"""Human override of a review finding (#1291).

A person may close an item although its newest review reported ``deviations``
or ``unclear`` — with a mandatory reason. Neither Claude nor the worker ever
does this; the verdict on the job stays unchanged, the override is recorded in
separate fields and as an internal note on the item.

Idempotent: once the job carries ``review_overridden_at`` a repeated call
(double click) changes nothing and writes no second comment or activity.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from django.db import transaction
from django.utils import timezone

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobKind,
    ClaudeQueueJobStatus,
    ClaudeQueueReviewVerdict,
    CommentKind,
    CommentVisibility,
    ExternalIssueKind,
    Item,
    ItemComment,
    ItemStatus,
)
from core.services.activity import ActivityService
from core.services.claude_queue.review_apply import _pr_mapping, _repo_ref

logger = logging.getLogger(__name__)

MIN_REASON_LENGTH = 10
OVERRIDE_SUBJECT = 'Review-Befund überschrieben'
FOLLOWUP_SUBJECT = 'Durch Überschreiben des Review-Befunds erledigt'

OVERRIDABLE_VERDICTS = (
    ClaudeQueueReviewVerdict.DEVIATIONS,
    ClaudeQueueReviewVerdict.UNCLEAR,
)
# A follow-up in one of these states is being worked on and is never auto-closed.
_FOLLOWUP_IN_PROGRESS = (ItemStatus.WORKING, ItemStatus.INTEGRATED, ItemStatus.TESTING)

FOLLOWUP_NONE = 'none'
FOLLOWUP_CLOSABLE = 'closable'
FOLLOWUP_IN_PROGRESS = 'in_progress'
FOLLOWUP_CLOSED = 'closed'


class ReviewOverrideError(Exception):
    """User-fixable problem (bad reason, not allowed); message is shown verbatim."""


@dataclass
class ReviewOverrideResult:
    outcome: str  # 'overridden' | 'already_overridden'
    job: ClaudeQueueJob
    comment: Optional[ItemComment] = None
    followup_closed: bool = False


def latest_review_job(item) -> Optional[ClaudeQueueJob]:
    return (
        ClaudeQueueJob.objects.filter(
            item=item, kind=ClaudeQueueJobKind.REVIEW, status=ClaudeQueueJobStatus.DONE,
        ).select_related('review_followup_item').order_by('-id').first()
    )


def overridable_review_job(item) -> Optional[ClaudeQueueJob]:
    """The review job whose finding may be overridden, or None if not allowed."""
    if item.status == ItemStatus.CLOSED:
        return None
    job = latest_review_job(item)
    if job is None or job.review_verdict not in OVERRIDABLE_VERDICTS or job.review_overridden_at:
        return None
    return job


def followup_state(job) -> str:
    followup = job.review_followup_item
    if followup is None:
        return FOLLOWUP_NONE
    if followup.status == ItemStatus.CLOSED:
        return FOLLOWUP_CLOSED
    if (
        followup.status in _FOLLOWUP_IN_PROGRESS
        or followup.external_mappings.filter(kind=ExternalIssueKind.PR).exists()
    ):
        return FOLLOWUP_IN_PROGRESS
    return FOLLOWUP_CLOSABLE


def _user_name(user) -> str:
    return (getattr(user, 'name', '') or user.get_username()).strip()


def _build_comment(job, item, user, reason, when, followup, followup_closed) -> str:
    lines = [
        f'**Begründung:** {reason}', '',
        f'**Von:** {_user_name(user)}',
        f'**Zeitpunkt:** {timezone.localtime(when).strftime("%Y-%m-%d %H:%M")}',
        f'**Review-Job:** #{job.pk}',
        f'**Urteil des Reviews:** {job.review_verdict}',
    ]
    mapping = _pr_mapping(item)
    if mapping is not None:
        lines.append(f'**GitHub-PR:** [{_repo_ref(mapping)}]({mapping.html_url})')
    if followup is not None:
        suffix = ' (ebenfalls geschlossen)' if followup_closed else ''
        lines.append(f'**Folge-Issue:** #{followup.pk} – {followup.title}{suffix}')
    return '\n'.join(lines) + '\n'


def override_review(item, user, reason, close_followup: bool = True) -> ReviewOverrideResult:
    """Close ``item`` despite its review finding, documenting ``reason``."""
    from core.services.workflow import ItemWorkflowGuard

    reason = (reason or '').strip()
    if len(reason) < MIN_REASON_LENGTH:
        raise ReviewOverrideError(
            f'Bitte eine Begründung mit mindestens {MIN_REASON_LENGTH} Zeichen angeben.'
        )

    with transaction.atomic():
        # Lock the item row so concurrent submits serialise; the loser then
        # sees the recorded override and becomes a no-op.
        item = Item.objects.select_for_update().get(pk=item.pk)
        latest = latest_review_job(item)
        if latest is not None and latest.review_overridden_at:
            return ReviewOverrideResult(outcome='already_overridden', job=latest)
        job = overridable_review_job(item)
        if job is None:
            raise ReviewOverrideError(
                'Überschreiben nicht möglich: Das Item ist bereits geschlossen oder '
                'sein letztes Review hat weder „Abweichungen“ noch „Unklar“ ergeben.'
            )

        now = timezone.now()
        followup = job.review_followup_item
        followup_closed = (
            close_followup and followup is not None
            and followup_state(job) == FOLLOWUP_CLOSABLE
        )

        ItemWorkflowGuard().transition(item, ItemStatus.CLOSED, actor=user)
        comment = ItemComment.objects.create(
            item=item,
            author=user,
            visibility=CommentVisibility.INTERNAL,
            kind=CommentKind.NOTE,
            subject=OVERRIDE_SUBJECT,
            body=_build_comment(job, item, user, reason, now, followup, followup_closed),
        )
        job.review_overridden_by = user
        job.review_overridden_at = now
        job.review_override_reason = reason
        job.save(update_fields=[
            'review_overridden_by', 'review_overridden_at', 'review_override_reason',
        ])

        activity = ActivityService()
        activity.log(
            verb='claudequeuejob.review_overridden',
            target=item,
            actor=user,
            summary=(
                f'Review-Befund (Job #{job.pk}, {job.review_verdict}) überschrieben, '
                f'Item geschlossen: {reason}'
            ),
        )

        if followup_closed:
            ItemWorkflowGuard().transition(followup, ItemStatus.CLOSED, actor=user)
            ItemComment.objects.create(
                item=followup,
                author=user,
                visibility=CommentVisibility.INTERNAL,
                kind=CommentKind.NOTE,
                subject=FOLLOWUP_SUBJECT,
                body=(
                    f'**Begründung:** {reason}\n\n'
                    f'Review-Job #{job.pk} zu Item #{item.pk} wurde von '
                    f'{_user_name(user)} überschrieben.\n'
                ),
            )
            activity.log(
                verb='claudequeuejob.review_overridden',
                target=followup,
                actor=user,
                summary=f'Folge-Issue durch Überschreiben des Review-Befunds (Job #{job.pk}) geschlossen',
            )

    return ReviewOverrideResult(
        outcome='overridden', job=job, comment=comment, followup_closed=followup_closed,
    )
