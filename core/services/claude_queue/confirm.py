"""Manual confirmation of a "Ggf. unvollständig" run (``completion_uncertain``).

A flagged run halts its epic chain (see ``orchestration.sub_job_state``). When
a human has checked the result and found it complete, this is the way to tell
the queue — without repeating the paid run and without touching the PR or
branch: nothing is merged or changed on GitHub here.
"""
import logging

from django.db import transaction
from django.utils import timezone

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobStatus,
    CommentKind,
    CommentVisibility,
    ItemComment,
)
from core.services.activity import ActivityService

logger = logging.getLogger(__name__)

MIN_REASON_LENGTH = 10


class ConfirmCompleteError(ValueError):
    """The run cannot be confirmed (wrong state or missing justification)."""


def confirm_complete(job, user, reason) -> bool:
    """Confirm the flagged ``job`` as complete; return False if already done.

    Idempotent: the row is locked and re-checked, so a double click confirms
    once and writes one comment and one activity. The original
    ``completion_uncertain_reason`` is kept.
    """
    reason = (reason or '').strip()
    if len(reason) < MIN_REASON_LENGTH:
        raise ConfirmCompleteError(
            f'Begründung erforderlich (mindestens {MIN_REASON_LENGTH} Zeichen).'
        )

    with transaction.atomic():
        locked = ClaudeQueueJob.objects.select_for_update().select_related(
            'item'
        ).get(pk=job.pk)
        if locked.is_epic_node or locked.status != ClaudeQueueJobStatus.DONE:
            raise ConfirmCompleteError(
                f'Job #{locked.pk} kann nicht als vollständig bestätigt werden.'
            )
        if not locked.completion_uncertain:
            job.refresh_from_db()
            return False

        locked.completion_uncertain = False
        locked.completion_confirmed_reason = reason
        locked.completion_confirmed_by = user if getattr(user, 'pk', None) else None
        locked.completion_confirmed_at = timezone.now()
        locked.save(update_fields=[
            'completion_uncertain', 'completion_confirmed_reason',
            'completion_confirmed_by', 'completion_confirmed_at',
        ])

        item = locked.item
        original = locked.completion_uncertain_reason.strip() or '–'
        ActivityService().log(
            verb='claudequeuejob.completion_confirmed',
            target=item,
            actor=user if getattr(user, 'pk', None) else None,
            summary=f'Claude queue job #{locked.pk} manuell als vollständig bestätigt: {reason}',
        )
        pr = (
            f'[PR #{locked.pr_number}]({locked.pr_url})' if locked.pr_url
            else (f'PR #{locked.pr_number}' if locked.pr_number else 'kein PR')
        )
        ItemComment.objects.create(
            item=item,
            author=user if getattr(user, 'pk', None) else None,
            visibility=CommentVisibility.INTERNAL,
            kind=CommentKind.NOTE,
            subject='Claude-Queue: Lauf manuell als vollständig bestätigt',
            body=(
                f'Job #{locked.pk} („Ggf. unvollständig“) wurde manuell als '
                f'vollständig bestätigt.\n\n'
                f'**Begründung:** {reason}\n\n'
                f'**Ursprünglicher Hinweis:** {original}\n\n'
                f'**PR:** {pr}'
            ),
        )

    job.refresh_from_db()

    # The poll would pick the change up anyway; this just makes it immediate.
    from core.services.claude_queue.orchestration import advance_epic_for_item
    try:
        advance_epic_for_item(job.item, actor=user if getattr(user, 'pk', None) else None)
    except Exception:  # noqa: BLE001 — confirmation stands, the poll retries
        logger.exception('Advancing epic after confirming job #%s failed', job.pk)
    return True
