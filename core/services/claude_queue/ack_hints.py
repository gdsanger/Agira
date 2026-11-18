"""Tick off the hints of a passed review ("Hinweise gelesen").

A review that passed with non-blocking hints (``minor`` findings) stays in the
board's "Passed mit Hinweisen" column so the hints are not overlooked. Once a
human has read them this marks the review as dealt with and moves it to
"Erledigt". Nothing else changes: the verdict, the item status and GitHub are
untouched, and no justification is asked for.

Idempotent: a double click records the acknowledgement once.
"""
from django.db import transaction
from django.utils import timezone

from core.models import ClaudeQueueJob
from core.services.activity import ActivityService


class AcknowledgeHintsError(ValueError):
    """The review has no open hints to acknowledge."""


def acknowledge_hints(job, user) -> bool:
    """Mark the hints of ``job`` as read; return False if already done."""
    actor = user if getattr(user, 'pk', None) else None
    with transaction.atomic():
        locked = ClaudeQueueJob.objects.select_for_update().select_related('item').get(pk=job.pk)
        if locked.review_hints_acknowledged_at:
            return False
        if not locked.can_acknowledge_hints:
            raise AcknowledgeHintsError(
                f'Job #{locked.pk} hat keine offenen Review-Hinweise.'
            )
        locked.review_hints_acknowledged_at = timezone.now()
        locked.review_hints_acknowledged_by = actor
        locked.save(update_fields=[
            'review_hints_acknowledged_at', 'review_hints_acknowledged_by',
        ])
        ActivityService().log(
            verb='claudequeuejob.review_hints_acknowledged',
            target=locked.item,
            actor=actor,
            summary=f'Review-Hinweise (Job #{locked.pk}) als gelesen markiert',
        )
    job.refresh_from_db()
    return True
