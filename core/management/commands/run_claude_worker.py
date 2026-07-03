"""
Django management command: Claude Code queue worker.

This is the *engine* of the Claude queue. It claims queued ``ClaudeQueueJob``
rows and runs them end-to-end:

1. Prepare a per-project repo checkout under ``settings.REPO_BASE_DIR`` (never
   the app directory — Claude edits there, the process runs from the app tree).
2. Open a **draft PR up front**: branch ``fix/{item-slug}`` off ``main``, an
   empty commit, push, then a draft PR via the existing ``GitHubService`` infra.
   The PR reference (number/url/github-id) is written to the job and to an
   ``ExternalIssueMapping`` (Kind=PR) *before* Claude runs, so it is
   deterministic regardless of what Claude reports.
3. Run Claude Code headless (``--output-format stream-json``) in the checkout,
   parsing the event stream line-by-line to advance ``progress_text`` live and
   to persist ``session_id`` / ``num_turns`` / ``total_cost_usd`` from the final
   ``result`` event.

The #831 frame — claiming, one-running-job-per-project concurrency, timeout and
crash recovery — is unchanged; this command fills the seam that used to run a
placeholder ``--cli-command``.

Concurrency rules enforced here:

* At most **one running job per project** at any time. The row lock alone does
  not guarantee this — two queued jobs of the same project are both unlocked,
  so ``skip_locked`` would happily hand them to two workers. The selection
  predicate therefore (a) excludes projects that already have a running job and
  (b) considers only the *oldest* queued job of each project as a candidate, so
  a second worker finds no eligible row for a project whose head-of-line job is
  already locked.
* Jobs of *different* projects may run in parallel (across multiple worker
  processes / hosts).

Run modes::

    # cron: claim and process a single job, then exit
    python manage.py run_claude_worker --once

    # daemon: loop forever, polling for work
    python manage.py run_claude_worker --interval 5
"""

import json
import logging
import os
import select
import signal
import socket
import subprocess
import tempfile
import time
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.text import slugify

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobStatus,
    ItemStatus,
)

logger = logging.getLogger(__name__)

# Default wall-clock budget for a single Claude invocation (30 minutes). A hung
# job must not block its project lane forever.
DEFAULT_TIMEOUT_SECONDS = 30 * 60

# Watchdog: if no stream event arrives for this long, SIGINT the Claude process.
# A known stdout-buffering bug means the stream can fall silent while Claude is
# still alive, so "done" is decided by process exit + result event — not by
# stream silence — but a truly stuck run still needs a nudge.
DEFAULT_IDLE_TIMEOUT_SECONDS = 5 * 60

# After a watchdog SIGINT, give Claude this long to emit its final result event
# and exit cleanly before escalating to SIGKILL.
INTERRUPT_GRACE_SECONDS = 30

# Default poll interval for daemon mode.
DEFAULT_INTERVAL_SECONDS = 5

# A running job whose start is older than ``timeout + STALE_BUFFER`` is treated
# as orphaned during crash recovery: a live worker would have enforced the
# timeout itself, so if the job is still "running" its supervisor is gone.
STALE_BUFFER_SECONDS = 60

# Tools Claude may use in the headless run: read/edit files, write the
# PR_BODY_FILE (which lives outside the checkout, so Edit's "must already
# exist with matching content" semantics don't fit), and drive git.
ALLOWED_TOOLS = 'Read,Edit,Write,Bash(git*)'

# Fixed PR body sections Claude must write into PR_BODY_FILE. Literal headings
# so the resulting PR bodies are uniform and cleanly chunkable for the
# Weaviate RAG index.
PR_BODY_FILE_INSTRUCTIONS = (
    "Schließe deine Arbeit ab, indem du einen PR-Text in die Datei unter "
    "`$PR_BODY_FILE` schreibst. Verwende GENAU die vorgegebene "
    "Markdown-Struktur (Überschriften wörtlich: `## Zusammenfassung`, "
    "`## Änderungen`, `## Warum / Entscheidungen`, `## Test-Hinweise`; keine "
    "zusätzlichen H2). Nur inhaltlicher PR-Text — kein Prozess-Geplauder, "
    "keine Commit-Hashes, kein „Committed as\". Nenne unter „## Warum / "
    "Entscheidungen\" ausdrücklich auch bewusst verworfene Alternativen im "
    "Format „nicht X, weil Y\"."
)


