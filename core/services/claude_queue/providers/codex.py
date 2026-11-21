"""OpenAI Codex provider: ``codex exec`` behind the queue worker (#1298).

Counterpart of :mod:`providers.claude`. Everything here is derived from the
*assumptions* in ``docs/CODEX_CLI_SPIKE.md`` — the spike's measurements are
still open, so event names and error texts are matched tolerantly and pinned by
the synthetic streams in ``test_codex_provider``. Decisions:

* **Sandbox:** the implementation run uses
  ``--dangerously-bypass-approvals-and-sandbox``. The worker flow needs commit,
  push and ``gh`` from inside the run (like ``--dangerously-skip-permissions``
  for Claude), which ``workspace-write`` would likely block (spike §4). The
  worker host is the isolation boundary. Review runs stay ``read-only``.
* **Usage:** token counts (summed over ``turn.completed``) are stored on the
  job. ``num_turns`` is the number of completed turns. ``total_cost_usd`` stays
  empty: Codex reports no cost and a price table would silently go stale.
* **Limits:** API-key runs report 429s with at most a *relative* wait; there is
  no subscription reset time. ``insufficient_quota`` (empty balance) is not a
  temporary limit and is classified as a credential/billing failure instead of
  being parked.
"""

from __future__ import annotations

import json
import os
import re
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from core.models import ClaudeCredentialSource, ClaudeQueueJobAuthMode, openai_cli_model_id
from core.services.claude_queue.credentials import resolve_openai_credential
from core.services.claude_queue.review import VERDICT_JSON_SCHEMA
from core.services.claude_queue.providers.base import AgentProvider, save_progress

DEFAULT_TIMEOUT_SECONDS = 120 * 60

# Variables that could steer auth or routing of the child. All are removed
# before the job's own key is set, so nothing inherited from the host decides.
FOREIGN_ENV_VARS = (
    'OPENAI_API_KEY',
    'CODEX_API_KEY',
    'OPENAI_BASE_URL',
    'OPENAI_API_BASE',
    'OPENAI_ORG_ID',
    'OPENAI_ORGANIZATION',
    'OPENAI_PROJECT',
    'OPENAI_PROJECT_ID',
    'CODEX_HOME',
)

# Item types whose execution can be silent for a long time (test runs, MCP
# calls): the idle watchdog pauses while one is in flight.
TOOL_ITEM_TYPES = {'command_execution', 'mcp_tool_call', 'web_search', 'file_change'}

# ``insufficient_quota`` is deliberately absent: see module docstring.
LIMIT_MARKERS = (
    'rate limit',
    'rate_limit',
    'ratelimit',
    'usage limit',
    'too many requests',
    'status code 429',
    '"status":429',
    ' 429 ',
    'limit reached',
    'limit exceeded',
)

QUOTA_MARKERS = (
    'insufficient_quota',
    'exceeded your current quota',
)

AUTH_ERROR_MARKERS = (
    'invalid api key',
    'incorrect api key',
    'invalid_api_key',
    'missing bearer',
    'authentication',
    'unauthorized',
    '401',
    'not logged in',
    'no api key',
    'missing api key',
    'codex login',
)

# "try again in 1.2s", "in 6m0s", "in 2 hours 3 minutes", "retry after 30 seconds"
_RELATIVE_WAIT = re.compile(
    r'(?:try again|retry)(?: again)?\s+(?:in|after)\s+([0-9a-z.\s,]+?)(?:[.;]|$|\n)', re.I,
)
_DURATION_PART = re.compile(
    r'(\d+(?:\.\d+)?)\s*(ms|milliseconds?|s|secs?|seconds?|m|mins?|minutes?|h|hrs?|hours?|d|days?)(?![a-z])',
    re.I,
)
_UNIT_SECONDS = {'ms': 0.001, 's': 1, 'm': 60, 'h': 3600, 'd': 86400}


