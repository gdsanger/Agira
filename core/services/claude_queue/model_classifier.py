"""Hybrid classifier for Item.suggested_model (#834).

Cheap text heuristics run first; the Haiku agent is only consulted when
the heuristics are inconclusive. The result is a suggestion, not a gate:
it is always overridable in the UI, and the enqueue flow (#833) reads it
via plain attribute access on Item.
"""

import logging
import re
from typing import Optional

from core.models import ClaudeQueueJobModel
from core.services.agents.agent_service import AgentService

logger = logging.getLogger(__name__)

MIGRATION_KEYWORDS = (
    'migration', 'migrate', 'migrating', 'schema change', 'schema-change',
    'datenbankmigration', 'db migration', 'alter table',
)

SECURITY_KEYWORDS = (
    'security', 'sicherheit', 'authentifizierung', 'authentication',
    'authorization', 'autorisierung', 'password', 'passwort', 'permission',
    'berechtigung', 'vulnerability', 'schwachstelle', 'cve', 'encryption',
    'verschlüsselung', 'secret', 'geheimnis', 'token', 'xss', 'csrf',
    'sql injection', 'rbac', 'oauth', 'zugriffskontrolle',
)

LARGE_SCOPE_KEYWORDS = (
    'refactor', 'architecture', 'architektur', 'redesign', 'rewrite',
    'breaking change', 'gesamte codebase', 'across the codebase',
    'mehrere module', 'multiple modules', 'multiple services',
)

FILE_PATH_PATTERN = re.compile(r'\b[\w./-]+\.[A-Za-z]{1,5}\b')

MIN_WORDS_FOR_CONFIDENT_SONNET = 10
MIN_FILE_MENTIONS_FOR_OPUS = 3

# The classifier only distinguishes "cheap default" from "needs an Opus-class
# model" — picking *which* Opus generation is a human call, made in the UI
# (#1082). Its coarse verdict therefore lands on Opus 4.8, the cheaper of the
# two; the Haiku agent's vocabulary is unchanged and its bare 'opus' is mapped
# onto the same value.
AUTO_DETECT_OPUS = ClaudeQueueJobModel.OPUS_4_8

_HAIKU_VALUE_ALIASES = {
    'sonnet': ClaudeQueueJobModel.SONNET,
    'opus': AUTO_DETECT_OPUS,
}


def _text_for(item) -> str:
    """Concatenate the item's textual fields for keyword/heuristic scans."""
    return '\n'.join([item.title or '', item.description or '', item.user_input or ''])


def _contains_any(text: str, keywords) -> bool:
    return any(keyword in text for keyword in keywords)


def classify_by_heuristics(item) -> Optional[str]:
    """Cheap, deterministic first pass.

    Returns AUTO_DETECT_OPUS or 'sonnet' when confident, None when the signals
    are inconclusive and a Haiku call is warranted.
    """
    text = _text_for(item).lower()

    if _contains_any(text, MIGRATION_KEYWORDS):
        return AUTO_DETECT_OPUS
    if _contains_any(text, SECURITY_KEYWORDS):
        return AUTO_DETECT_OPUS
    if _contains_any(text, LARGE_SCOPE_KEYWORDS):
        return AUTO_DETECT_OPUS
    if len(FILE_PATH_PATTERN.findall(text)) >= MIN_FILE_MENTIONS_FOR_OPUS:
        return AUTO_DETECT_OPUS

    if len((item.description or '').split()) >= MIN_WORDS_FOR_CONFIDENT_SONNET:
        return ClaudeQueueJobModel.SONNET

    # Too short/vague to be confident either way.
    return None


class ModelClassifierService:
    """Hybrid suggested_model classifier: heuristics first, Haiku fallback."""

    HAIKU_AGENT_FILENAME = 'model-classifier-agent.yml'

    def __init__(self, agent_service: Optional[AgentService] = None):
        self.agent_service = agent_service or AgentService()

    def classify(self, item) -> str:
        """Return the suggested Claude model for item.

        The result is one of ``ClaudeQueueJobModel.SONNET`` /
        ``AUTO_DETECT_OPUS``; the remaining choices are manual-only (#1082).

        Never raises: any failure in the Haiku fallback degrades to the
        safe default (sonnet) rather than silently defaulting to opus.
        """
        heuristic_result = classify_by_heuristics(item)
        if heuristic_result is not None:
            return heuristic_result

        return self._classify_with_haiku(item) or ClaudeQueueJobModel.SONNET

    def _classify_with_haiku(self, item) -> Optional[str]:
        context = f"Title: {item.title}\n\nDescription:\n{item.description}"
        try:
            response = self.agent_service.execute_agent(
                filename=self.HAIKU_AGENT_FILENAME,
                input_text=context,
            )
        except Exception as e:
            logger.warning(f"Haiku model classification failed: {e}, defaulting to sonnet")
            return None

        value = response.strip().lower()
        if value in _HAIKU_VALUE_ALIASES:
            return _HAIKU_VALUE_ALIASES[value]

        logger.warning(f"Haiku model classification returned unexpected value {value!r}, defaulting to sonnet")
        return None
