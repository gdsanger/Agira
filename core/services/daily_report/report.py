"""
Data side of the daily status report (#daily_status_report).

Everything here works on a *report date* ``d``. The report window is
"previous day 07:30 to ``d`` 07:30" in the report time zone (Europe/Berlin),
computed from wall-clock times so that the window is 23 h / 25 h long on the
days daylight saving time starts / ends.

Sources for a past status distribution, in order of preference:

1. ``ItemStatusSnapshot`` rows written by an earlier report run,
2. the live item table, when ``d`` is today,
3. a reconstruction from ``ItemStatusChange`` (walking back every change
   after the cut-off), which is only valid once the history is complete,
   i.e. for cut-offs after the first non-backfilled status change.

Anything older is a gap and is rendered as such.
"""

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from datetime import timezone as dt_timezone
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Min
from django.urls import reverse
from django.utils import timezone

from core.models import Item, ItemStatus, ItemStatusChange, ItemStatusSnapshot, User

OPEN_STATUSES = [
    ItemStatus.INBOX,
    ItemStatus.BACKLOG,
    ItemStatus.WORKING,
    ItemStatus.TESTING,
    ItemStatus.REVIEW,
    ItemStatus.READY_FOR_RELEASE,
]
# Statuses that count as "in active work" for the responsible section.
ACTIVE_STATUSES = [ItemStatus.WORKING, ItemStatus.TESTING, ItemStatus.REVIEW]

STATUS_LABELS = {
    ItemStatus.INBOX: 'Inbox',
    ItemStatus.BACKLOG: 'Backlog',
    ItemStatus.WORKING: 'Working',
    ItemStatus.TESTING: 'Testing',
    ItemStatus.REVIEW: 'Review',
    ItemStatus.READY_FOR_RELEASE: 'Ready for Release',
    ItemStatus.CLOSED: 'Closed',
}

TREND_DAYS = 7

NO_REQUESTER = 'ohne Requester'
NO_RESPONSIBLE = 'ohne Responsible'

# Where a status distribution came from.
SOURCE_SNAPSHOT = 'snapshot'
SOURCE_LIVE = 'live'
SOURCE_HISTORY = 'history'


def report_timezone() -> ZoneInfo:
    return ZoneInfo(getattr(settings, 'DAILY_REPORT_TIMEZONE', 'Europe/Berlin'))


def cutoff_time() -> time:
    hours, minutes = getattr(settings, 'DAILY_REPORT_CUTOFF', '07:30').split(':')
    return time(int(hours), int(minutes))


def cutoff(day: date) -> datetime:
    """Report cut-off (07:30 local) on ``day``, as an aware UTC datetime.

    Converted to UTC on purpose: Python compares and subtracts datetimes that
    share a tzinfo by wall-clock time, which would hide the 23 h / 25 h DST days.
    """
    local = datetime.combine(day, cutoff_time(), tzinfo=report_timezone())
    return local.astimezone(dt_timezone.utc)


def report_window(day: date):
    """``(start, end)`` of the report window ending at ``day``'s cut-off."""
    return cutoff(day - timedelta(days=1)), cutoff(day)


def local_today(now: Optional[datetime] = None) -> date:
    return (now or timezone.now()).astimezone(report_timezone()).date()


def history_start() -> Optional[datetime]:
    """First moment from which the status history is complete.

    Rows backfilled from the Activity log do not count: that log never saw
    every transition. ``None`` while no change has been recorded yet.
    """
    return ItemStatusChange.objects.filter(backfilled=False).aggregate(t=Min('changed_at'))['t']


def user_display_name(user: Optional[User]) -> str:
    if user is None:
        return ''
    return user.name or user.username or user.email


def item_url(item_id: int) -> str:
    return f"{settings.APP_BASE_URL.rstrip('/')}{reverse('item-detail', args=[item_id])}"


# ---------------------------------------------------------------------------
# Item states
# ---------------------------------------------------------------------------

def _open_states_live() -> List[dict]:
    return list(
        Item.objects.exclude(status=ItemStatus.CLOSED)
        .values('id', 'status', 'project_id', 'project__name', 'requester_id', 'responsible_id')
    )