def _unit_seconds(unit):
    unit = unit.lower()
    if unit.startswith('ms') or unit.startswith('milli'):
        return _UNIT_SECONDS['ms']
    return _UNIT_SECONDS[unit[0]]


class CodexProvider(AgentProvider):
    name = 'openai'
    allowed_tools = 'shell, apply_patch (sandbox bypassed)'

    # -- command line ---------------------------------------------------- #
    def build_args(self, job):
        """``codex exec`` command line; the prompt is read from stdin (``-``)."""
        model = self.model_id(job.model or job.item.suggested_model)
        args = [
            settings.CODEX_CLI_BIN, 'exec',
            '--json',
            '--skip-git-repo-check',
            '-m', model,
        ]
        if job.is_review:
            schema_file, message_file = self._review_files(job)
            args += [
                '-s', 'read-only', '-c', 'approval_policy=never',
                '--output-schema', str(schema_file),
                '--output-last-message', str(message_file),
            ]
        else:
            args += ['--dangerously-bypass-approvals-and-sandbox']
        args.append('-')
        return args

    def model_id(self, slug):
        return openai_cli_model_id(slug)

    # -- review verdict channel ------------------------------------------ #
    def _review_dir(self, job):
        return self._codex_home() / 'review' / str(job.pk)

    def _review_files(self, job):
        """Schema and last-message file of a review run (outside the checkout).

        They live under ``CODEX_HOME`` so the read-only review never needs a
        writable checkout and nothing lands in the repo. The schema is
        (re)written on every call; a stale answer file is removed so a failed
        run can never be mistaken for a verdict.
        """
        directory = self._review_dir(job)
        directory.mkdir(parents=True, exist_ok=True)
        schema_file = directory / 'verdict.schema.json'
        message_file = directory / 'last-message.json'
        schema_file.write_text(json.dumps(VERDICT_JSON_SCHEMA))
        message_file.unlink(missing_ok=True)
        return schema_file, message_file

    def review_raw_answer(self, job, result):
        """Verdict from ``--output-last-message``; else the stream's last message.

        Whatever comes back is still validated by ``parse_review_verdict``: a
        schema violation or unreadable text ends up as ``unclear``.
        """
        try:
            text = (self._review_dir(job) / 'last-message.json').read_text(encoding='utf-8', errors='replace').strip()
        except OSError:
            text = ''
        return text or (result.get('result_text') or '')

    # -- environment ----------------------------------------------------- #
    def build_env(self, job, pr_body_file, *, auth_mode=ClaudeQueueJobAuthMode.API_KEY,
                  timeout=DEFAULT_TIMEOUT_SECONDS):
        """Child env with exactly the job user's key (or the host-wide one).

        ``auth_mode`` is irrelevant (OpenAI is API-key only) and accepted for
        the shared signature. ``codex exec`` reads ``CODEX_API_KEY``; the same
        key is also set as ``OPENAI_API_KEY`` for tools the run starts. A
        dedicated ``CODEX_HOME`` keeps a host ``auth.json`` from overriding it.
        """
        env = dict(os.environ, CLAUDE_QUEUE_JOB_ID=str(job.pk))
        if pr_body_file:
            env['PR_BODY_FILE'] = str(pr_body_file)
        for name in FOREIGN_ENV_VARS:
            env.pop(name, None)

        credential = resolve_openai_credential(job.auth_user)
        env['CODEX_API_KEY'] = credential.value
        env['OPENAI_API_KEY'] = credential.value
        env['CODEX_HOME'] = str(self._codex_home())
        self._set_credential_source(job, credential.source)
        return env

    @staticmethod
    def _codex_home():
        configured = (getattr(settings, 'CODEX_HOME', '') or '').strip()
        home = Path(configured) if configured else Path(settings.REPO_BASE_DIR) / '.codex-home'
        home.mkdir(parents=True, exist_ok=True)
        return home

    @staticmethod
    def _set_credential_source(job, source):
        if job.auth_credential_source == source:
            return
        job.auth_credential_source = source
        job.save(update_fields=['auth_credential_source'])

    # -- checkout -------------------------------------------------------- #
    def prepare_checkout(self, repo_dir, review=False):
        """Derive ``AGENTS.md`` from ``CLAUDE.md`` as a symlink, kept out of git.

        Codex reads ``AGENTS.md``, not ``CLAUDE.md``; the symlink keeps
        ``CLAUDE.md`` the single source. It is listed in ``.git/info/exclude``
        (local, never committed) so the worker's ``git add -A`` rescue commit
        cannot put it into the PR. A tracked or hand-written ``AGENTS.md`` is
        left alone.
        """
        repo = Path(repo_dir)
        source = repo / 'CLAUDE.md'
        target = repo / 'AGENTS.md'
        if not source.is_file() or (target.exists() or target.is_symlink()):
            return
        target.symlink_to('CLAUDE.md')
        exclude = repo / '.git' / 'info' / 'exclude'
        try:
            exclude.parent.mkdir(parents=True, exist_ok=True)
            current = exclude.read_text(encoding='utf-8', errors='replace') if exclude.exists() else ''
            if '/AGENTS.md' not in current.splitlines():
                with exclude.open('a') as fh:
                    fh.write(('' if current.endswith('\n') or not current else '\n') + '/AGENTS.md\n')
        except OSError:
            pass

    # -- error classification -------------------------------------------- #
    @staticmethod
    def _haystack(result):
        return f"{result.get('result_text', '')}\n{result.get('stderr', '')}".lower()

    @staticmethod
    def _errored(result):
        return bool(result.get('is_error') or result.get('returncode', 0) != 0)

    def _is_quota_exhausted(self, result):
        return self._errored(result) and any(m in self._haystack(result) for m in QUOTA_MARKERS)

    def is_limit_error(self, result):
        if not self._errored(result) or self._is_quota_exhausted(result):
            return False
        text = self._haystack(result)
        return any(m in text for m in LIMIT_MARKERS)

    def is_auth_error(self, result):
        """Broken key, or an empty balance (no backoff can fix either)."""
        if not self._errored(result):
            return False
        if self._is_quota_exhausted(result):
            return True
        text = self._haystack(result)
        return any(m in text for m in AUTH_ERROR_MARKERS)

    def parse_limit_reset(self, result):
        """Reset time from a *relative* hint ("try again in 6m0s"), else ``None``."""
        match = _RELATIVE_WAIT.search(f"{result.get('result_text', '')}\n{result.get('stderr', '')}")
        if not match:
            return None
        parts = _DURATION_PART.findall(match.group(1))
        if not parts:
            return None
        seconds = sum(float(n) * _unit_seconds(u) for n, u in parts)
        return timezone.now() + timedelta(seconds=seconds)

    def auth_error_message(self, result, job=None):
        detail = (result.get('result_text') or result.get('stderr') or '').strip()
        if self._is_quota_exhausted(result):
            base = (
                "OpenAI-Guthaben/Kontingent aufgebraucht (insufficient_quota) – "
                "das ist kein temporäres Limit. Guthaben im OpenAI-Konto aufladen."
            )
        elif job is not None and job.auth_credential_source == ClaudeCredentialSource.USER:
            owner = job.auth_user.name if job.auth_user else 'der Benutzer'
            base = (
                f"OpenAI-Authentifizierung fehlgeschlagen: der persönliche API-Key "
                f"von {owner} ist ungültig. Key unter „User Settings“ erneuern."
            )
        else:
            base = (
                "OpenAI-Authentifizierung fehlgeschlagen (API-Key ungültig). "
                "OPENAI_API_KEY auf dem Host prüfen."
            )
        return f"{base}\n\n{detail}".strip() if detail else base

    # -- stream parsing -------------------------------------------------- #
    def parse_stream(self, job, lines, tools_in_flight=None):
        """Parse ``codex exec --json`` JSONL into the shared result dict.

        ``saw_result`` means a terminal turn event (``turn.completed`` or
        ``turn.failed``) arrived. An ``error`` event only fails the run if no
        ``turn.completed`` follows it (the CLI emits transient reconnect
        errors).
        """
        if tools_in_flight is None:
            tools_in_flight = set()
        result = {
            'session_id': None,
            'num_turns': None,
            'total_cost_usd': None,
            'is_error': False,
            'result_text': '',
            'saw_result': False,
        }
        turns = 0
        usage = {'input_tokens': 0, 'cached_input_tokens': 0, 'output_tokens': 0}
        saw_usage = False
        last_message = ''
        error_text = ''
        failed = False

        for raw in lines:
            raw = (raw or '').strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            etype = event.get('type')
            if etype == 'thread.started':
                result['session_id'] = event.get('thread_id')
                job.session_id = result['session_id']
                save_progress(job, 'Session started', extra_fields=['session_id'])
            elif etype in ('item.started', 'item.updated', 'item.completed'):
                item = event.get('item') or {}
                self._track_item(etype, item, tools_in_flight)
                if item.get('type') == 'agent_message' and etype == 'item.completed':
                    last_message = item.get('text') or last_message
                step = self._describe_item(etype, item)
                if step:
                    save_progress(job, step)
            elif etype == 'turn.completed':
                turns += 1
                result['saw_result'] = True
                error_text, failed = '', False
                u = event.get('usage') or {}
                for key in usage:
                    usage[key] += int(u.get(key) or 0)
                saw_usage = saw_usage or bool(u)
            elif etype == 'turn.failed':
                result['saw_result'] = True
                failed = True
                error_text = self._error_message(event.get('error')) or error_text or 'Turn failed'
            elif etype == 'error':
                error_text = self._error_message(event) or error_text

        result['is_error'] = bool(failed or error_text)
        result['result_text'] = error_text if result['is_error'] else last_message
        if turns:
            result['num_turns'] = turns
            job.num_turns = turns
        fields = ['num_turns', 'session_id']
        if saw_usage:
            job.input_tokens = usage['input_tokens']
            job.cached_input_tokens = usage['cached_input_tokens']
            job.output_tokens = usage['output_tokens']
            fields += ['input_tokens', 'cached_input_tokens', 'output_tokens']
        if result['saw_result'] or result['is_error']:
            save_progress(
                job, (result['result_text'] or 'Completed').strip(), extra_fields=fields,
            )
        return result

    @staticmethod
    def _error_message(payload):
        if isinstance(payload, dict):
            return str(payload.get('message') or payload.get('error') or '').strip()
        return str(payload or '').strip()

    @staticmethod
    def _track_item(etype, item, in_flight):
        item_id = item.get('id')
        if not item_id or item.get('type') not in TOOL_ITEM_TYPES:
            return
        if etype == 'item.completed':
            in_flight.discard(item_id)
        elif etype == 'item.started':
            in_flight.add(item_id)

    def _track_tool_calls(self, event, in_flight):
        """Worker hook: keep ``in_flight`` in step with one Codex item event."""
        self._track_item(event.get('type'), event.get('item') or {}, in_flight)

    @staticmethod
    def _describe_item(etype, item):
        """A short "current step" line for an item event, or ``None``."""
        itype = item.get('type')
        if itype == 'command_execution' and etype == 'item.started':
            return f"command: {item.get('command') or ''}".strip().rstrip(':')[:2000]
        if itype == 'file_change' and etype == 'item.completed':
            paths = ', '.join(
                str(c.get('path')) for c in item.get('changes') or [] if isinstance(c, dict)
            )
            return f"file_change: {paths}".strip().rstrip(':')[:2000]
        if itype == 'mcp_tool_call' and etype == 'item.started':
            return f"{item.get('server') or 'mcp'}: {item.get('tool') or ''}".strip()[:2000]
        if itype == 'agent_message' and etype == 'item.completed':
            text = (item.get('text') or '').strip()
            if text:
                return text.splitlines()[0][:2000]
        return None
