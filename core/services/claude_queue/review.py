"""Verdict schema and strict parser for ``review`` queue jobs.

Claude is asked to answer a review with one JSON object::

    {
      "verdict": "pass" | "deviations",
      "summary": "short text",
      "criteria": [
        {"text": "...", "status": "met" | "not_met" | "accepted_deviation",
         "evidence": "file:line or PR hint"}
      ],
      "deviations": [
        {"title": "...", "description": "...", "criterion": "...",
         "severity": "major" | "minor"}
      ]
    }

``major`` findings block (verdict ``deviations``); ``minor`` findings are
non-blocking hints (verdict ``pass``). A missing or invalid ``severity``
counts as ``major``.

``unclear`` is never produced by Claude: it is the parser's own result for
anything it cannot trust (no JSON, malformed JSON, schema violations or a
verdict that contradicts the criteria). The parser never raises — a review
that cannot be read must end up as ``unclear`` for a human, not as a crash
in the worker.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional

VERDICT_PASS = 'pass'
VERDICT_DEVIATIONS = 'deviations'
VERDICT_UNCLEAR = 'unclear'

CLAUDE_VERDICTS = (VERDICT_PASS, VERDICT_DEVIATIONS)

STATUS_MET = 'met'
STATUS_NOT_MET = 'not_met'
STATUS_ACCEPTED_DEVIATION = 'accepted_deviation'
CRITERION_STATUSES = (STATUS_MET, STATUS_NOT_MET, STATUS_ACCEPTED_DEVIATION)

SEVERITY_MAJOR = 'major'
SEVERITY_MINOR = 'minor'
SEVERITIES = (SEVERITY_MAJOR, SEVERITY_MINOR)

# Shown to Claude in the review prompt.
VERDICT_SCHEMA_EXAMPLE = """{
  "verdict": "pass | deviations",
  "summary": "short text",
  "criteria": [
    {"text": "acceptance criterion", "status": "met | not_met | accepted_deviation",
     "evidence": "file:line or PR hint"}
  ],
  "deviations": [
    {"title": "...", "description": "...", "criterion": "affected criterion",
     "severity": "major | minor"}
  ]
}"""


@dataclass
class CriterionResult:
    text: str
    status: str
    evidence: str = ''


@dataclass
class Deviation:
    title: str
    description: str = ''
    criterion: str = ''
    severity: str = SEVERITY_MAJOR


@dataclass
class ReviewVerdict:
    verdict: str
    summary: str = ''
    criteria: List[CriterionResult] = field(default_factory=list)
    # Blocking (major) findings only; they drive the follow-up item.
    deviations: List[Deviation] = field(default_factory=list)
    # Non-blocking (minor) findings; reported but never block the close.
    hints: List[Deviation] = field(default_factory=list)
    # Why the result is ``unclear``; empty for a valid verdict.
    error: str = ''

    @property
    def is_unclear(self) -> bool:
        return self.verdict == VERDICT_UNCLEAR


def _unclear(reason: str, summary: str = '') -> ReviewVerdict:
    return ReviewVerdict(verdict=VERDICT_UNCLEAR, summary=summary, error=reason)


_FENCE_RE = re.compile(r'```[a-zA-Z0-9_-]*\s*\n(.*?)```', re.DOTALL)


def _iter_json_objects(text: str):
    """Yield every top-level ``{...}`` substring that parses as a JSON object."""
    decoder = json.JSONDecoder()
    pos = 0
    while True:
        start = text.find('{', pos)
        if start == -1:
            return
        try:
            obj, end = decoder.raw_decode(text, start)
        except ValueError:
            pos = start + 1
            continue
        if isinstance(obj, dict):
            yield obj
        pos = end


def _extract_candidates(text: str) -> List[dict]:
    """Candidate verdict objects: whole text, fenced blocks, then inline."""
    sources = [text]
    sources.extend(m.group(1) for m in _FENCE_RE.finditer(text))
    candidates: List[dict] = []
    for src in sources:
        candidates.extend(_iter_json_objects(src))
    # Prefer objects that look like a verdict; the last one wins, since a
    # final answer follows any quoted examples earlier in the text.
    verdictish = [c for c in candidates if 'verdict' in c]
    return verdictish


def _str(value: Any) -> Optional[str]:
    return value.strip() if isinstance(value, str) else None


def _validate(data: dict) -> ReviewVerdict:
    verdict = data.get('verdict')
    if verdict not in CLAUDE_VERDICTS:
        return _unclear(f'Ungültiges verdict: {verdict!r}')

    summary = _str(data.get('summary'))
    if summary is None:
        return _unclear('summary fehlt oder ist kein Text')

    raw_criteria = data.get('criteria')
    if not isinstance(raw_criteria, list):
        return _unclear('criteria fehlt oder ist keine Liste')
    criteria: List[CriterionResult] = []
    for i, c in enumerate(raw_criteria):
        if not isinstance(c, dict):
            return _unclear(f'criteria[{i}] ist kein Objekt')
        text = _str(c.get('text'))
        if not text:
            return _unclear(f'criteria[{i}].text fehlt')
        status = c.get('status')
        if status not in CRITERION_STATUSES:
            return _unclear(f'criteria[{i}].status ungültig: {status!r}')
        evidence = c.get('evidence', '')
        if not isinstance(evidence, str):
            return _unclear(f'criteria[{i}].evidence ist kein Text')
        criteria.append(CriterionResult(text=text, status=status, evidence=evidence.strip()))

    raw_deviations = data.get('deviations')
    if not isinstance(raw_deviations, list):
        return _unclear('deviations fehlt oder ist keine Liste')
    deviations: List[Deviation] = []
    for i, d in enumerate(raw_deviations):
        if not isinstance(d, dict):
            return _unclear(f'deviations[{i}] ist kein Objekt')
        title = _str(d.get('title'))
        if not title:
            return _unclear(f'deviations[{i}].title fehlt')
        description = d.get('description', '')
        criterion = d.get('criterion', '')
        if not isinstance(description, str) or not isinstance(criterion, str):
            return _unclear(f'deviations[{i}] hat ungültige Felder')
        severity = d.get('severity')
        if severity not in SEVERITIES:
            severity = SEVERITY_MAJOR  # safe default
        deviations.append(Deviation(
            title=title, description=description.strip(), criterion=criterion.strip(),
            severity=severity,
        ))

    # The verdict is derived from the criteria and the severity of the
    # findings; the model's ``verdict`` field is supplementary information only.
    # Only a ``major`` finding on a ``not_met`` criterion blocks.
    not_met = [c for c in criteria if c.status == STATUS_NOT_MET]

    # Deviations must refer to a criterion. ``major`` ones referring to a met /
    # accepted_deviation criterion are redundant and dropped; ``minor`` ones are
    # kept as hints whatever the criterion's status.
    major: List[Deviation] = []
    hints: List[Deviation] = []
    for i, dev in enumerate(deviations):
        crit = _match_criterion(dev.criterion, criteria)
        if crit is None:
            return _unclear(f'deviations[{i}] ist keinem Kriterium zuordenbar')
        resolved = Deviation(
            title=dev.title, description=dev.description, criterion=crit.text,
            severity=dev.severity,
        )
        if dev.severity == SEVERITY_MINOR:
            hints.append(resolved)
        elif crit.status == STATUS_NOT_MET:
            major.append(resolved)

    # A not_met criterion without any finding yields a (major) deviation; one
    # that only has minor findings is carried by those hints.
    covered = {d.criterion for d in major} | {d.criterion for d in hints}
    for c in not_met:
        if c.text not in covered:
            major.append(Deviation(
                title=c.text, description=c.evidence, criterion=c.text,
                severity=SEVERITY_MAJOR,
            ))

    if verdict == VERDICT_PASS and major:
        return _unclear('verdict "pass" widerspricht Kriterium mit Status not_met')

    return ReviewVerdict(
        verdict=VERDICT_DEVIATIONS if major else VERDICT_PASS,
        summary=summary, criteria=criteria, deviations=major, hints=hints,
    )


def _norm(text: str) -> str:
    return ' '.join((text or '').split()).casefold()


def _match_criterion(ref: str, criteria: List[CriterionResult]) -> Optional[CriterionResult]:
    """Criterion a deviation refers to (normalised exact match), else ``None``."""
    key = _norm(ref)
    if not key:
        return None
    for c in criteria:
        if _norm(c.text) == key:
            return c
    return None


def parse_review_verdict(raw: Any) -> ReviewVerdict:
    """Parse Claude's answer into a :class:`ReviewVerdict`; never raises."""
    if not isinstance(raw, str) or not raw.strip():
        return _unclear('Leere Antwort')
    try:
        candidates = _extract_candidates(raw)
        if not candidates:
            return _unclear('Kein JSON-Urteil in der Antwort gefunden')
        # Prefer the last valid candidate; if none is valid report the last error.
        result = None
        for cand in reversed(candidates):
            result = _validate(cand)
            if not result.is_unclear:
                return result
        return result
    except Exception as exc:  # defensive: the contract is "no exception"
        return _unclear(f'Urteil nicht lesbar: {exc}')


