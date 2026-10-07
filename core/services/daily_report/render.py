"""
HTML and plain-text rendering of the daily status report.

The HTML goes to Outlook, whose Word-based engine ignores most CSS: the
template therefore uses tables, inline styles and ``bgcolor``/``width``
attributes only — no external stylesheets, scripts or images.
"""

from django.template.loader import render_to_string

from .report import (
    ACTIVE_STATUSES,
    OPEN_STATUSES,
    SOURCE_HISTORY,
    SOURCE_LIVE,
    SOURCE_SNAPSHOT,
    STATUS_LABELS,
    DailyReport,
    report_timezone,
)

# Categorical status colours, validated for colour-vision deficiency in this
# order (adjacent stacked segments). Light steps for the white mail body; the
# dashboard uses the dark steps of the same hues (see dashboard.py).
STATUS_COLORS = {
    'Inbox': '#2a78d6',
    'Backlog': '#eb6834',
    'Working': '#1baf7a',
    'Testing': '#eda100',
    'Review': '#e87ba4',
    'ReadyForRelease': '#008300',
    'Closed': '#4a3aa7',
}

WEEKDAYS = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So']
BAR_WIDTH_PX = 240
GAP = '–'

SOURCE_LABELS = {
    SOURCE_LIVE: 'aktuell',
    SOURCE_SNAPSHOT: 'Snapshot',
    SOURCE_HISTORY: 'Historie',
}


def _fmt_dt(value) -> str:
    return value.astimezone(report_timezone()).strftime('%d.%m.%Y %H:%M')


def _fmt_day(value) -> str:
    return f"{WEEKDAYS[value.weekday()]} {value.strftime('%d.%m.')}"


def _notes(report: DailyReport) -> list:
    notes = []
    if report.state_hint:
        notes.append(report.state_hint)
    if not report.closed_complete:
        notes.append(
            '„Geschlossen“ stammt für dieses Fenster (teilweise) aus der Zeit vor der '
            'lückenlosen Statusprotokollierung und kann unvollständig sein.'
        )
    if report.trend_has_gaps:
        since = _fmt_dt(report.history_start) if report.history_start else 'noch nicht'
        notes.append(
            f'Verlauf: Statushistorie lückenlos seit {since}. Tage davor sind mit „{GAP}“ '
            '(keine Daten) bzw. „*“ (möglicherweise unvollständig) gekennzeichnet.'
        )
    return notes


def build_context(report: DailyReport) -> dict:
    open_labels = [STATUS_LABELS[s] for s in OPEN_STATUSES]
    active_labels = [STATUS_LABELS[s] for s in ACTIVE_STATUSES]

    max_open = max((d.state.total for d in report.trend if d.state), default=0) or 1
    trend_rows = []
    for day in report.trend:
        segments = []
        if day.state:
            for status in OPEN_STATUSES:
                count = day.state.counts.get(status, 0)
                if count:
                    segments.append({
                        'color': STATUS_COLORS[status],
                        'width': max(1, round(count / max_open * BAR_WIDTH_PX)),
                        'label': STATUS_LABELS[status],
                        'count': count,
                    })
        trend_rows.append({
            'day': _fmt_day(day.date),
            'new': day.new,
            'closed': f"{day.closed}{'' if day.closed_complete else '*'}",
            'open': day.state.total if day.state else GAP,
            'counts': [day.state.counts.get(s, 0) for s in OPEN_STATUSES] if day.state else [GAP] * len(OPEN_STATUSES),
            'source': SOURCE_LABELS.get(day.state.source, '') if day.state else 'keine Daten',
            'segments': segments,
            'gap': day.state is None,
        })

    return {
        'report': report,
        'subject': report.subject,
        'window': f"{_fmt_dt(report.window_start)} – {_fmt_dt(report.window_end)}",
        'generated': _fmt_dt(report.generated_at),
        'open_labels': open_labels,
        'legend': [{'label': STATUS_LABELS[s], 'color': STATUS_COLORS[s]} for s in OPEN_STATUSES],
        'status_totals': [
            {'label': STATUS_LABELS[s], 'count': report.state.counts.get(s, 0), 'color': STATUS_COLORS[s]}
            for s in OPEN_STATUSES
        ],
        'total_open': report.state.total,
        'projects': [
            {'name': name, 'counts': [counts.get(s, 0) for s in OPEN_STATUSES], 'total': total}
            for name, counts, total in report.projects
        ],
        'requesters': report.requesters,
        'requesters_total': sum(p.total for p in report.requesters),
        'active_labels': active_labels,
        'responsibles': [
            {
                'name': p.name,
                'placeholder': p.is_placeholder,
                'counts': [p.per_status.get(s, 0) for s in ACTIVE_STATUSES],
                'total': p.total,
            }
            for p in report.responsibles
        ],
        'responsibles_total': sum(p.total for p in report.responsibles),
        'trend': trend_rows,
        'notes': _notes(report),
    }


