"""Derived board state of a queue job (Kanban view of the Agent Queue).

A job's real state is spread over several fields: ``status``, ``kind``,
``completion_uncertain``/``completion_confirmed_at``, ``pr_number``/``pr_state``,
``review_verdict``/``review_report`` and ``review_followup_item``. The board
collapses them into ONE overarching state per job, so "what is running, what
failed, what still needs a merge, how did the reviews turn out" can be read at a
glance. Nothing is persisted: the state is recomputed on every access and so
cannot go stale or disagree with the fields it is derived from.

The "Done" in the review/merge columns is only a mnemonic; the columns do not
repeat it.
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobStatus,
    ClaudeQueueReviewVerdict,
    ItemStatus,
)

# Board state keys.
QUEUED = 'queued'
RUNNING = 'running'
FAILED = 'failed'
UNCERTAIN = 'uncertain'
MERGE_MISSING = 'merge_missing'
DONE = 'done'
REVIEW_DEVIATION = 'review_deviation'
REVIEW_DEVIATION_FOLLOWUP = 'review_deviation_followup'
REVIEW_PASS_HINTS = 'review_pass_hints'
REVIEW_PASS = 'review_pass'


@dataclass(frozen=True)
class BoardColumn:
    key: str
    label: str
    icon: str
    css: str  # bootstrap colour name, used for header accent
    hint: str
    capped: bool = False  # finished columns only show the newest N cards
    quiet: bool = False  # nothing to do for a human; hideable via the board switch


# Display order, one flat row of columns.
COLUMNS: Dict[str, BoardColumn] = {c.key: c for c in [
    BoardColumn(QUEUED, 'Queued', 'bi-hourglass-split', 'secondary',
                'Wartet auf den Worker (auch: geblockt in der Epic-Kette)'),
    BoardColumn(RUNNING, 'Running', 'bi-play-circle', 'primary',
                'Läuft, wartet auf Abo-Kontingent oder Epic wird orchestriert'),
    BoardColumn(FAILED, 'Failed', 'bi-exclamation-triangle', 'danger',
                'Fehlgeschlagen oder abgebrochen'),
    BoardColumn(UNCERTAIN, 'Unklar / ggf. unvollständig', 'bi-question-circle', 'warning',
                'Fertig, aber das Ergebnis sieht unvollständig aus bzw. das Review-Urteil ist unklar – Mensch muss prüfen'),
    BoardColumn(MERGE_MISSING, 'Merge fehlt', 'bi-git', 'info',
                'Umsetzung fertig, PR ist noch nicht gemergt'),
    BoardColumn(REVIEW_DEVIATION, 'Abweichung', 'bi-exclamation-diamond', 'warning',
                'Review fand Abweichungen, noch kein Folge-Issue'),
    BoardColumn(REVIEW_DEVIATION_FOLLOWUP, 'Abweichung + Folge-Issue', 'bi-link-45deg', 'warning',
                'Review fand Abweichungen, ein Folge-Issue wurde angelegt – bis dieses geschlossen ist'),
    BoardColumn(REVIEW_PASS_HINTS, 'Passed mit Hinweisen', 'bi-check-circle', 'success',
                'Review bestanden, mit nicht blockierenden Hinweisen', capped=True),
    BoardColumn(REVIEW_PASS, 'Passed', 'bi-patch-check', 'success',
                'Review ohne Befund bestanden', capped=True, quiet=True),
    BoardColumn(DONE, 'Erledigt', 'bi-check-lg', 'success',
                'Erledigt: Umsetzung gemergt (bzw. ohne PR) oder Review-Befund abgehakt (Folge-Issue geschlossen, Item geschlossen, überschrieben)', capped=True, quiet=True),
]}

_QUEUED_STATUSES = (ClaudeQueueJobStatus.QUEUED, ClaudeQueueJobStatus.BLOCKED)
_RUNNING_STATUSES = (
    ClaudeQueueJobStatus.RUNNING,
    ClaudeQueueJobStatus.ORCHESTRATING,
    ClaudeQueueJobStatus.WAITING_LIMIT,
)
_FAILED_STATUSES = (ClaudeQueueJobStatus.FAILED, ClaudeQueueJobStatus.CANCELLED)


def _finding_resolved(job) -> bool:
    if job.review_overridden_at:
        return True
    if job.item.status == ItemStatus.CLOSED:
        return True
    followup = job.review_followup_item
    return followup is not None and followup.status == ItemStatus.CLOSED


def derive_board_state(job: ClaudeQueueJob, hint_count=None) -> str:
    """Return the board state key of ``job``.

    ``hint_count`` may be passed when the caller already knows it, to avoid
    re-parsing the review report; otherwise it is read from the job.
    """
    status = job.status
    if status in _QUEUED_STATUSES:
        return QUEUED
    if status in _RUNNING_STATUSES:
        return RUNNING
    if status in _FAILED_STATUSES:
        return FAILED

    # status == DONE from here on.
    if job.is_review:
        verdict = job.review_verdict
        if verdict == ClaudeQueueReviewVerdict.PASS:
            n = job.review_hint_count if hint_count is None else hint_count
            return REVIEW_PASS_HINTS if n else REVIEW_PASS
        if verdict in (ClaudeQueueReviewVerdict.DEVIATIONS, ClaudeQueueReviewVerdict.UNCLEAR):
            # A finding that has been dealt with leaves the attention columns:
            # overridden by a human, the item closed anyway, or the follow-up
            # issue (which carries its own review) closed.
            if _finding_resolved(job):
                return DONE
            if verdict == ClaudeQueueReviewVerdict.UNCLEAR:
                return UNCERTAIN
            return REVIEW_DEVIATION_FOLLOWUP if job.review_followup_item_id else REVIEW_DEVIATION
        # A review that finished without any verdict.
        return UNCERTAIN

    if job.completion_uncertain and not job.is_completion_confirmed:
        return UNCERTAIN
    if job.pr_number and job.pr_state != 'merged':
        return MERGE_MISSING
    return DONE


@dataclass
class Board:
    columns: List[BoardColumn]
    cards: Dict[str, list]
    hidden: Dict[str, int]

    @property
    def lanes(self):
        return [
            {'column': c, 'jobs': self.cards[c.key], 'hidden': self.hidden[c.key]}
            for c in self.columns
        ]


def build_board(jobs: Iterable[ClaudeQueueJob], cap: int = 15) -> Board:
    """Sort ``jobs`` (newest first) into columns; capped columns keep ``cap`` cards."""
    cards = {key: [] for key in COLUMNS}
    hidden = {key: 0 for key in COLUMNS}
    for job in jobs:
        key = derive_board_state(job)
        job.board_state = key
        if COLUMNS[key].capped and len(cards[key]) >= cap:
            hidden[key] += 1
            continue
        cards[key].append(job)
    return Board(columns=list(COLUMNS.values()), cards=cards, hidden=hidden)