# --------------------------------------------------------------------------- #
# Review prompt
# --------------------------------------------------------------------------- #

# Upper bound for the diff embedded in the prompt; the checkout is available
# to Claude for anything beyond it.
MAX_DIFF_CHARS = 150_000

REVIEW_RULES = """\
## Regeln
- Prüfe jedes Akzeptanzkriterium des Issues gegen den Code im Checkout (nur lesen).
- Eine im PR-Text (insbesondere „Warum / Entscheidungen“) **begründete, bewusste Abweichung** ist keine Abweichung: Status `accepted_deviation`, in `evidence` mit Verweis auf die Begründung.
- Eine **unbegründete** Lücke ist `not_met`.
- Im Zweifel `not_met` statt `met`.
- Dieses Review prüft **Vollständigkeit und Plausibilität** der Umsetzung, nicht die fachliche Korrektheit zur Laufzeit (der fachliche Test findet später statt).
- Jeder Eintrag in `deviations` bezieht sich auf ein Kriterium (`criterion` = exakter Text des Kriteriums) und hat eine `severity`:
  - `major`: ein Kriterium ist fachlich nicht erreicht oder Verhalten/Funktion fehlt. Beispiel: ein geforderter Endpunkt fehlt.
  - `minor`: formal, kosmetisch, rein dokumentarisch, Widerspruch/Unschärfe in der Vorgabe selbst oder eine Anregung zur Verbesserung. Beispiel: eine Datei fehlt, obwohl das Issue selbst sagt, dass der Bereich diese gar nicht kennt; ein fehlender Docstring.
  - Bei Zweifel zwischen `major` und `minor`: `major`, außer die Vorgabe widerspricht sich selbst oder der Befund ist rein formal.
  - Fehlt `severity` oder ist sie ungültig, gilt der Eintrag als `major`.
- Im PR begründete, akzeptierte Abweichungen stehen nur in `criteria` (Status `accepted_deviation`) und **nicht** in `deviations`.
- Das Urteil ergibt sich aus den Befunden: `deviations`, wenn mindestens ein `major`-Befund zu einem `not_met`-Kriterium existiert, sonst `pass`. Nur `minor`-Befunde ergeben `pass` mit Hinweisen (nicht blockierend, kein Folge-Issue).
- Verändere nichts: kein Schreiben, kein Commit, kein Push, kein PR.
- Du läufst headless: Führe alle Befehle im Vordergrund aus; plane keine Wakeups.
- Antworte ausschließlich mit **einem** JSON-Objekt nach diesem Schema, ohne Text davor oder danach:

"""