def _open_states_at(moment: datetime) -> List[dict]:
    """Open items with their status at ``moment``, reconstructed from history.

    Only correct when every change after ``moment`` is recorded, i.e. for
    ``moment >= history_start()``. Project/requester/responsible are today's
    values — they are not historised.
    """
    first_change_after = {}
    later_changes = (
        ItemStatusChange.objects.filter(changed_at__gt=moment, backfilled=False)
        .order_by('changed_at', 'id')
        .values_list('item_id', 'from_status')
    )
    for item_id, from_status in later_changes:
        first_change_after.setdefault(item_id, from_status)

    states = []
    items = Item.objects.filter(created_at__lte=moment).values(
        'id', 'status', 'project_id', 'project__name', 'requester_id', 'responsible_id',
    )
    for row in items:
        status = first_change_after.get(row['id'], row['status'])
        if status and status != ItemStatus.CLOSED:
            states.append({**row, 'status': status})
    return states


@dataclass
class DayState:
    counts: Dict[str, int]
    source: str
    per_project: Optional[Dict[str, Dict[str, int]]] = None

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def _counts(states: List[dict]) -> Dict[str, int]:
    counter = Counter(row['status'] for row in states)
    return {status: counter.get(status, 0) for status in OPEN_STATUSES}


def _per_project(states: List[dict]) -> Dict[str, Dict[str, int]]:
    grouped = defaultdict(Counter)
    for row in states:
        grouped[row['project__name']][row['status']] += 1
    return {
        name: {status: counter.get(status, 0) for status in OPEN_STATUSES}
        for name, counter in grouped.items()
    }


def _snapshot_state(day: date) -> Optional[DayState]:
    snapshot_rows = list(
        ItemStatusSnapshot.objects.filter(date=day).values('project__name', 'status', 'count')
    )
    if not snapshot_rows:
        return None
    counts = {status: 0 for status in OPEN_STATUSES}
    per_project = defaultdict(lambda: {status: 0 for status in OPEN_STATUSES})
    for row in snapshot_rows:
        if row['status'] in counts:
            counts[row['status']] += row['count']
            per_project[row['project__name']][row['status']] += row['count']
    return DayState(counts=counts, source=SOURCE_SNAPSHOT, per_project=dict(per_project))


def day_state(day: date, today: date, tracking_start: Optional[datetime]) -> Optional[DayState]:
    """Open-item distribution at ``day``'s cut-off, or ``None`` for a gap."""
    snapshot = _snapshot_state(day)
    if snapshot is not None:
        return snapshot
    if day == today:
        states = _open_states_live()
        return DayState(counts=_counts(states), source=SOURCE_LIVE, per_project=_per_project(states))
    if tracking_start is not None and cutoff(day) >= tracking_start:
        states = _open_states_at(cutoff(day))
        return DayState(counts=_counts(states), source=SOURCE_HISTORY, per_project=_per_project(states))
    return None


@transaction.atomic
def write_snapshot(day: date) -> bool:
    """Persist today's open-item distribution for ``day``.

    The first run of a day wins: a manual re-run later that day must not
    overwrite the cut-off state the trend is built from. Returns whether a
    snapshot was written.
    """
    if ItemStatusSnapshot.objects.filter(date=day).exists():
        return False
    counter = Counter((row['project_id'], row['status']) for row in _open_states_live())
    ItemStatusSnapshot.objects.bulk_create([
        ItemStatusSnapshot(date=day, project_id=project_id, status=status, count=count)
        for (project_id, status), count in counter.items()
    ])
    return True


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

@dataclass
class ItemLine:
    id: int
    title: str
    project: str
    person: str
    url: str


@dataclass
class PersonCount:
    name: str
    total: int
    per_status: Dict[str, int] = field(default_factory=dict)
    is_placeholder: bool = False


@dataclass
class TrendDay:
    date: date
    new: int
    closed: int
    closed_complete: bool
    state: Optional[DayState]


@dataclass
class DailyReport:
    report_date: date
    window_start: datetime
    window_end: datetime
    generated_at: datetime
    new_items: List[ItemLine]
    closed_items: List[ItemLine]
    closed_complete: bool
    state: DayState
    state_hint: str
    requesters: List[PersonCount]
    responsibles: List[PersonCount]
    trend: List[TrendDay]
    trend_has_gaps: bool
    history_start: Optional[datetime]

    @property
    def subject(self) -> str:
        return f"Agira Tagesreport – {self.report_date.strftime('%d.%m.%Y')}"

    @property
    def projects(self) -> List[tuple]:
        """``(project, counts, total)`` for projects with open items, by size."""
        rows = [
            (name, counts, sum(counts.values()))
            for name, counts in (self.state.per_project or {}).items()
            if sum(counts.values())
        ]
        return sorted(rows, key=lambda r: (-r[2], r[0].lower()))


