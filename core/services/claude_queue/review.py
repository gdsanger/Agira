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
        {"title": "...", "description": "...", "criterion": "..."}
      ]
    }

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

# Shown to Claude in the review prompt.
VERDICT_SCHEMA_EXAMPLE = """{
  "verdict": "pass | deviations",
  "summary": "short text",
  "criteria": [
    {"text": "acceptance criterion", "status": "met | not_met | accepted_deviation",
     "evidence": "file:line or PR hint"}
  ],
  "deviations": [
    {"title": "...", "description": "...", "criterion": "affected criterion"}
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


@dataclass
class ReviewVerdict:
    verdict: str
    summary: str = ''
    criteria: List[CriterionResult] = field(default_factory=list)
    deviations: List[Deviation] = field(default_factory=list)
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
        deviations.append(Deviation(
            title=title, description=description.strip(), criterion=criterion.strip(),
        ))

    has_not_met = any(c.status == STATUS_NOT_MET for c in criteria)
    if verdict == VERDICT_PASS:
        if has_not_met:
            return _unclear('verdict "pass" widerspricht Kriterium mit Status not_met')
        if deviations:
            return _unclear('verdict "pass" widerspricht nicht-leerer deviations-Liste')
    elif not deviations:
        return _unclear('verdict "deviations" ohne Eintrag in deviations')

    return ReviewVerdict(
        verdict=verdict, summary=summary, criteria=criteria, deviations=deviations,
    )


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