def strip_git_workflow_hint(text: str) -> str:
    """Drop the queue's git-workflow hint (and anything after it) from a text."""
    from core.services.claude_queue.hint import GIT_WORKFLOW_HINT_MARKER

    text = text or ''
    idx = text.find(GIT_WORKFLOW_HINT_MARKER)
    if idx != -1:
        text = text[:idx]
    return text.strip()


def build_review_prompt(item, pr_text: Optional[str] = None, diff: str = '') -> str:
    """Build the read-only review prompt for ``item``.

    ``pr_text`` defaults to ``item.pr_description``; ``diff`` is the PR diff
    against its base (the epic branch for a sub-issue).
    """
    pr_text = (pr_text if pr_text is not None else item.pr_description) or ''
    diff = diff or ''
    if len(diff) > MAX_DIFF_CHARS:
        diff = (
            diff[:MAX_DIFF_CHARS]
            + '\n[... Diff gekürzt – den Rest per `git diff` im Checkout lesen ...]'
        )

    parts = [f'# Review: {item.title}', '',
             'Prüfe, ob die Umsetzung dieses Issues (Checkout im aktuellen '
             'Verzeichnis) die Anforderungen erfüllt.', '']
    description = strip_git_workflow_hint(item.description)
    if description:
        parts += ['## Issue-Beschreibung und Akzeptanzkriterien', description, '']
    if item.solution_description:
        parts += ['## Erwartete Lösung', item.solution_description.strip(), '']
    parts += ['## PR-Text', pr_text.strip() or '(kein PR-Text vorhanden)', '']
    parts += ['## Diff des PR', '```diff', diff.strip() or '(leer)', '```', '']
    parts += [REVIEW_RULES + VERDICT_SCHEMA_EXAMPLE]
    return '\n'.join(parts)