def _closed_changes(start: datetime, end: datetime):
    """Distinct item ids that switched to Closed within ``[start, end)``."""
    return (
        ItemStatusChange.objects.filter(
            to_status=ItemStatus.CLOSED, changed_at__gte=start, changed_at__lt=end,
        )
        .values_list('item_id', flat=True)
        .distinct()
    )


def _users_by_id(ids) -> Dict[int, User]:
    return {user.id: user for user in User.objects.filter(id__in={i for i in ids if i})}


def _person_counts(states, key: str, statuses, placeholder: str, users) -> List[PersonCount]:
    grouped = defaultdict(Counter)
    for row in states:
        if row['status'] in statuses:
            grouped[row[key]][row['status']] += 1
    result = []
    for user_id, counter in grouped.items():
        name = user_display_name(users.get(user_id)) if user_id else placeholder
        result.append(PersonCount(
            name=name or placeholder,
            total=sum(counter.values()),
            per_status={status: counter.get(status, 0) for status in statuses},
            is_placeholder=not user_id,
        ))
    # People by workload; the placeholder row always last so it stands out.
    return sorted(result, key=lambda p: (p.is_placeholder, -p.total, p.name.lower()))


def build_report(report_date: date, now: Optional[datetime] = None) -> DailyReport:
    now = now or timezone.now()
    today = local_today(now)
    tracking_start = history_start()
    window_start, window_end = report_window(report_date)

    # 1. New items
    new_qs = (
        Item.objects.filter(created_at__gte=window_start, created_at__lt=window_end)
        .select_related('project', 'requester')
        .order_by('id')
    )
    new_items = [
        ItemLine(i.id, i.title, i.project.name, user_display_name(i.requester), item_url(i.id))
        for i in new_qs
    ]

    # 3. Closed items — from the recorded transition, not updated_at
    closed_qs = (
        Item.objects.filter(id__in=_closed_changes(window_start, window_end))
        .select_related('project', 'responsible')
        .order_by('id')
    )
    closed_items = [
        ItemLine(i.id, i.title, i.project.name, user_display_name(i.responsible), item_url(i.id))
        for i in closed_qs
    ]
    closed_complete = tracking_start is not None and window_start >= tracking_start

    # 2./4./5. State at the cut-off
    if report_date == today:
        states = _open_states_live()
        state_source = SOURCE_LIVE
        state_hint = ''
    elif tracking_start is not None and window_end >= tracking_start:
        states = _open_states_at(window_end)
        state_source = SOURCE_HISTORY
        state_hint = (
            'Status rekonstruiert aus der Statushistorie; Projekt, Requester und '
            'Responsible entsprechen dem heutigen Stand.'
        )
    else:
        states = _open_states_live()
        state_source = SOURCE_LIVE
        state_hint = (
            'Die Statushistorie reicht nicht bis zu diesem Stichtag zurück – '
            'Abschnitte 2, 4 und 5 zeigen den aktuellen Stand.'
        )
    # For a past date the distribution prefers the stored snapshot: it reflects
    # the projects as they were at the cut-off, not after later moves. Today
    # stays live so sections 2, 4 and 5 agree on a later manual run.
    snapshot = None if report_date == today else _snapshot_state(report_date)
    state = snapshot or DayState(
        counts=_counts(states),
        source=state_source,
        per_project=_per_project(states),
    )

    users = _users_by_id(
        [row['requester_id'] for row in states] + [row['responsible_id'] for row in states]
    )
    requesters = _person_counts(states, 'requester_id', OPEN_STATUSES, NO_REQUESTER, users)
    responsibles = _person_counts(states, 'responsible_id', ACTIVE_STATUSES, NO_RESPONSIBLE, users)

    # 6. Trend
    trend = []
    for offset in range(TREND_DAYS - 1, -1, -1):
        day = report_date - timedelta(days=offset)
        start, end = report_window(day)
        trend.append(TrendDay(
            date=day,
            new=Item.objects.filter(created_at__gte=start, created_at__lt=end).count(),
            closed=_closed_changes(start, end).count(),
            closed_complete=tracking_start is not None and start >= tracking_start,
            state=state if day == report_date else day_state(day, today, tracking_start),
        ))
    trend_has_gaps = any(d.state is None or not d.closed_complete for d in trend)

    return DailyReport(
        report_date=report_date,
        window_start=window_start,
        window_end=window_end,
        generated_at=now,
        new_items=new_items,
        closed_items=closed_items,
        closed_complete=closed_complete,
        state=state,
        state_hint=state_hint,
        requesters=requesters,
        responsibles=responsibles,
        trend=trend,
        trend_has_gaps=trend_has_gaps,
        history_start=tracking_start,
    )
