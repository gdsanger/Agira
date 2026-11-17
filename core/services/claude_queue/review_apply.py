"""Apply a stored review verdict deterministically (Review 3/6).

Claude only produces the verdict; this module — run by the worker — writes the
report comment, closes the item on ``pass`` and files exactly one follow-up
item on ``deviations``. The follow-up deliberately points at the *GitHub PR*
(not at the Agira item): Claude Code and GitHub Copilot cannot read Agira, so
the description is self-contained and carries no Agira id or link.

Applying is idempotent per job: a marker in the report comment and
``job.review_followup_item`` guard against duplicates on retry / re-claim.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

from django.db import transaction

from core.models import (
    CommentKind,
    CommentVisibility,
    ExternalIssueKind,
    ExternalIssueMapping,
    Item,
    ItemComment,
    ItemRelation,
    ItemStatus,
    RelationType,
)
from core.services.activity import ActivityService
from core.services.claude_queue.review import (
    STATUS_ACCEPTED_DEVIATION,
    VERDICT_DEVIATIONS,
    VERDICT_PASS,
    VERDICT_UNCLEAR,
    ReviewVerdict,
    parse_review_verdict,
    strip_git_workflow_hint,
)

logger = logging.getLogger(__name__)

MARKER_TEMPLATE = '<!-- claude-queue:review-report job={job_id} -->'

_PR_URL_RE = re.compile(r'github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)')

_STATUS_LABELS = {
    'met': 'erfüllt',
    'not_met': 'nicht erfüllt',
    'accepted_deviation': 'akzeptierte Abweichung',
}


@dataclass
class ReviewApplyResult:
    outcome: str  # 'closed' | 'followup' | 'manual' | 'already_applied'
    comment: Optional[ItemComment] = None
    followup: Optional[Item] = None


def _cell(text: str) -> str:
    return (text or '').replace('|', '\\|').replace('\n', ' ').strip() or '–'


def _repo_ref(mapping) -> str:
    """``owner/repo#<nr>`` from the mapping's PR URL (``#<nr>`` if unparsable)."""
    m = _PR_URL_RE.search(mapping.html_url or '')
    return f'{m.group(1)}#{mapping.number}' if m else f'#{mapping.number}'


def _pr_mapping(item) -> Optional[ExternalIssueMapping]:
    """The PR mapping to cite: the merged one if any, else the newest."""
    mappings = list(
        ExternalIssueMapping.objects.filter(item=item, kind=ExternalIssueKind.PR)
        .order_by('-number')
    )
    for mapping in mappings:
        if mapping.merge_commit_sha and mapping.html_url:
            return mapping
    for mapping in mappings:
        if mapping.html_url:
            return mapping
    return None


def _decide(job, verdict: ReviewVerdict, mapping) -> str:
    """Return 'pass', 'deviations' or 'unclear' (the latter needs a human)."""
    if verdict.is_unclear or job.completion_uncertain:
        return VERDICT_UNCLEAR
    if verdict.verdict == VERDICT_PASS:
        # Only a blocking (major) finding prevents a pass; minor hints do not.
        return VERDICT_UNCLEAR if verdict.deviations else VERDICT_PASS
    if verdict.verdict == VERDICT_DEVIATIONS:
        # Guard: a follow-up needs at least one blocking (major) finding.
        if not verdict.deviations:
            return VERDICT_UNCLEAR
        return VERDICT_DEVIATIONS if mapping is not None else VERDICT_UNCLEAR
    return VERDICT_UNCLEAR


def followup_title(item, mapping) -> str:
    return f'Folge zu PR #{mapping.number}: {item.title} – Abweichungen aus Review'


def build_followup_description(item, verdict: ReviewVerdict, mapping, pr_text: str) -> str:
    """Self-contained follow-up text: PR reference, task, findings, scope limits."""
    ref = _repo_ref(mapping)
    lines = [
        '## Ursprung',
        f'Dieses Issue behebt Abweichungen aus der Umsetzung von GitHub-PR '
        f'[{ref}]({mapping.html_url}) ({mapping.html_url}).',
        'Diff, PR-Text und Begründungen stehen in diesem Pull Request.',
    ]
    if mapping.merge_commit_sha:
        lines.append(f'Merge-Commit: `{mapping.merge_commit_sha}`')
    lines += ['', '## Ursprünglicher Auftrag',
              strip_git_workflow_hint(item.description) or '(keine Beschreibung)', '']

    lines += ['## Festgestellte Abweichungen']
    for i, dev in enumerate(verdict.deviations, 1):
        lines.append(f'### {i}. {dev.title}')
        if dev.criterion:
            lines.append(f'- Betroffenes Kriterium: {dev.criterion}')
        evidence = next(
            (c.evidence for c in verdict.criteria
             if c.evidence and dev.criterion and c.text == dev.criterion),
            '',
        )
        if evidence:
            lines.append(f'- Beleg (Datei/Zeile): {evidence}')
        if dev.description:
            lines.append(f'- Erwartetes Verhalten / Befund: {dev.description}')
        lines.append('')

    accepted = [c for c in verdict.criteria if c.status == STATUS_ACCEPTED_DEVIATION]
    lines += ['## Im PR begründete, akzeptierte Abweichungen (nicht erneut umsetzen)']
    if accepted:
        for c in accepted:
            lines.append(f'- {c.text}' + (f' – {c.evidence}' if c.evidence else ''))
    else:
        lines.append('- Keine.')
    lines.append('')

    lines += ['## Akzeptanzkriterien']
    for dev in verdict.deviations:
        lines.append(f'- [ ] {dev.title}' + (f' (Kriterium: {dev.criterion})' if dev.criterion else ''))
    lines.append(f'- [ ] Der PR-Verweis {ref} bleibt als Ursprung nachvollziehbar.')
    return '\n'.join(lines).strip() + '\n'