def render_html(report: DailyReport) -> str:
    return render_to_string('emails/daily_status_report.html', build_context(report))


# ---------------------------------------------------------------------------
# Plain text
# ---------------------------------------------------------------------------

def _table(headers, rows) -> list:
    rows = [[str(c) for c in row] for row in rows]
    widths = [max(len(str(h)), *(len(r[i]) for r in rows)) if rows else len(str(h)) for i, h in enumerate(headers)]

    def line(cells):
        # First column left-aligned (names), numbers right-aligned.
        return '  '.join(
            str(c).ljust(widths[i]) if i == 0 else str(c).rjust(widths[i]) for i, c in enumerate(cells)
        ).rstrip()

    return [line(headers), '  '.join('-' * w for w in widths)] + [line(r) for r in rows]


def _item_lines(items, person_label) -> list:
    if not items:
        return ['  (keine)']
    return [f"  #{i.id}  {i.title}  [{i.project}]  {person_label}: {i.person or '–'}" for i in items]


def render_text(report: DailyReport) -> str:
    ctx = build_context(report)
    out = [
        report.subject,
        '=' * len(report.subject),
        f"Zeitfenster: {ctx['window']}",
        f"Erzeugt: {ctx['generated']}",
        '',
        f"1. Neue Items (24 h): {len(report.new_items)}",
        *_item_lines(report.new_items, 'Requester'),
        '',
        f"2. Statusverteilung (offen gesamt: {ctx['total_open']})",
        *_table(['Status', 'Anzahl'], [[s['label'], s['count']] for s in ctx['status_totals']]),
        '',
        '   Nach Projekt:',
        *_table(
            ['Projekt', *ctx['open_labels'], 'Summe'],
            [[p['name'], *p['counts'], p['total']] for p in ctx['projects']],
        ),
        '',
        f"3. Geschlossen (24 h): {len(report.closed_items)}{'' if report.closed_complete else ' *'}",
        *_item_lines(report.closed_items, 'Responsible'),
        '',
        '4. Offene Items je Requester',
        *_table(
            ['Requester', 'Offen'],
            [[p.name, p.total] for p in report.requesters] + [['Summe', ctx['requesters_total']]],
        ),
        '',
        '5. Responsible in Bearbeitung (Working/Implemented/Clarification)',
        *_table(
            ['Responsible', *ctx['active_labels'], 'Summe'],
            [[p['name'], *p['counts'], p['total']] for p in ctx['responsibles']]
            + [['Summe', *[''] * len(ctx['active_labels']), ctx['responsibles_total']]],
        ),
        '',
        '6. Verlauf 7 Tage',
        *_table(
            ['Tag', 'Neu', 'Geschl.', 'Offen', *ctx['open_labels'], 'Quelle'],
            [[r['day'], r['new'], r['closed'], r['open'], *r['counts'], r['source']] for r in ctx['trend']],
        ),
    ]
    if ctx['notes']:
        out += ['', 'Hinweise:'] + [f"  - {n}" for n in ctx['notes']]
    return '\n'.join(out) + '\n'