class Command(BaseCommand):
    help = (
        'Claim and run queued Claude Code jobs. Enforces at-most-one running '
        'job per project. Runnable as a cron (--once) or a loop daemon.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--once',
            action='store_true',
            help='Claim and process a single job (or none), then exit. Ideal for cron.',
        )
        parser.add_argument(
            '--interval',
            type=float,
            default=DEFAULT_INTERVAL_SECONDS,
            help=f'Daemon poll interval in seconds when idle (default: {DEFAULT_INTERVAL_SECONDS}).',
        )
        parser.add_argument(
            '--timeout',
            type=int,
            default=DEFAULT_TIMEOUT_SECONDS,
            help=f'Per-job wall-clock timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS}).',
        )
        parser.add_argument(
            '--idle-timeout',
            type=int,
            default=DEFAULT_IDLE_TIMEOUT_SECONDS,
            help=f'Seconds without a stream event before the watchdog interrupts '
                 f'the Claude process (default: {DEFAULT_IDLE_TIMEOUT_SECONDS}).',
        )
        parser.add_argument(
            '--skip-recovery',
            action='store_true',
            help='Do not run crash recovery of orphaned running jobs at startup.',
        )

    def handle(self, *args, **options):
        self._stop = False
        once = options['once']
        interval = options['interval']
        timeout = options['timeout']
        idle_timeout = options['idle_timeout']

        self.stdout.write(self.style.SUCCESS(
            f"Claude worker starting on {socket.gethostname()} (pid {os.getpid()})"
        ))

        if not options['skip_recovery']:
            self.recover_orphans(timeout)

        if once:
            job = self.claim_next_job()
            if job is None:
                self.stdout.write("No eligible job to claim.")
            else:
                self.process_job(job, timeout, idle_timeout)
            return

        # Daemon mode: loop until a termination signal arrives.
        self._install_signal_handlers()
        self.stdout.write(f"Entering daemon loop (poll interval {interval}s). Ctrl-C to stop.")
        while not self._stop:
            job = self.claim_next_job()
            if job is None:
                # Nothing claimable right now — sleep, but stay responsive to signals.
                self._interruptible_sleep(interval)
                continue
            self.process_job(job, timeout, idle_timeout)
        self.stdout.write(self.style.SUCCESS("Claude worker stopped."))

    # ------------------------------------------------------------------ #
    # Claiming
    # ------------------------------------------------------------------ #
    def claim_next_job(self):
        """Atomically claim the next eligible job and mark it ``running``.

        Eligible = the oldest ``queued`` job of a project that currently has no
        ``running`` job. Returns the claimed job (already committed as running)
        or ``None`` if nothing is claimable.
        """
        with transaction.atomic():
            # Projects that already have a running job are off-limits.
            busy_projects = ClaudeQueueJob.objects.filter(
                status=ClaudeQueueJobStatus.RUNNING,
            ).values_list('project_id', flat=True)

            # Restrict candidates to the head-of-line (oldest) queued job of each
            # project. Without this, skip_locked could hand a second worker the
            # *second*-oldest queued job of a project whose oldest is locked,
            # breaking the one-per-project rule.
            older = ClaudeQueueJob.objects.filter(
                project_id=OuterRef('project_id'),
                status=ClaudeQueueJobStatus.QUEUED,
            ).filter(
                Q(created_at__lt=OuterRef('created_at'))
                | Q(created_at=OuterRef('created_at'), pk__lt=OuterRef('pk'))
            )

            candidates = (
                ClaudeQueueJob.objects
                .filter(status=ClaudeQueueJobStatus.QUEUED)
                .exclude(project_id__in=busy_projects)
                .annotate(_has_older=Exists(older))
                .filter(_has_older=False)
                .order_by('created_at', 'pk')
            )
            # Row-lock the candidate so peers skip it. skip_locked is what makes
            # concurrent workers pick disjoint rows; fall back gracefully on
            # backends (e.g. sqlite in tests) that lack these features.
            if connection.features.has_select_for_update:
                lock_kwargs = {}
                if connection.features.has_select_for_update_skip_locked:
                    lock_kwargs['skip_locked'] = True
                candidates = candidates.select_for_update(**lock_kwargs)

            job = candidates.first()

            if job is None:
                return None

            # Take ownership *before* the long-running part, and commit it with
            # this transaction so the row is visibly ``running`` to peers.
            job.worker_host = socket.gethostname()
            job.worker_pid = os.getpid()
            job.transition_to(ClaudeQueueJobStatus.RUNNING)

        self.stdout.write(self.style.SUCCESS(
            f"Claimed job #{job.pk} (project {job.project_id}, item {job.item_id})"
        ))
        return job

    # ------------------------------------------------------------------ #
    # Processing
    # ------------------------------------------------------------------ #
    def process_job(self, job, timeout, idle_timeout=DEFAULT_IDLE_TIMEOUT_SECONDS):
        """Run a claimed job to a terminal state (done/failed).

        Prepares the checkout, opens the draft PR up front, runs Claude under a
        wall-clock timeout + idle watchdog, and persists the result fields. Any
        failure (setup, timeout, non-zero exit, ``is_error`` result) drives the
        job to ``failed`` with diagnostics and releases the item so it does not
        starve in ``Working``.

        Claude is asked to write the PR body text into ``PR_BODY_FILE`` — a file
        outside the checkout (so ``reset --hard``/``clean -fd`` can't touch it
        and Claude can't accidentally commit it). It is created empty up front
        and removed again once the job reaches a terminal state.
        """
        pr_body_file = self._pr_body_file_path(job)
        self._init_pr_body_file(pr_body_file)
        try:
            self._process_job_inner(job, timeout, idle_timeout, pr_body_file)
        finally:
            self._cleanup_pr_body_file(pr_body_file)

    def _process_job_inner(self, job, timeout, idle_timeout, pr_body_file):
        try:
            repo_dir = self._prepare_checkout(job)
            branch = self._create_branch_and_pr(job, repo_dir)
            result = self._run_cli(job, repo_dir, timeout, idle_timeout, pr_body_file)
        except subprocess.TimeoutExpired:
            error = f"Job exceeded the {timeout}s timeout and was terminated."
            self._fail_job(job, error=error)
            self._update_pr_body(job, error=error)
            self.stdout.write(self.style.ERROR(f"Job #{job.pk} timed out after {timeout}s"))
            return
        except Exception as exc:  # noqa: BLE001 — any setup/launch failure is a job failure
            logger.exception("Failed to run Claude for job #%s", job.pk)
            error = f"Worker error: {exc}"
            self._fail_job(job, error=error)
            self._update_pr_body(job, error=error)
            self.stdout.write(self.style.ERROR(f"Job #{job.pk} failed: {exc}"))
            return

        # Push whatever Claude committed onto the branch. Best-effort: Claude may
        # have pushed already, or produced no commit — neither is fatal here.
        self._push_branch(repo_dir, branch)

        if result.get('is_error') or result.get('returncode', 0) != 0:
            detail = (
                result.get('result_text')
                or result.get('stderr')
                or f"Claude exited with status {result.get('returncode')}."
            ).strip()
            error = detail or "Claude reported an error."
            self._fail_job(job, error=error)
            self._update_pr_body(job, error=error)
            self.stdout.write(self.style.ERROR(f"Job #{job.pk} failed"))
            return

        if not result.get('saw_result'):
            # Process exited 0 but never emitted a result event — treat as a
            # failure so it is not silently marked done.
            error = "Claude exited without emitting a final result event."
            self._fail_job(job, error=error)
            self._update_pr_body(job, error=error)
            self.stdout.write(self.style.ERROR(f"Job #{job.pk} failed (no result event)"))
            return

        self._update_pr_body(
            job, summary=result.get('result_text'), pr_body_file=pr_body_file
        )
        job.transition_to(ClaudeQueueJobStatus.DONE)
        self.stdout.write(self.style.SUCCESS(f"Job #{job.pk} done"))

    # ------------------------------------------------------------------ #
    # Checkout preparation
    # ------------------------------------------------------------------ #
    def _prepare_checkout(self, job):
        """Ensure a clean checkout of the project's repo under REPO_BASE_DIR.

        Clones on first use, otherwise fetches and hard-resets to ``origin/main``
        so each job starts from a known-clean base. Returns the checkout path.
        The worker edits here, never in the app directory.
        """
        project = job.project
        repo = (project.github_repo or '').strip()
        if not repo:
            raise ValueError(
                f"Project '{project.name}' has no github_repo configured."
            )

        base = Path(settings.REPO_BASE_DIR)
        repo_dir = base / repo

        if (repo_dir / '.git').is_dir():
            self._git(['fetch', 'origin', '--prune'], cwd=str(repo_dir))
        else:
            base.mkdir(parents=True, exist_ok=True)
            clone_url = self._clone_url(project)
            # Never leak the token in stdout/logs.
            self.stdout.write(f"  Cloning {project.github_owner}/{repo} …")
            self._git(['clone', clone_url, str(repo_dir)], cwd=str(base))

        self._git(['checkout', 'main'], cwd=str(repo_dir))
        self._git(['reset', '--hard', 'origin/main'], cwd=str(repo_dir))
        self._git(['clean', '-fd'], cwd=str(repo_dir))
        self._write_trust_settings(repo_dir)
        return str(repo_dir)

    def _clone_url(self, project):
        """Build an authenticated https clone URL for the project's repo."""
        from core.models import GitHubConfiguration

        config = GitHubConfiguration.load()
        token = config.github_token
        owner = project.github_owner
        repo = project.github_repo
        host = 'github.com'
        if token:
            return f"https://x-access-token:{token}@{host}/{owner}/{repo}.git"
        return f"https://{host}/{owner}/{repo}.git"

    def _write_trust_settings(self, repo_dir):
        """Write the Claude whitelist + trust flag into the *checkout*.

        These must live in the working checkout, not the app directory, so the
        headless run does not prompt for tool permission or project trust.
        """
        claude_dir = Path(repo_dir) / '.claude'
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_file = claude_dir / 'settings.local.json'
        payload = {
            'hasTrustDialogAccepted': True,
            'permissions': {
                'allow': ['Read', 'Edit', 'Write', 'Bash(git*)'],
            },
        }
        settings_file.write_text(json.dumps(payload, indent=2))

    # ------------------------------------------------------------------ #
    # Branch + draft PR (the up-front trick)
    # ------------------------------------------------------------------ #
    def _create_branch_and_pr(self, job, repo_dir):
        """Create ``fix/{item-slug}`` off main, empty commit, push, draft PR.

        The PR is opened *before* Claude runs and its reference is written to the
        job + an ``ExternalIssueMapping`` (Kind=PR) immediately, so it stays
        deterministic regardless of what Claude does. Returns the branch name.
        """
        item = job.item
        branch = self._branch_name(item)

        self._git(['checkout', '-B', branch, 'origin/main'], cwd=repo_dir)
        self._git(
            ['commit', '--allow-empty', '-m',
             f"chore: start Claude work on item #{item.id}"],
            cwd=repo_dir,
        )
        self._git(
            ['push', '--force-with-lease', '-u', 'origin', branch],
            cwd=repo_dir,
        )

        job.branch_name = branch
        job.save(update_fields=['branch_name'])

        self._open_draft_pr(job, branch, repo_dir)
        return branch

    def _branch_name(self, item):
        """Deterministic, collision-free branch name for an item."""
        slug = slugify(item.title)[:50].strip('-')
        return f"fix/{slug}-{item.id}" if slug else f"fix/item-{item.id}"

    def _open_draft_pr(self, job, branch, repo_dir):
        """Open the draft PR and record it on the job + ExternalIssueMapping.

        Uses the existing ``GitHubService`` infra. On failure, falls back to
        ``gh pr list --head`` (e.g. the PR already exists from a re-run) so a
        transient API hiccup does not orphan the job.
        """
        from core.services.github.service import GitHubService

        mapping = None
        try:
            mapping = GitHubService().create_draft_pr_for_item(
                job.item,
                branch_name=branch,
                base='main',
                title=job.item.title,
                body=self._pr_body(job),
            )
        except Exception as exc:  # noqa: BLE001 — fall back to gh lookup
            logger.warning(
                "Draft PR API call failed for job #%s (%s); trying gh fallback",
                job.pk, exc,
            )
            mapping = self._pr_from_gh_fallback(job, branch, repo_dir)
            if mapping is None:
                raise

        job.pr_number = mapping.number
        job.pr_url = mapping.html_url
        job.save(update_fields=['pr_number', 'pr_url'])
        self.stdout.write(f"  Draft PR #{mapping.number}: {mapping.html_url}")

    def _pr_from_gh_fallback(self, job, branch, repo_dir):
        """Resolve an existing PR for ``branch`` via the ``gh`` CLI.

        Records an ``ExternalIssueMapping`` (Kind=PR) so the reference is stored
        through the same infra as the primary path. Returns the mapping or None.
        """
        from core.models import ExternalIssueKind, ExternalIssueMapping

        try:
            proc = subprocess.run(
                ['gh', 'pr', 'list', '--head', branch,
                 '--state', 'all', '--json', 'number,url,id', '--limit', '1'],
                cwd=repo_dir, capture_output=True, text=True, timeout=60,
            )
            if proc.returncode != 0:
                logger.warning("gh pr list failed: %s", proc.stderr.strip())
                return None
            entries = json.loads(proc.stdout or '[]')
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            logger.warning("gh fallback error for job #%s: %s", job.pk, exc)
            return None

        if not entries:
            return None

        entry = entries[0]
        # gh's `id` is the GraphQL node id (a string); ExternalIssueMapping needs
        # a numeric github_id, so derive a stable one from the PR number if the
        # numeric database id is unavailable.
        github_id = entry.get('id')
        if not isinstance(github_id, int):
            github_id = None
        mapping, _ = ExternalIssueMapping.objects.update_or_create(
            item=job.item,
            kind=ExternalIssueKind.PR,
            number=entry['number'],
            defaults={
                'github_id': github_id if github_id is not None
                else -entry['number'],
                'state': 'open',
                'html_url': entry['url'],
            },
        )
        return mapping

    def _pr_body(self, job):
        item = job.item
        return (
            f"Automated draft PR opened by the Claude queue worker for "
            f"Agira item #{item.id}.\n\n"
            f"Model: {job.get_model_display()}\n"
            f"Job: #{job.pk}"
        )

    def _update_pr_body(self, job, *, summary=None, error=None, pr_body_file=None):
        """Replace the draft PR body with Claude's structured PR text (or a failure note).

        Runs through ``GitHubService`` — the same infra that opened the PR — so
        there is no parallel gh path. Idempotent: always overwrites the body
        rather than appending, so re-runs don't duplicate content. Best-effort;
        a PR body update failure must not affect the job's own terminal status.
        The success body is what gets indexed into Weaviate as RAG context, so
        an empty/generic body here is a real loss, not just a readability nit.

        On success, prefers the fixed-structure text Claude wrote to
        ``pr_body_file``; falls back to the raw ``result_text`` summary when
        that file is missing or empty (e.g. an older/uncooperative run).
        """
        if not job.pr_number:
            return

        header = self._pr_body(job)
        if error is not None:
            body = f"{header}\n\n---\n\n**Run failed:** {error.strip()}"
        else:
            structured = self._read_pr_body_file(pr_body_file) if pr_body_file else None
            if structured:
                body = f"{header}\n\n---\n\n{structured}"
            else:
                text = (summary or '').strip() or '_No summary provided._'
                body = f"{header}\n\n---\n\n## Claude Summary\n\n{text}"

        try:
            from core.services.github.service import GitHubService

            GitHubService().update_pr_body(job.item, number=job.pr_number, body=body)
        except Exception as exc:  # noqa: BLE001 — best-effort, don't fail the job over this
            logger.warning("Failed to update PR #%s body for job #%s: %s", job.pr_number, job.pk, exc)

    # ------------------------------------------------------------------ #
    # PR_BODY_FILE lifecycle
    # ------------------------------------------------------------------ #
    def _pr_body_file_path(self, job):
        """Path for the per-job PR body file, outside any repo checkout."""
        return Path(tempfile.gettempdir()) / f"claude-pr-body-{job.pk}.md"

    def _init_pr_body_file(self, path):
        """Create an empty PR body file before the run so Claude can write to it."""
        try:
            path.write_text('')
        except OSError as exc:
            logger.warning("Could not create PR body file %s: %s", path, exc)

    def _read_pr_body_file(self, path):
        """Read the PR body file's stripped content, or ``None`` if missing/empty."""
        try:
            content = path.read_text().strip()
        except OSError:
            return None
        return content or None

    def _cleanup_pr_body_file(self, path):
        """Remove the PR body file after the run; missing file is not an error."""
        try:
            path.unlink()
        except OSError:
            pass

    def _push_branch(self, repo_dir, branch):
        """Push the branch after the Claude run (best-effort)."""
        try:
            self._git(['push', 'origin', branch], cwd=repo_dir)
        except Exception as exc:  # noqa: BLE001 — non-fatal; Claude may have pushed
            logger.warning("Post-run push of %s failed: %s", branch, exc)

    # ------------------------------------------------------------------ #
    # Claude Code invocation + stream parsing
    # ------------------------------------------------------------------ #
    def _run_cli(self, job, repo_dir, timeout, idle_timeout, pr_body_file):
        """Run Claude Code headless in ``repo_dir`` and parse its event stream.

        Returns a result dict with ``session_id``/``num_turns``/
        ``total_cost_usd``/``is_error``/``result_text``/``saw_result``/
        ``returncode``/``stderr``. Raises ``subprocess.TimeoutExpired`` when the
        wall-clock budget is exhausted.
        """
        args = self._build_claude_args(job)
        env = self._build_env(job, pr_body_file)

        proc = subprocess.Popen(
            args,
            cwd=repo_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        try:
            result = self._consume_stream(
                job, self._iter_events(proc, timeout, idle_timeout)
            )
        except subprocess.TimeoutExpired:
            self._kill(proc)
            raise

        result['stderr'] = proc.stderr.read() if proc.stderr else ''
        result['returncode'] = proc.wait()
        return result

    def _build_claude_args(self, job):
        """Assemble the headless Claude Code command line."""
        model = job.model or job.item.suggested_model or 'sonnet'
        return [
            settings.CLAUDE_CLI_BIN,
            '-p', self._build_prompt(job.item),
            '--model', model,
            '--output-format', 'stream-json',
            '--verbose',
            '--allowedTools', ALLOWED_TOOLS,
            '--permission-mode', 'acceptEdits',
        ]

    def _build_env(self, job, pr_body_file):
        env = dict(
            os.environ,
            CLAUDE_QUEUE_JOB_ID=str(job.pk),
            PR_BODY_FILE=str(pr_body_file),
        )
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', '') or os.environ.get(
            'ANTHROPIC_API_KEY', ''
        )
        if api_key:
            env['ANTHROPIC_API_KEY'] = api_key
        return env

    def _build_prompt(self, item):
        """Build the task prompt Claude works from."""
        parts = [f"# Task: {item.title}", '']
        if item.description:
            parts += [item.description, '']
        if item.solution_description:
            parts += ['## Expected solution', item.solution_description, '']
        parts.append(
            "Implement the change in this repository. Make focused edits and "
            "commit them to the current branch with git. Do not push."
        )
        parts += ['', PR_BODY_FILE_INSTRUCTIONS]
        return '\n'.join(parts)

    def _iter_events(self, proc, timeout, idle_timeout):
        """Yield stdout lines, enforcing the wall-clock budget + idle watchdog.

        On an idle window with no output, sends one SIGINT (the watchdog) and
        grants a short grace period for the final result event; a second idle
        window escalates to a timeout. "Done" is process EOF, never mere stream
        silence.
        """
        deadline = time.monotonic() + timeout
        interrupted = False
        stdout = proc.stdout

        while True:
            now = time.monotonic()
            if now >= deadline:
                raise subprocess.TimeoutExpired(proc.args, timeout)

            wait = min(idle_timeout, deadline - now)
            rlist, _, _ = select.select([stdout], [], [], max(0.1, wait))

            if rlist:
                line = stdout.readline()
                if line == '':  # EOF — process finished writing
                    break
                yield line
                continue

            # No output within the idle window.
            if proc.poll() is not None:
                break  # process already exited; drain done
            if not interrupted:
                logger.warning(
                    "No Claude event for %ss; sending SIGINT (watchdog).",
                    idle_timeout,
                )
                self._signal(proc, signal.SIGINT)
                interrupted = True
                deadline = min(deadline, time.monotonic() + INTERRUPT_GRACE_SECONDS)
            else:
                raise subprocess.TimeoutExpired(proc.args, timeout)

    def _consume_stream(self, job, lines):
        """Parse Claude's stream-json events, updating ``job`` as they arrive.

        ``lines`` is any iterable of raw JSON lines (so it is unit-testable with
        synthetic input). Returns the accumulated result dict.
        """
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
                self._save_progress(
                    job,
                    f"Session started ({len(mcp)} MCP server(s))",
                    extra_fields=['session_id'],
                )
            elif etype == 'assistant':
                step = self._describe_assistant(event)
                if step:
                    self._save_progress(job, step)
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
                self._save_progress(
                    job,
                    (result['result_text'] or 'Completed').strip(),
                    extra_fields=['num_turns', 'total_cost_usd', 'session_id'],
                )

        return result

    def _describe_assistant(self, event):
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

    def _save_progress(self, job, text, extra_fields=None):
        job.progress_text = (text or '')[:2000]
        fields = ['progress_text'] + (extra_fields or [])
        job.save(update_fields=fields)

    # ------------------------------------------------------------------ #
    # Subprocess helpers
    # ------------------------------------------------------------------ #
    def _git(self, args, cwd):
        """Run a git command, raising with captured stderr on failure."""
        proc = subprocess.run(
            ['git', *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed ({proc.returncode}): "
                f"{(proc.stderr or proc.stdout).strip()}"
            )
        return proc.stdout

    @staticmethod
    def _signal(proc, sig):
        try:
            proc.send_signal(sig)
        except ProcessLookupError:
            pass

    def _kill(self, proc):
        """Escalate to SIGKILL and reap the process."""
        self._signal(proc, signal.SIGKILL)
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass

    # ------------------------------------------------------------------ #
    # Failure / item release
    # ------------------------------------------------------------------ #
    def _fail_job(self, job, error):
        """Transition a running job to ``failed`` and release its item."""
        job.error_text = error
        try:
            job.transition_to(ClaudeQueueJobStatus.FAILED)
        except ValidationError:
            # Already terminal (e.g. cancelled meanwhile) — just persist the note.
            job.save(update_fields=['error_text'])
        self._release_item(job)

    def _release_item(self, job):
        """Don't let the item starve in ``Working`` after a failed job.

        Move it back to ``Backlog`` (the human-triage lane / "needs attention")
        so a person can pick it up again.
        """
        item = job.item
        if item.status == ItemStatus.WORKING:
            item.status = ItemStatus.BACKLOG
            item.save(update_fields=['status'])
            self.stdout.write(
                f"  Released item #{item.id} back to Backlog"
            )

    # ------------------------------------------------------------------ #
    # Crash recovery
    # ------------------------------------------------------------------ #
    def recover_orphans(self, timeout):
        """Fail running jobs whose supervising worker is gone.

        Runs once at startup. A ``running`` job is an orphan when its owning
        process on this host is dead, or when it has been running longer than
        its timeout could allow (its supervisor would otherwise have killed it),
        or when it carries no worker ownership at all.
        """
        running = ClaudeQueueJob.objects.filter(status=ClaudeQueueJobStatus.RUNNING)
        recovered = 0
        for job in running:
            reason = self._orphan_reason(job, timeout)
            if reason is None:
                continue
            self.stdout.write(self.style.WARNING(
                f"Recovering orphaned job #{job.pk}: {reason}"
            ))
            self._fail_job(job, error=f"Crash recovery: {reason}")
            recovered += 1
        if recovered:
            self.stdout.write(self.style.SUCCESS(
                f"Crash recovery: cleaned up {recovered} orphaned job(s)"
            ))

    def _orphan_reason(self, job, timeout):
        """Return a human reason if ``job`` is an orphan, else ``None``."""
        # 1) Authoritative check for jobs owned by a process on this host.
        if job.worker_host == socket.gethostname() and job.worker_pid:
            if not self._pid_alive(job.worker_pid):
                return "worker process no longer running"

        # 2) Anything running longer than its own timeout has lost its
        #    supervisor (a live worker enforces the timeout locally).
        if job.started_at is not None:
            age = (timezone.now() - job.started_at).total_seconds()
            if age > timeout + STALE_BUFFER_SECONDS:
                return f"running for {int(age)}s, exceeds timeout of {timeout}s"

        # 3) Running with no owner recorded — nobody is driving it.
        if not job.worker_pid:
            return "running with no worker owner recorded"

        return None

    @staticmethod
    def _pid_alive(pid):
        """Return True if a process with ``pid`` currently exists."""
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # Exists but owned by another user.
            return True
        except OSError:
            return False
        return True

    # ------------------------------------------------------------------ #
    # Daemon plumbing
    # ------------------------------------------------------------------ #
    def _install_signal_handlers(self):
        def _handler(signum, _frame):
            self.stdout.write(f"\nReceived signal {signum}, finishing up...")
            self._stop = True

        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, _handler)

    def _interruptible_sleep(self, seconds):
        """Sleep in short slices so a stop signal is honored promptly."""
        deadline = time.monotonic() + seconds
        while not self._stop and time.monotonic() < deadline:
            time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
