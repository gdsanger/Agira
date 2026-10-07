"""
Dashboard view-model built on the daily status report (#dashboard).

The dashboard shows the same status distribution and 7-day trend as the
mail report, limited to the projects the user is assigned to, plus per-person
status breakdowns (responsible / assigned to) as stacked bar charts.
"""

from datetime import timedelta
from typing import Dict, List, Optional

from django.db.models import Count, DateTimeField, Max, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.models import Item, ItemStatus, User

from .render import build_context
from .report import OPEN_STATUSES, STATUS_LABELS, build_report, local_today, user_display_name

# Same hues and order as the mail palette, stepped for Agira's dark surface
# (#121720) and validated as a set: CVD-safe for adjacent segments, >= 3:1.
STATUS_COLORS_DARK = {
    'Inbox': '#3987e5',
    'Backlog': '#d95926',
    'Working': '#199e70',
    'Testing': '#c98500',
    'Review': '#d55181',
    'ReadyForRelease': '#008300',
    'Closed': '#9085e9',
}

PERSON_STATUSES = OPEN_STATUSES + [ItemStatus.CLOSED]
CLOSED_DAYS = 7


def annotate_closed_at(items):
    """Annotate ``closed_at``: the latest switch to Closed, else ``updated_at``.

    The status history only exists since #daily_status_report; older items fall
    back to ``updated_at`` so they do not vanish from 7-day figures.
    """
    return items.annotate(
        last_closed_change=Max(
            'status_changes__changed_at',
            filter=Q(status_changes__to_status=ItemStatus.CLOSED),
        ),
    ).annotate(
        closed_at=Coalesce('last_closed_change', 'updated_at', output_field=DateTimeField()),
    )


def closed_since(items, since):
    """Items currently Closed whose closing happened at or after ``since``."""
    return annotate_closed_at(items.filter(status=ItemStatus.CLOSED)).filter(closed_at__gte=since)


def person_status_breakdown(items, field: str, empty_label: str, now=None) -> List[dict]:
    """Open items per person and status, plus items closed in the last 7 days.

    ``field`` is the user FK on Item (``responsible`` or ``assigned_to``).
    Returns rows ``{name, counts: {status: n}, total, placeholder}`` sorted by
    total, the "nobody" row last.
    """
    now = now or timezone.now()
    key = f'{field}_id'
    counts: Dict[Optional[int], Dict[str, int]] = {}

    open_rows = (
        items.exclude(status=ItemStatus.CLOSED)
        .values(key, 'status')
        .annotate(n=Count('id'))
    )
    for row in open_rows:
        counts.setdefault(row[key], {})[row['status']] = row['n']

    closed_ids = list(closed_since(items, now - timedelta(days=CLOSED_DAYS)).values_list('id', flat=True))
    closed_rows = Item.objects.filter(id__in=closed_ids).values(key).annotate(n=Count('id'))
    for row in closed_rows:
        counts.setdefault(row[key], {})[ItemStatus.CLOSED] = row['n']

    users = {u.id: u for u in User.objects.filter(id__in=[k for k in counts if k])}
    result = []
    for user_id, per_status in counts.items():
        result.append({
            'name': user_display_name(users.get(user_id)) if user_id else empty_label,
            'counts': {s: per_status.get(s, 0) for s in PERSON_STATUSES},
            'total': sum(per_status.values()),
            'placeholder': not user_id,
        })
    return sorted(result, key=lambda r: (r['placeholder'], -r['total'], r['name'].lower()))


def person_chart(rows: List[dict]) -> dict:
    """Chart.js data for a horizontal stacked bar chart of ``person_status_breakdown``."""
    return {
        'labels': [r['name'] for r in rows],
        'datasets': [
            {
                'label': f"{STATUS_LABELS[s]} ({CLOSED_DAYS}d)" if s == ItemStatus.CLOSED else STATUS_LABELS[s],
                'status': s,
                'data': [r['counts'][s] for r in rows],
                'backgroundColor': STATUS_COLORS_DARK[s],
            }
            for s in PERSON_STATUSES
        ],
    }


def trend_chart(context: dict, report) -> dict:
    """Chart.js data for the 7-day open-item trend (stacked by status)."""
    labels = [row['day'] for row in context['trend']]
    return {
        'labels': labels,
        'datasets': [
            {
                'label': STATUS_LABELS[s],
                'status': s,
                # None leaves a visible gap for days without data.
                'data': [day.state.counts.get(s, 0) if day.state else None for day in report.trend],
                'backgroundColor': STATUS_COLORS_DARK[s],
            }
            for s in OPEN_STATUSES
        ],
    }


def build_dashboard_status(project_ids) -> dict:
    """Everything the status sections of the dashboard need, scoped to ``project_ids``."""
    project_ids = list(project_ids)
    items = Item.objects.filter(project_id__in=project_ids)
    report = build_report(local_today(), project_ids=project_ids)
    context = build_context(report)

    responsible_rows = person_status_breakdown(items, 'responsible', 'No responsible')
    assigned_rows = person_status_breakdown(items, 'assigned_to', 'Unassigned')

    return {
        'status_report': report,
        'status_totals': [
            {**row, 'color': STATUS_COLORS_DARK[status]}
            for row, status in zip(context['status_totals'], OPEN_STATUSES)
        ],
        'status_total_open': context['total_open'],
        'status_open_labels': context['open_labels'],
        'status_projects': context['projects'],
        'trend_rows': context['trend'],
        'trend_notes': context['notes'],
        'trend_chart': trend_chart(context, report),
        'responsible_chart': person_chart(responsible_rows),
        'assigned_chart': person_chart(assigned_rows),
        'responsible_rows': responsible_rows,
        'assigned_rows': assigned_rows,
        'person_statuses': [
            {'label': STATUS_LABELS[s], 'color': STATUS_COLORS_DARK[s]} for s in PERSON_STATUSES
        ],
    }
