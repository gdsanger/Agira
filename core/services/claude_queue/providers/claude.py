"""Claude Code provider: the CLI-specific half of the queue worker.

Encapsulates the command line, child environment and credentials, trust
settings, stream-json parsing, limit/auth markers and the model-slug mapping
for ``claude -p``. Behaviour is identical to the code that used to live in
``run_claude_worker``; only its home changed (see ``providers.base``).
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone as datetime_timezone
from pathlib import Path

from django.conf import settings

from core.models import ClaudeCredentialSource, ClaudeQueueJobAuthMode, claude_cli_model_id
from core.services.claude_queue.credentials import (
    ALL_AUTH_ENV_VARS,
    resolve_claude_credential,
)
from core.services.claude_queue.providers.base import AgentProvider, save_progress

# Fallback wall-clock budget (seconds) when ``build_env`` is called without one.
DEFAULT_TIMEOUT_SECONDS = 120 * 60

# Headless runs must stay strictly in the foreground. Claude Code can park a
# long command (typically a full test run) in a background task, or schedule a
# wakeup/cron, and end its turn to "pick it up later" — but in ``-p`` mode the
# process then exits and nobody is left listening, so the test result is lost.
# These variables switch that machinery off for the child process.
FOREGROUND_ONLY_ENV = {
    'CLAUDE_CODE_DISABLE_BACKGROUND_TASKS': '1',
    'CLAUDE_CODE_DISABLE_CRON': '1',
}

# Substrings (checked case-insensitively across the CLI's result text + stderr)
# that mark a Max/Pro *subscription usage limit* — the reactive signal the
# worker parks on. Distinct from a plain API error: a limit means "wait for the
# rollover / fall back to the API key", not "this run is broken".
LIMIT_MARKERS = (
    'usage limit reached',
    'usage limit',
    'rate limit',
    'rate_limit',
    'ratelimit',
    'too many requests',
    '"status":429',
    'status code 429',
    ' 429 ',
    'quota',
    '5-hour limit',
    '5 hour limit',
    'weekly limit',
    'limit reached',
    'limit exceeded',
    'nutzungslimit',
    'kontingent',
)

# Substrings that mark a broken/expired credential rather than a usage limit.
# These must fail the job with a clear message (not park it, not silently
# retry): a bad token never fixes itself by waiting.
AUTH_ERROR_MARKERS = (
    'oauth token has expired',
    'oauth token expired',
    'token has expired',
    'invalid api key',
    'invalid_api_key',
    'invalid bearer token',
    'authentication_error',
    'authentication error',
    'unauthorized',
    '401',
    'please run /login',
    'please run `claude login`',
    'run claude login',
    'no credentials found',
    'not logged in',
)

# Tools Claude may use in the headless run: read/edit files, write the
# PR_BODY_FILE (which lives outside the checkout, so Edit's "must already
# exist with matching content" semantics don't fit), and drive git.
ALLOWED_TOOLS = 'Read,Edit,Write,Bash(git*)'

# A review run only reads: files and read-only git queries. Anything that
# writes, commits or pushes is denied explicitly on top of not being allowed.
REVIEW_ALLOWED_TOOLS = [
    'Read', 'Grep', 'Glob',
    'Bash(git diff*)', 'Bash(git log*)', 'Bash(git show*)',
    'Bash(git status*)', 'Bash(git blame*)', 'Bash(git ls-files*)',
]
REVIEW_DENIED_TOOLS = [
    'Edit', 'Write', 'NotebookEdit',
    'Bash(git push*)', 'Bash(git commit*)', 'Bash(git checkout*)',
    'Bash(git reset*)', 'Bash(git add*)', 'Bash(gh*)',
]


class ClaudeProvider(AgentProvider):
    name = 'claude'
    allowed_tools = ALLOWED_TOOLS

    def build_args(self, job):
        """Assemble the headless Claude Code command line.

        The prompt is deliberately *not* part of argv (size limit, see
        ``_run_cli``); ``-p`` without a value makes the CLI read stdin.

        The job's model is a stored slug (``opus-5``), not something the CLI
        understands — it is translated to a concrete ``--model`` identifier
        here (#1082).
        """
        model = self.model_id(job.model or job.item.suggested_model)
        if job.is_review:
            # Read-only: no --dangerously-skip-permissions; the checkout's
            # settings allow only reading and deny writes/commits/pushes.
            return [
                settings.CLAUDE_CLI_BIN,
                '-p',
                '--model', model,
                '--output-format', 'stream-json',
                '--verbose',
                '--allowedTools', ','.join(REVIEW_ALLOWED_TOOLS),
                '--disallowedTools', ','.join(REVIEW_DENIED_TOOLS),
            ]
        return [
            settings.CLAUDE_CLI_BIN,
            '-p',
            '--model', model,
            '--output-format', 'stream-json',
            '--verbose',
            '--dangerously-skip-permissions',
        ]

    def model_id(self, slug):
        return claude_cli_model_id(slug)

    def build_env(self, job, pr_body_file, *, auth_mode=ClaudeQueueJobAuthMode.OAUTH,
                  timeout=DEFAULT_TIMEOUT_SECONDS):
        """Build the child environment for one Claude run, per ``auth_mode``.

        The CLI's credential precedence is *process-local*: inside a single
        process it prefers ``ANTHROPIC_API_KEY`` whenever it sees one. So both
        auth-carrying variables are stripped from the inherited environment
        first, and exactly the one matching ``auth_mode`` is set. This is what
        guarantees an OAuth run never silently spends the API key even when the
        key is exported globally on the host.

        Which secret that is comes from ``job.auth_user`` (#1083) — the run
        goes on *that* user's subscription or API account. Handing it over via
        the environment rather than a CLI flag is also the safer channel: argv
        is visible to every process via ``ps``, the environment is not.

        Background tasks and cron/wakeups are disabled (``FOREGROUND_ONLY_ENV``).
        With backgrounding off, a long command blocks in the foreground, so a
        single Bash call may use the job's whole wall-clock budget instead of
        the CLI's 2/10-minute defaults (which would otherwise kill a long test
        run). The idle watchdog is paused meanwhile (see ``_iter_events``).
        """
        bash_timeout_ms = str(timeout * 1000)
        env = dict(
            os.environ,
            CLAUDE_QUEUE_JOB_ID=str(job.pk),
            BASH_DEFAULT_TIMEOUT_MS=bash_timeout_ms,
            BASH_MAX_TIMEOUT_MS=bash_timeout_ms,
            **FOREGROUND_ONLY_ENV,
        )
        if pr_body_file:
            env['PR_BODY_FILE'] = str(pr_body_file)
        # Start from a clean slate so nothing inherited decides the auth for us.
        for name in ALL_AUTH_ENV_VARS:
            env.pop(name, None)

        credential = resolve_claude_credential(job.auth_user, auth_mode)
        if credential.value:
            env[credential.env_var] = credential.value
        self._set_credential_source(job, credential.source)
        return env

    @staticmethod
    def _set_credential_source(job, source):
        """Record which credential the current attempt actually used."""
        if job.auth_credential_source == source:
            return
        job.auth_credential_source = source
        job.save(update_fields=['auth_credential_source'])

    def prepare_checkout(self, repo_dir, review=False):
        """Write the Claude whitelist + trust flag into the *checkout*.

        These must live in the working checkout, not the app directory, so the
        headless run does not prompt for tool permission or project trust. A
        review run gets the read-only tool set instead.
        """
        allow = REVIEW_ALLOWED_TOOLS if review else None
        deny = REVIEW_DENIED_TOOLS if review else None
        claude_dir = Path(repo_dir) / '.claude'
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_file = claude_dir / 'settings.local.json'
        payload = {
            'hasTrustDialogAccepted': True,
            'permissions': {
                'allow': allow or ['Read', 'Edit', 'Write', 'Bash(git*)'],
            },
        }
        if deny:
            payload['permissions']['deny'] = deny
        settings_file.write_text(json.dumps(payload, indent=2))

    # -- error classification ------------------------------------------- #
    @staticmethod
    def _match_markers(result, markers):
        """True if any marker appears in the run's result text or stderr."""
        haystack = (
            f"{result.get('result_text', '')}\n{result.get('stderr', '')}"
        ).lower()
        return any(marker in haystack for marker in markers)

    def is_limit_error(self, result):
        """True if an *errored* run looks like a subscription usage-limit hit.

        Gated on the run actually erroring (``is_error`` or a non-zero exit) so a
        successful run that merely mentions "quota" in its summary is not
        misread as a limit.
        """
        errored = result.get('is_error') or result.get('returncode', 0) != 0
        return bool(errored) and self._match_markers(result, LIMIT_MARKERS)

    def is_auth_error(self, result):
        """True if an errored run looks like a broken/expired credential."""
        errored = result.get('is_error') or result.get('returncode', 0) != 0
        return bool(errored) and self._match_markers(result, AUTH_ERROR_MARKERS)

    def auth_error_message(self, result, job=None):
        """An actionable failure message for a credential problem.

        Points at the credential the run actually used: a personal one is fixed
        by its owner in the user profile, a host-wide one by the administrator.
        """
        detail = (result.get('result_text') or result.get('stderr') or '').strip()
        if job is not None and job.auth_credential_source == ClaudeCredentialSource.USER:
            owner = job.auth_user.name if job.auth_user else 'der Benutzer'
            base = (
                f"Claude-Authentifizierung fehlgeschlagen: das persönliche Credential "
                f"von {owner} ist abgelaufen oder ungültig. Neuen Token per "
                f"`claude setup-token` erzeugen bzw. den API-Key erneuern und unter "
                f"„User Settings“ hinterlegen."
            )
        else:
            base = (
                "Claude-Authentifizierung fehlgeschlagen (Token/Key abgelaufen oder "
                "ungültig). OAuth-Token per `claude setup-token` erneuern bzw. "
                "CLAUDE_CODE_OAUTH_TOKEN/ANTHROPIC_API_KEY prüfen."
            )
        return f"{base}\n\n{detail}".strip() if detail else base

    def parse_limit_reset(self, result):
        """Best-effort parse of a quota reset time from the CLI output.

        Recognises the ``…limit reached|<unix_epoch>`` form the CLI emits, plus
        a looser ``reset/retry … <epoch>`` fallback. Returns an aware datetime
        or ``None`` when nothing parseable is present (the caller then applies a
        default backoff).
        """
        text = f"{result.get('result_text', '')}\n{result.get('stderr', '')}"
        match = re.search(r'\|\s*(\d{10,13})\b', text)
        if not match:
            match = re.search(
                r'(?:reset|retry|available)[^0-9]{0,24}(\d{10,13})\b', text, re.I,
            )
        if not match:
            return None
        ts = int(match.group(1))
        if ts > 10_000_000_000:  # value is in milliseconds
            ts //= 1000
        try:
            return datetime.fromtimestamp(ts, tz=datetime_timezone.utc)
        except (ValueError, OSError, OverflowError):
            return None

    # -- stream parsing ------------------------------------------------- #
    def parse_stream(self, job, lines, tools_in_flight=None):
        """Parse Claude's stream-json events, updating ``job`` as they arrive.

        ``lines`` is any iterable of raw JSON lines (so it is unit-testable with
        synthetic input). Returns the accumulated result dict.
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

        for raw in lines:
            raw = (raw or '').strip()
            if not raw:
                continue
            try:
                event = json.loads(raw)
            except json.JSONDecodeError:
                # Known stdout bug can interleave non-JSON noise — skip it.
                continue

            etype = event.get('type')
            if etype == 'system' and event.get('subtype') == 'init':
                result['session_id'] = event.get('session_id')
                job.session_id = result['session_id']
                mcp = event.get('mcp_servers') or []
                save_progress(
                    job,
                    f"Session started ({len(mcp)} MCP server(s))",
                    extra_fields=['session_id'],
                )
            elif etype == 'assistant':
                self._track_tool_calls(event, tools_in_flight)
                step = self._describe_assistant(event)
                if step:
                    save_progress(job, step)
            elif etype == 'user':
                self._track_tool_calls(event, tools_in_flight)
            elif etype == 'result':
                result['saw_result'] = True
                result['is_error'] = bool(event.get('is_error'))
                result['num_turns'] = event.get('num_turns')
                result['total_cost_usd'] = event.get('total_cost_usd')
                result['result_text'] = event.get('result') or ''

                job.num_turns = result['num_turns']
                if result['total_cost_usd'] is not None:
                    job.total_cost_usd = result['total_cost_usd']
                if event.get('session_id'):
                    job.session_id = event['session_id']
                save_progress(
                    job,
                    (result['result_text'] or 'Completed').strip(),
                    extra_fields=['num_turns', 'total_cost_usd', 'session_id'],
                )

        return result

    @staticmethod
    def _track_tool_calls(event, in_flight):
        """Keep ``in_flight`` in step with tool_use/tool_result blocks."""
        for block in (event.get('message') or {}).get('content') or []:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use' and block.get('id'):
                in_flight.add(block['id'])
            elif block.get('type') == 'tool_result':
                in_flight.discard(block.get('tool_use_id'))

    @staticmethod
    def _describe_assistant(event):
        """Turn an assistant event into a short 'current step' line."""
        message = event.get('message') or {}
        content = message.get('content') or []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get('type') == 'tool_use':
                name = block.get('name', 'tool')
                inp = block.get('input') or {}
                target = (
                    inp.get('file_path')
                    or inp.get('command')
                    or inp.get('path')
                    or ''
                )
                return f"{name}: {target}".strip().rstrip(':')[:2000]
        for block in content:
            if isinstance(block, dict) and block.get('type') == 'text':
                text = (block.get('text') or '').strip()
                if text:
                    return text.splitlines()[0][:2000]
        return None