def build_report(job, item, verdict: ReviewVerdict, decision: str, mapping,
                 followup: Optional[Item], pr_deviation_note: str = '') -> str:
    """Markdown report for the review comment (starts with the idempotency marker)."""
    when = (job.finished_at or job.created_at).strftime('%Y-%m-%d %H:%M')
    label = {
        VERDICT_PASS: 'pass',
        VERDICT_DEVIATIONS: 'deviations',
        VERDICT_UNCLEAR: 'unclear',
    }[decision]
    lines = [MARKER_TEMPLATE.format(job_id=job.pk),
             f'## Claude-Review – Job #{job.pk} ({when})', '',
             f'**Urteil:** {label}', '']
    if decision == VERDICT_UNCLEAR:
        reason = verdict.error or job.completion_uncertain_reason or ''
        if verdict.verdict == VERDICT_DEVIATIONS and mapping is None:
            reason = 'Kein GitHub-PR-Verweis am Item – kein Folge-Issue möglich.'
        lines += ['**Manuelle Prüfung nötig.**' + (f' {reason}' if reason else ''), '']
    if verdict.summary:
        lines += ['**Zusammenfassung:** ' + verdict.summary, '']
    if verdict.criteria:
        lines += ['### Akzeptanzkriterien', '',
                  '| Kriterium | Status | Beleg |', '|---|---|---|']
        for c in verdict.criteria:
            lines.append(
                f'| {_cell(c.text)} | {_STATUS_LABELS.get(c.status, c.status)} | {_cell(c.evidence)} |'
            )
        lines.append('')
    accepted = [c for c in verdict.criteria if c.status == STATUS_ACCEPTED_DEVIATION]
    if accepted:
        lines.append('### Akzeptierte Abweichungen (Begründung im PR)')
        lines += [f'- {c.text}' + (f' – {c.evidence}' if c.evidence else '') for c in accepted]
        lines.append('')
    if verdict.deviations:
        lines.append('### Abweichungen')
        for d in verdict.deviations:
            lines.append(
                f'- **{d.title}**' + (f' ({d.criterion})' if d.criterion else '')
                + (f': {d.description}' if d.description else '')
            )
        lines.append('')
    if verdict.hints:
        lines.append('### Hinweise (nicht blockierend)')
        for d in verdict.hints:
            evidence = next(
                (c.evidence for c in verdict.criteria
                 if c.evidence and d.criterion and c.text == d.criterion),
                '',
            )
            lines.append(
                f'- **{d.title}**' + (f' ({d.criterion})' if d.criterion else '')
                + (f': {d.description}' if d.description else '')
                + (f' – Beleg: {evidence}' if evidence else '')
            )
        lines.append('')
    if mapping is not None:
        lines += [f'**GitHub-PR:** [{_repo_ref(mapping)}]({mapping.html_url})', '']
    if followup is not None:
        lines += [f'**Folge-Issue:** #{followup.pk} – {followup.title}', '']
    if decision == VERDICT_PASS:
        lines += ['Das Item wurde auf *Closed* gesetzt.', '']
    return '\n'.join(lines).strip() + '\n'


def apply_review_result(job) -> ReviewApplyResult:
    """Apply ``job``'s stored verdict to its item; safe to call repeatedly."""
    from core.services.workflow import ItemWorkflowGuard

    item = job.item
    marker = MARKER_TEMPLATE.format(job_id=job.pk)
    existing = ItemComment.objects.filter(item=item, body__startswith=marker).first()
    if existing is not None or job.review_followup_item_id:
        return ReviewApplyResult(
            outcome='already_applied', comment=existing, followup=job.review_followup_item,
        )

    verdict = parse_review_verdict(job.review_report)
    mapping = _pr_mapping(item)
    decision = _decide(job, verdict, mapping)

    followup = None
    with transaction.atomic():
        if decision == VERDICT_DEVIATIONS:
            followup = Item.objects.create(
                project=item.project,
                parent=item.parent,
                type=item.type,
                status=ItemStatus.BACKLOG,
                title=followup_title(item, mapping),
                description=build_followup_description(
                    item, verdict, mapping, item.pr_description,
                ),
            )
            if any(c == RelationType.RELATED for c, _l in RelationType.choices):
                ItemRelation.objects.get_or_create(
                    from_item=followup, to_item=item, relation_type=RelationType.RELATED,
                )
            job.review_followup_item = followup
            job.save(update_fields=['review_followup_item'])
            ActivityService().log_created(
                target=followup, summary=f'Folge-Issue aus Review-Job #{job.pk} angelegt',
            )

        comment = ItemComment.objects.create(
            item=item,
            author=None,
            visibility=CommentVisibility.INTERNAL,
            kind=CommentKind.AI_GENERATED,
            subject='Claude-Review',
            body=build_report(job, item, verdict, decision, mapping, followup),
        )

    if decision == VERDICT_PASS:
        ItemWorkflowGuard().transition(item, ItemStatus.CLOSED, actor=None)
        outcome = 'closed'
    elif decision == VERDICT_DEVIATIONS:
        outcome = 'followup'
    else:
        outcome = 'manual'
        if not job.completion_uncertain:
            job.completion_uncertain = True
            job.completion_uncertain_reason = (
                'Review-Ergebnis nicht automatisch anwendbar – manuelle Prüfung nötig'
            )
            job.save(update_fields=['completion_uncertain', 'completion_uncertain_reason'])

    ActivityService().log(
        verb='claudequeuejob.review_applied',
        target=item,
        summary=f'Review-Job #{job.pk} angewendet: {decision} ({outcome})',
    )
    return ReviewApplyResult(outcome=outcome, comment=comment, followup=followup)
