"""
Django management command: Claude Code queue worker.

This is the *engine* of the Claude queue. It claims queued ``ClaudeQueueJob``
rows and runs them end-to-end:

1. Prepare a per-project repo checkout under ``settings.REPO_BASE_DIR`` (never
   the app directory — Claude edits there, the process runs from the app tree).
2. Open a **PR up front**: branch ``fix/{item-slug}`` off the item's base, an
   empty commit, push, then a PR via the existing ``GitHubService`` infra. The
   PR reference (number/url/github-id) is written to the job and to an
   ``ExternalIssueMapping`` (Kind=PR) *before* Claude runs, so it is
   deterministic regardless of what Claude reports. The base is ``main`` and
   the PR a draft for a standalone item; for a sub-issue of an epic (#1076) it
   is the parent's epic branch and the PR is opened ready-for-review with
   squash auto-merge armed.
3. Run Claude Code headless (``--output-format stream-json``) in the checkout,
   parsing the event stream line-by-line to advance ``progress_text`` live and
   to persist ``session_id`` / ``num_turns`` / ``total_cost_usd`` from the final
   ``result`` event.

The #831 frame — claiming, one-running-job-per-repo concurrency, timeout and
crash recovery — is unchanged; this command fills the seam that used to run a
placeholder ``--cli-command``.

Concurrency rules enforced here:

* At most **one running job per repo** (identified by the project's
  ``github_owner``/``github_repo``, not its ``project_id``) at any time. Two
  projects that happen to point at the same GitHub repo share a checkout
  directory, so they must never run concurrently either — keying the lock on
  repo identity rather than project makes that safe automatically, with no
  extra pipeline model. The row lock alone does not guarantee the one-per-repo
  rule — two queued jobs of the same repo are both unlocked, so
  ``skip_locked`` would happily hand them to two workers. The selection
  predicate therefore (a) excludes repos that already have a running job and
  (b) considers only the *oldest* queued job of each repo as a candidate, so a
  second worker finds no eligible row for a repo whose head-of-line job is
  already locked.
* Jobs of *different* repos (in practice, different projects) may run in
  parallel (across multiple worker processes / hosts) — each project is
  effectively its own pipeline.

Run modes::

    # cron: claim and process a single job, then exit
    python manage.py run_claude_worker --once

    # daemon: loop forever, polling for work
    python manage.py run_claude_worker --interval 5
"""

import json
import logging
import os
import re
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone as datetime_timezone
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.text import slugify

from core.models import (
    ClaudeCredentialSource,
    ClaudeQueueJob,
    ClaudeQueueJobAuthMode,
    ClaudeQueueJobStatus,
    ItemStatus,
    claude_cli_model_id,
)
from core.services.claude_queue.branch import (
    DEFAULT_BASE_BRANCH,
    resolve_base_branch,
)
from core.services.claude_queue.credentials import (
    ALL_AUTH_ENV_VARS,
    MissingClaudeCredential,
    resolve_claude_credential,
)
from core.services.claude_queue.epic import can_start, sub_issue_position

logger = logging.getLogger(__name__)

# Default wall-clock budget for a single Claude invocation (60 minutes). A hung
# job must not block its project lane forever.
DEFAULT_TIMEOUT_SECONDS = 60 * 60

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
# WAITING_LIMIT jobs are excluded from recovery (they are not "running").
STALE_BUFFER_SECONDS = 60

# How long to park a subscription-limited job when the CLI does not tell us when
# the quota resets. The job is re-claimed after this backoff and simply retries;
# if the limit still holds it parks again. Kept modest so a rollover that
# happened in the meantime is picked up promptly rather than slept through.
DEFAULT_LIMIT_BACKOFF_SECONDS = 15 * 60

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

# Substrings (checked case-insensitively) in a run's final result text that
# suggest Claude parked the work on a background/wait mechanism instead of
# actually finishing — the headless equivalent of a blocked question it had
# no channel to ask. Not a defect to suppress: a signal that a human should
# look at the run before it is trusted as "done".
BACKGROUND_MARKERS = (
    'background',
    'im hintergrund',
    'hintergrundprozess',
    'hintergrundtask',
    'wakeup',
    'wake up',
    'aufwecken',
    'scheduled',
    'eingeplant',
    "i'll wait",
    'ich warte',
    'i will wait',
    'want me to',
    'soll ich',
    'sag mir bescheid',
    'let me know',
    'lass es mich wissen',
    'should i proceed',
    'soll ich fortfahren',
)

# Commit-message convention (#1076). Sub-issue PRs squash-merge into the epic
# branch, so each sub-issue becomes exactly one commit on it — and that commit's
# subject is all the final epic PR shows for a whole layer. Carrying the Agira id
# is what keeps that PR reviewable commit-for-commit instead of a wall of
# untraceable squashes.
COMMIT_MESSAGE_INSTRUCTIONS = (
    "Verwende Conventional-Commit-Messages mit der Agira-ID im Scope, z. B. "
    "`feat(#{item_id}): …` oder `fix(#{item_id}): …`, damit der Epic-PR "
    "commit-für-commit nachvollziehbar bleibt."
)

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


class _SubscriptionLimitWait(Exception):
    """Raised internally when a run hit the subscription limit and must wait.

    Carries the (optional) quota reset time and a short human detail so the
    caller can park the job in ``WAITING_LIMIT`` with a meaningful note instead
    of failing it. Never propagates out of ``process_job``.
    """

    def __init__(self, reset_at=None, detail=''):
        super().__init__(detail or 'subscription usage limit reached')
        self.reset_at = reset_at
        self.detail = detail


class Command(BaseCommand):
    help = (
        'Claim and run queued Claude Code jobs. Enforces at-most-one running '
        'job per repo (github_owner/github_repo). Runnable as a cron (--once) '
        'or a loop daemon.'
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
        self._configure_unbuffered_output()
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
            # Before claiming: a chain whose current layer landed since the last
            # run has a next layer to release, and releasing it is what makes it
            # claimable below (#1079).
            self.advance_epics()
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
            self.advance_epics()
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

        Eligible = the oldest *pending, unblocked* job of a repo (the project's
        ``github_owner``/``github_repo``) that currently has no ``running`` job.
        "Pending" means a ``queued`` job, or a ``waiting_limit`` job whose quota
        reset time has passed (or is unknown) — the latter is how a run parked on
        a subscription limit is resumed automatically. "Unblocked" means the
        item's predecessors inside its epic have merged (#1076). Returns the
        claimed job (already committed as running) or ``None`` if nothing is
        claimable.
        """
        with transaction.atomic():
            now = timezone.now()
            # A job is claimable if it is freshly queued, or a waiting-for-quota
            # job whose reset time has arrived (unknown reset ⇒ due now, guarded
            # by the default backoff written at park time).
            pending = (
                Q(status=ClaudeQueueJobStatus.QUEUED)
                | Q(status=ClaudeQueueJobStatus.WAITING_LIMIT, limit_reset_at__isnull=True)
                | Q(status=ClaudeQueueJobStatus.WAITING_LIMIT, limit_reset_at__lte=now)
            )

            # Sub-issues of an epic must run strictly in ``epic_order``: a
            # layer started before its foundation merged is how an agent ends
            # up inventing a mock for the missing part and shipping a green PR
            # built on a prop. Blocked jobs stay ``queued`` and are simply not
            # claimable yet — the merge of the predecessor unblocks them on a
            # later poll, with no intervention.
            #
            # Excluded from the head-of-line subquery below as well, not just
            # from the candidates: otherwise a blocked job that happens to be
            # its repo's oldest would mask every claimable job behind it.
            blocked_ids = self._blocked_job_ids(pending)

            # Repos that already have a running job are off-limits. Keyed on
            # repo identity, not project_id: two projects configured with the
            # same github_owner/github_repo must not run at once either, since
            # they would share the same checkout directory (see
            # _prepare_checkout).
            busy_repos = ClaudeQueueJob.objects.filter(
                status=ClaudeQueueJobStatus.RUNNING,
                project__github_owner=OuterRef('project__github_owner'),
                project__github_repo=OuterRef('project__github_repo'),
            )

            # Restrict candidates to the head-of-line (oldest) pending job of each
            # repo. Without this, skip_locked could hand a second worker the
            # *second*-oldest pending job of a repo whose oldest is locked,
            # breaking the one-per-repo rule.
            older = ClaudeQueueJob.objects.filter(
                pending,
                project__github_owner=OuterRef('project__github_owner'),
                project__github_repo=OuterRef('project__github_repo'),
            ).exclude(pk__in=blocked_ids).filter(
                Q(created_at__lt=OuterRef('created_at'))
                | Q(created_at=OuterRef('created_at'), pk__lt=OuterRef('pk'))
            )

            candidates = (
                ClaudeQueueJob.objects
                .filter(pending)
                .exclude(pk__in=blocked_ids)
                .annotate(_is_busy=Exists(busy_repos))
                .filter(_is_busy=False)
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
            # this transaction so the row is visibly ``running`` to peers. Clear
            # any waiting-quota marker: this is a fresh attempt from now on.
            job.worker_host = socket.gethostname()
            job.worker_pid = os.getpid()
            job.limit_reset_at = None
            job.transition_to(ClaudeQueueJobStatus.RUNNING)

        self.stdout.write(self.style.SUCCESS(
            f"Claimed job #{job.pk} (project {job.project_id}, item {job.item_id})"
        ))
        return job

    def _blocked_job_ids(self, pending):
        """Ids of pending chain entries whose predecessor has not merged (#1076, #1109).

        The block is decided on the **job** now (``parent_job`` set), not on the
        item's ``parent`` alone. Keying it on the item hierarchy was the #1109
        bug: a sub-issue enqueued *standalone* (``parent_job=None``) has an item
        with a parent, so it matched here and ``can_start`` stayed False forever
        — but no epic node existed to ever release it, so it sat in ``queued``
        indefinitely, indistinguishable from a claimable job. Such a standalone
        run is now rejected or attached to a chain at enqueue time (see
        ``enqueue.SubIssueOutsideEpic``); the claim gate concerns itself only
        with genuine chain entries, so the queue's chain and the item hierarchy
        can no longer disagree about what "belongs to an epic" means.

        For a queue of standalone jobs this is one extra, empty query.
        """
        chain_jobs = (
            ClaudeQueueJob.objects
            .filter(pending, parent_job__isnull=False)
            .select_related('item', 'item__parent')
        )
        return [job.pk for job in chain_jobs if not can_start(job.item)]

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

        An epic node (#1079) never gets here: it has no item to implement, so
        it takes the short orchestration path instead of a CLI run.
        """
        if job.is_epic_node:
            self.process_epic_job(job)
            return

        pr_body_file = self._pr_body_file_path(job)
        self._init_pr_body_file(pr_body_file)
        try:
            self._process_job_inner(job, timeout, idle_timeout, pr_body_file)
        finally:
            self._cleanup_pr_body_file(pr_body_file)

    def process_epic_job(self, job):
        """Run the start step of an epic node (#1079).

        Two things happen and no more: the epic branch is materialised, and the
        chain is built and its first layer released. Then the node steps out of
        ``running`` into ``orchestrating`` — it must not keep the repo lane it
        holds while running, because the sub-runs it is now waiting for need
        exactly that lane.

        The branch is created here rather than left to the first sub-run (which
        would create it too, see ``_ensure_base_branch``) so that "the epic has
        started" is a fact on the remote from the first second, not a promise
        that materialises whenever the first layer happens to get claimed.
        """
        from core.services.claude_queue.branch import build_epic_branch_name
        from core.services.claude_queue.orchestration import start_epic

        branch = build_epic_branch_name(job.item)
        try:
            repo_dir = self._prepare_checkout(job)
            self._materialise_epic_branch(job, repo_dir, branch)
            job.branch_name = branch
            job.save(update_fields=['branch_name'])
            self._save_progress(job, f"Epic-Branch {branch} bereit")
            outcome = start_epic(job)
        except Exception as exc:  # noqa: BLE001 — same contract as a failed run
            logger.exception("Epic node #%s failed to start", job.pk)
            self._fail_job(job, error=str(exc))
            self.stdout.write(self.style.ERROR(
                f"Epic node #{job.pk} failed to start: {exc}"
            ))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Epic node #{job.pk} orchestrating {branch} ({outcome})"
        ))

    def advance_epics(self):
        """Let every orchestrating epic node act on what the queue now knows.

        This — not a GitHub webhook — is what drives a chain: the poll that
        already looks for claimable work also asks each epic whether its
        current layer finished cleanly enough to release the next one.
        """
        from core.services.claude_queue.orchestration import advance_all_epics

        try:
            return advance_all_epics()
        except Exception:  # noqa: BLE001 — never let orchestration stop claiming
            logger.exception("Advancing epic chains failed")
            return 0

    def _process_job_inner(self, job, timeout, idle_timeout, pr_body_file):
        try:
            # Credential check first: a job whose user has no credential for the
            # chosen mode must fail with that reason, not silently on the other
            # mode — and before a checkout and an empty PR exist for it (#1083).
            resolve_claude_credential(job.auth_user, self._resolve_auth_mode(job))
        except MissingClaudeCredential as exc:
            self._fail_job(job, error=str(exc))
            self.stdout.write(self.style.ERROR(
                f"Job #{job.pk} failed: missing Claude credential"
            ))
            return

        try:
            repo_dir = self._prepare_checkout(job)
            branch, bootstrap_sha = self._create_branch_and_pr(job, repo_dir)
            result = self._run_cli_with_auth(job, repo_dir, timeout, idle_timeout, pr_body_file)
        except _SubscriptionLimitWait as wait:
            # Not a failure: the subscription quota is exhausted. Park the job
            # until the rollover — it will be re-claimed automatically — and
            # leave the item in ``Working`` (it is still being worked on).
            self._park_for_limit(job, wait)
            return
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

        # Claude is told to commit its own work but may stop short of it (ran
        # out of turns, misjudged its own completion, ...). Rescue anything
        # left in the working tree before the next job's checkout reset would
        # discard it, then push whatever ended up on the branch. Best-effort:
        # Claude may already have committed and pushed, or produced nothing.
        self._commit_uncommitted_work(repo_dir, job)
        self._push_branch(repo_dir, branch)

        if self._is_auth_error(result):
            # A broken/expired credential never fixes itself by waiting — fail
            # the job with an actionable message instead of parking it.
            error = self._auth_error_message(result, job)
            self._fail_job(job, error=error)
            self._update_pr_body(job, error=error)
            self.stdout.write(self.style.ERROR(
                f"Job #{job.pk} failed: authentication problem"
            ))
            return

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

        if self._is_empty_diff(repo_dir, bootstrap_sha):
            # Still no diff even after the rescue-commit attempt above: this is
            # a genuine empty run, not a bookkeeping accident. It must not look
            # like a clean "done" — that is exactly the failure mode (an
            # empty PR merged on the strength of an unrelated success body)
            # this check exists to prevent.
            error = "Kein Code committet – Claude hat keine Änderungen geliefert."
            job.completion_uncertain = True
            job.completion_uncertain_reason = (
                "Leerer PR: keine Änderungen über den Start-Commit hinaus "
                "(auch nach automatischem Rettungscommit-Versuch)."
            )
            self._fail_job(job, error=error)
            self._update_pr_body(job, error=error)
            self.stdout.write(self.style.ERROR(
                f"Job #{job.pk} failed: no code committed (empty diff)"
            ))
            return

        uncertain_reason = self._detect_completion_uncertain(
            repo_dir, bootstrap_sha, result.get('result_text')
        )
        if uncertain_reason:
            job.completion_uncertain = True
            job.completion_uncertain_reason = uncertain_reason

        self._update_pr_body(
            job, summary=result.get('result_text'), pr_body_file=pr_body_file
        )
        # Work is done: flip the up-front draft PR to ready for review (#1114) so
        # no manual `gh pr ready` is needed before the human review + merge.
        self._mark_pr_ready(job, repo_dir)
        job.transition_to(ClaudeQueueJobStatus.DONE)
        if uncertain_reason:
            self.stdout.write(self.style.WARNING(
                f"Job #{job.pk} done, but completion uncertain: {uncertain_reason}"
            ))
        else:
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
    # Branch + PR (the up-front trick)
    # ------------------------------------------------------------------ #
    def _create_branch_and_pr(self, job, repo_dir):
        """Cut ``fix/{item-slug}`` off the item's base, empty commit, push, PR.

        The base is ``main`` for a standalone item and the parent's epic branch
        for a sub-issue (#1076) — see ``_ensure_base_branch``. The PR is opened
        *before* Claude runs and its reference is written to the job + an
        ``ExternalIssueMapping`` (Kind=PR) immediately, so it stays
        deterministic regardless of what Claude does. Returns ``(branch,
        bootstrap_sha)`` — the latter is the empty bootstrap commit's SHA, used
        after the run to detect an empty PR (see ``_detect_completion_uncertain``).
        """
        item = job.item
        branch = self._branch_name(item)
        base = self._ensure_base_branch(job, repo_dir)

        # The base ref is local and current at this point: ``main`` from the
        # checkout reset, an epic branch from ``_ensure_base_branch``.
        self._git(['checkout', '-B', branch, base], cwd=repo_dir)
        self._git(
            ['commit', '--allow-empty', '-m',
             f"chore: start Claude work on item #{item.id}"],
            cwd=repo_dir,
        )
        bootstrap_sha = self._git(['rev-parse', 'HEAD'], cwd=repo_dir).strip()
        self._git(
            ['push', '--force-with-lease', '-u', 'origin', branch],
            cwd=repo_dir,
        )

        job.branch_name = branch
        job.save(update_fields=['branch_name'])

        self._open_pr(job, branch, repo_dir, base)
        return branch, bootstrap_sha

    def _branch_name(self, item):
        """Deterministic, collision-free branch name for an item."""
        slug = slugify(item.title)[:50].strip('-')
        return f"fix/{slug}-{item.id}" if slug else f"fix/item-{item.id}"

    def _ensure_base_branch(self, job, repo_dir):
        """Materialise the branch this job's work branch is cut from (#1076).

        Returns a *local* ref name, already checked out and current.

        For an item without a parent this is plain ``main`` — the checkout was
        just hard-reset to ``origin/main``, so there is nothing to do and the
        pre-#1076 path is bit-for-bit unchanged.

        For a sub-issue it is the parent's epic branch, which is created here
        on first use (nobody creates it up front) and otherwise brought up to
        date with ``main`` before the sub-issue branches off it. Pulling
        ``main`` in *now* rather than later is what keeps each layer starting
        from the newest foundation instead of accumulating drift across a
        chain that may run for days.
        """
        base = resolve_base_branch(job.item)
        if base == DEFAULT_BASE_BRANCH:
            return DEFAULT_BASE_BRANCH
        return self._materialise_epic_branch(job, repo_dir, base)

    def _materialise_epic_branch(self, job, repo_dir, base):
        """Create or refresh epic branch ``base`` locally and on the remote.

        Split out of ``_ensure_base_branch`` because the epic node's start step
        (#1079) needs exactly this and nothing else: the node has no work
        branch to cut and no PR to open, it just has to make sure the branch
        its chain will target exists before releasing the first layer.
        """
        if self._remote_branch_exists(repo_dir, base):
            self._git(['checkout', '-B', base, f'origin/{base}'], cwd=repo_dir)
            try:
                self._git(
                    ['merge', '--no-edit', f'origin/{DEFAULT_BASE_BRANCH}'],
                    cwd=repo_dir,
                )
            except RuntimeError as exc:
                # A conflict between main and the epic branch needs a human;
                # continuing would silently build the next layer on a stale
                # base. Abort the half-done merge so the checkout stays usable.
                self._git(['merge', '--abort'], cwd=repo_dir)
                raise RuntimeError(
                    f"Epic-Branch '{base}' konnte nicht mit "
                    f"'{DEFAULT_BASE_BRANCH}' zusammengeführt werden: {exc}"
                ) from exc
            self._save_progress(job, f"Epic-Branch {base} auf main-Stand gebracht")
        else:
            self._git(
                ['checkout', '-B', base, f'origin/{DEFAULT_BASE_BRANCH}'],
                cwd=repo_dir,
            )
            self._save_progress(job, f"Epic-Branch {base} angelegt")

        self._git(['push', '-u', 'origin', base], cwd=repo_dir)
        return base

    def _remote_branch_exists(self, repo_dir, branch):
        """True if ``origin/<branch>`` exists in the (freshly fetched) checkout."""
        output = self._git(
            ['ls-remote', '--heads', 'origin', branch], cwd=repo_dir,
        )
        return bool(output.strip())

    def _open_pr(self, job, branch, repo_dir, base=DEFAULT_BASE_BRANCH):
        """Open the PR and record it on the job + ExternalIssueMapping.

        A PR against ``main`` is a **draft** merged by hand, as before. A
        sub-issue PR against an epic branch is opened ready-for-review with
        squash auto-merge armed instead (#1076): a single layer is not
        independently testable, so waiting for a human between layers would
        stall the chain for no gained signal — CI plus the review pass are the
        gate, and the human review happens once on the assembled epic.

        A retried job reuses the exact same deterministic branch name as its
        earlier attempt (``_branch_name`` is keyed on the item, not the job),
        so an earlier attempt may already have a PR open on it. Checking for
        that PR up front makes retries idempotent instead of hitting GitHub's
        422 "A pull request already exists for ..." on every re-run.

        If creation still races and hits that 422 (or any other API error),
        re-check for an existing PR before falling back to ``gh pr list
        --head`` and finally giving up.
        """
        from core.services.github.service import GitHubService

        service = GitHubService()
        draft = base == DEFAULT_BASE_BRANCH

        mapping = self._find_existing_pr(job, branch, service)
        reused = mapping is not None

        if mapping is None:
            try:
                mapping = service.create_draft_pr_for_item(
                    job.item,
                    branch_name=branch,
                    base=base,
                    title=job.item.title,
                    body=self._pr_body(job, base),
                    draft=draft,
                )
            except Exception as exc:  # noqa: BLE001 — a retry may hit an already-open PR
                logger.warning(
                    "PR API call failed for job #%s (%s); looking for an "
                    "existing PR on %s",
                    job.pk, exc, branch,
                )
                mapping = (
                    self._find_existing_pr(job, branch, service)
                    or self._pr_from_gh_fallback(job, branch, repo_dir)
                )
                if mapping is None:
                    raise
                reused = True

        self._apply_pr_mapping(job, mapping, reused=reused)
        if not draft:
            self._enable_auto_merge(job, mapping.number, repo_dir)

    def _enable_auto_merge(self, job, pr_number, repo_dir):
        """Arm squash auto-merge on a sub-issue PR (#1076).

        Squash so the epic PR stays reviewable commit-for-commit: one commit
        per sub-issue, carrying its Agira id. GitHub then merges the PR by
        itself once the required checks pass — that is the whole point, since
        the chain has to keep moving overnight without a human in the loop.

        Best-effort: if the repo has neither auto-merge enabled nor required
        checks configured, the call fails and the PR simply waits for a manual
        merge. That is a slower chain, not a broken job.
        """
        try:
            proc = subprocess.run(
                ['gh', 'pr', 'merge', str(pr_number), '--squash', '--auto'],
                cwd=repo_dir, capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Auto-merge call failed for job #%s: %s", job.pk, exc)
            return

        if proc.returncode != 0:
            logger.warning(
                "Could not enable auto-merge on PR #%s (job #%s): %s",
                pr_number, job.pk, (proc.stderr or proc.stdout).strip(),
            )
            return

        self.stdout.write(f"  Auto-merge (squash) armed on PR #{pr_number}")

    def _mark_pr_ready(self, job, repo_dir):
        """Flip the job's draft PR to *ready for review* once the work is done (#1114).

        The bootstrap PR against ``main`` is opened as a **draft** (see
        ``_open_pr``) so a half-finished run never looks review-ready. Once the
        job completes successfully the draft has served its purpose: mark it
        ready so the only remaining human steps are review and merge — no manual
        ``gh pr ready`` afterwards.

        Guarded and idempotent, so retries and non-draft PRs are safe no-ops:
        - skips when the job has no recorded PR at all,
        - reads the PR first and only flips it when it is *still an open draft*.
          A sub-issue PR is opened ready-for-review already (see ``_open_pr``),
          and a re-run finds the PR already ready — both short-circuit here
          instead of erroring on ``gh pr ready``.

        Best-effort, mirroring ``_enable_auto_merge``: a failed flip is logged
        but never fails an otherwise-successful job. Uses the ``gh`` CLI like the
        auto-merge/PR-fallback paths — the draft→ready transition is a GraphQL
        mutation the REST layer used elsewhere cannot express.
        """
        pr_number = job.pr_number
        if not pr_number:
            return

        try:
            proc = subprocess.run(
                ['gh', 'pr', 'view', str(pr_number), '--json', 'state,isDraft'],
                cwd=repo_dir, capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("PR status lookup failed for job #%s: %s", job.pk, exc)
            return

        if proc.returncode != 0:
            logger.warning(
                "Could not read PR #%s status (job #%s): %s",
                pr_number, job.pk, (proc.stderr or proc.stdout).strip(),
            )
            return

        try:
            info = json.loads(proc.stdout or '{}')
        except json.JSONDecodeError as exc:
            logger.warning(
                "Could not parse PR #%s status (job #%s): %s", pr_number, job.pk, exc,
            )
            return

        if info.get('state') != 'OPEN' or not info.get('isDraft'):
            # Already ready-for-review, merged, or closed — nothing to do.
            return

        try:
            proc = subprocess.run(
                ['gh', 'pr', 'ready', str(pr_number)],
                cwd=repo_dir, capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Mark-ready call failed for job #%s: %s", job.pk, exc)
            return

        if proc.returncode != 0:
            logger.warning(
                "Could not mark PR #%s ready for review (job #%s): %s",
                pr_number, job.pk, (proc.stderr or proc.stdout).strip(),
            )
            return

        note = f"PR #{pr_number} auf Ready for review gesetzt"
        self._save_progress(job, note)
        self.stdout.write(f"  {note}")

    def _find_existing_pr(self, job, branch, service):
        """Best-effort lookup of an already-open PR for ``branch`` via the API.

        Returns None (never raises) so a lookup hiccup still lets the normal
        create-PR path run instead of aborting the job.
        """
        try:
            return service.find_open_pr_for_branch(job.item, branch)
        except Exception as exc:  # noqa: BLE001 — fall through to PR creation
            logger.warning(
                "Existing-PR lookup failed for job #%s (%s)", job.pk, exc,
            )
            return None

    def _apply_pr_mapping(self, job, mapping, *, reused):
        """Record the PR on the job, logging whether it was reused or created."""
        job.pr_number = mapping.number
        job.pr_url = mapping.html_url
        job.save(update_fields=['pr_number', 'pr_url'])
        if reused:
            note = f"Reusing existing PR #{mapping.number} for branch {job.branch_name}"
            self._save_progress(job, note)
            self.stdout.write(f"  {note}: {mapping.html_url}")
        else:
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

    def _pr_body(self, job, base=DEFAULT_BASE_BRANCH):
        item = job.item
        lines = [
            "Automated PR opened by the Claude queue worker for "
            f"Agira item #{item.id}.",
            '',
            f"Model: {job.get_model_display()}",
            f"Job: #{job.pk}",
        ]
        if base != DEFAULT_BASE_BRANCH:
            position = sub_issue_position(item)
            lines += [
                f"Epic: #{item.parent_id} — Sub-Issue {position} "
                f"(Order {item.epic_order})",
                f"Target: `{base}` (Epic-Branch, Squash-Auto-Merge)",
            ]
        return '\n'.join(lines)

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

    def _commit_uncommitted_work(self, repo_dir, job):
        """Auto-commit any working-tree changes Claude left uncommitted.

        The prompt asks Claude to commit its own changes, but a run can edit
        files and stop short of ``git commit`` — that work would otherwise be
        silently discarded by the next job's ``reset --hard``/``clean -fd``.
        Deliberately unconditional (not gated on "no commit exists yet"): a
        run that made a partial commit and then left further edits
        uncommitted must not lose that tail either.

        ``.claude/settings.local.json`` is the worker's own trust-settings
        file (written by ``_write_trust_settings``), never Claude's work, so
        it is staged and then explicitly unstaged before checking whether
        anything worth committing remains.

        Best-effort: any git failure here (e.g. a bad ``repo_dir`` in tests)
        is swallowed and treated as "nothing to rescue" rather than failing
        the job. Returns True if a rescue commit was made.
        """
        try:
            self._git(['add', '-A'], cwd=repo_dir)
            self._git(['reset', '--', '.claude/settings.local.json'], cwd=repo_dir)
            proc = subprocess.run(
                ['git', 'diff', '--cached', '--quiet'], cwd=repo_dir, timeout=60,
            )
            if proc.returncode == 0:
                self._git(['reset'], cwd=repo_dir)
                return False

            self._git(
                ['commit', '-m',
                 f"chore(#{job.item_id}): auto-commit uncommitted work from Claude run"],
                cwd=repo_dir,
            )
            return True
        except Exception as exc:  # noqa: BLE001 — best-effort rescue, must not fail the job
            logger.warning("Auto-commit rescue failed for %s: %s", repo_dir, exc)
            return False

    # ------------------------------------------------------------------ #
    # Completion-uncertain detection
    # ------------------------------------------------------------------ #
    def _detect_completion_uncertain(self, repo_dir, bootstrap_sha, result_text):
        """Return a short reason if a "successful" run's outcome looks doubtful.

        A run that exits cleanly and emits a result event is not automatically
        trustworthy: Claude may have hit something that needed a human call (a
        false premise, an out-of-scope finding) and, headless, had no channel to
        ask — so it stalled, waited, or punted to a background/wakeup mechanism
        instead. That pause is signal, not a defect to paper over, so it must
        stay visible instead of being flattened into a plain "Done".

        Two independent checks, outcome first because it is the reliable one:

        1. Outcome: is the branch's diff against the bootstrap commit empty? An
           empty PR is a strong "nothing really landed" signal regardless of
           what Claude's text claims.
        2. Prose: does the final result text contain a background/wait/ask
           marker? Catches cases the outcome check misses (partial commits plus
           an open question).

        Returns ``None`` when neither signal fires.
        """
        if self._is_empty_diff(repo_dir, bootstrap_sha):
            return "Leerer PR: keine Änderungen über den Start-Commit hinaus."

        marker = self._find_background_marker(result_text)
        if marker:
            return (
                "Claude-Text deutet auf Warten/Hintergrund-Auslagerung/Rückfrage "
                f"hin (Hinweis: „{marker}“)."
            )

        return None

    def _is_empty_diff(self, repo_dir, bootstrap_sha):
        """True if the checkout has no changes relative to ``bootstrap_sha``."""
        try:
            proc = subprocess.run(
                ['git', 'diff', '--quiet', bootstrap_sha, 'HEAD'],
                cwd=repo_dir, timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("Empty-diff check failed for %s: %s", repo_dir, exc)
            return False
        return proc.returncode == 0

    def _find_background_marker(self, result_text):
        """Return the first background/wait/ask marker found in ``result_text``."""
        text = (result_text or '').strip()
        if not text:
            return None
        lowered = text.lower()
        for marker in BACKGROUND_MARKERS:
            if marker in lowered:
                return marker
        if text.endswith('?'):
            return 'endet mit einer Frage'
        return None

    # ------------------------------------------------------------------ #
    # Claude Code invocation + stream parsing
    # ------------------------------------------------------------------ #
    def _run_cli(self, job, repo_dir, timeout, idle_timeout, pr_body_file,
                 *, auth_mode=ClaudeQueueJobAuthMode.OAUTH):
        """Run Claude Code headless in ``repo_dir`` and parse its event stream.

        ``auth_mode`` selects the child-process credentials (subscription OAuth
        vs. API key); it is prepared per subprocess so a globally exported
        ``ANTHROPIC_API_KEY`` can never silently override an OAuth run.

        Returns a result dict with ``session_id``/``num_turns``/
        ``total_cost_usd``/``is_error``/``result_text``/``saw_result``/
        ``returncode``/``stderr``. Raises ``subprocess.TimeoutExpired`` when the
        wall-clock budget is exhausted.
        """
        args = self._build_claude_args(job)
        env = self._build_env(job, pr_body_file, auth_mode=auth_mode)

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
        """Assemble the headless Claude Code command line.

        The job's model is a stored slug (``opus-5``), not something the CLI
        understands — it is translated to a concrete ``--model`` identifier
        here (#1082).
        """
        model = job.model or job.item.suggested_model
        return [
            settings.CLAUDE_CLI_BIN,
            '-p', self._build_prompt(job.item),
            '--model', claude_cli_model_id(model),
            '--output-format', 'stream-json',
            '--verbose',
            '--dangerously-skip-permissions',
        ]

    def _build_env(self, job, pr_body_file, *, auth_mode=ClaudeQueueJobAuthMode.OAUTH):
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
        """
        env = dict(
            os.environ,
            CLAUDE_QUEUE_JOB_ID=str(job.pk),
            PR_BODY_FILE=str(pr_body_file),
        )
        # Start from a clean slate so nothing inherited decides the auth for us.
        for name in ALL_AUTH_ENV_VARS:
            env.pop(name, None)

        credential = resolve_claude_credential(job.auth_user, auth_mode)
        if credential.value:
            env[credential.env_var] = credential.value
        self._set_credential_source(job, credential.source)
        return env

    def _set_credential_source(self, job, source):
        """Record which credential the current attempt actually used."""
        if job.auth_credential_source == source:
            return
        job.auth_credential_source = source
        job.save(update_fields=['auth_credential_source'])

    # ------------------------------------------------------------------ #
    # Auth mode + reactive limit handling
    # ------------------------------------------------------------------ #
    def _run_cli_with_auth(self, job, repo_dir, timeout, idle_timeout, pr_body_file):
        """Run Claude under the configured auth, reacting to a subscription limit.

        Default path is the subscription (OAuth). If that run reports a usage
        limit, either fall back to the API key (only when the job is flagged for
        it and a key is configured) or raise ``_SubscriptionLimitWait`` so the
        caller parks the job until the quota rolls over. Any other outcome —
        including a credential failure — is returned as-is for the normal
        success/failure handling.
        """
        auth_mode = self._resolve_auth_mode(job)
        self._set_auth_mode(job, auth_mode)
        result = self._run_cli(
            job, repo_dir, timeout, idle_timeout, pr_body_file, auth_mode=auth_mode,
        )

        # A bad credential is not a limit — let the caller fail it clearly.
        if self._is_auth_error(result):
            return result

        if auth_mode == ClaudeQueueJobAuthMode.OAUTH and self._is_limit_error(result):
            if job.allow_api_key_fallback and self._api_key_available(job):
                self._save_progress(
                    job, 'Abo-Limit erreicht – Fallback auf API-Key (Job-Flag gesetzt).'
                )
                self.stdout.write(self.style.WARNING(
                    f"Job #{job.pk} hit the subscription limit; falling back to the API key"
                ))
                self._set_auth_mode(job, ClaudeQueueJobAuthMode.API_KEY)
                return self._run_cli(
                    job, repo_dir, timeout, idle_timeout, pr_body_file,
                    auth_mode=ClaudeQueueJobAuthMode.API_KEY,
                )
            raise _SubscriptionLimitWait(
                reset_at=self._parse_limit_reset(result),
                detail=self._limit_detail(result),
            )

        return result

    def _resolve_auth_mode(self, job):
        """Return the auth mode this run must use.

        The job carries the item's per-issue choice, frozen at enqueue time
        (#1083); ``settings.CLAUDE_AUTH_MODE`` is only the host-wide fallback
        for jobs from before that field existed.
        """
        configured = (
            job.requested_auth_mode
            or getattr(settings, 'CLAUDE_AUTH_MODE', 'oauth')
            or 'oauth'
        ).strip().lower()
        if configured == ClaudeQueueJobAuthMode.API_KEY:
            return ClaudeQueueJobAuthMode.API_KEY
        return ClaudeQueueJobAuthMode.OAUTH

    def _set_auth_mode(self, job, auth_mode):
        """Persist the auth mode used for the current attempt on the job."""
        job.auth_mode = auth_mode
        job.save(update_fields=['auth_mode'])

    def _api_key_available(self, job):
        """True if an API-key run for this job's user could be served at all."""
        try:
            resolve_claude_credential(job.auth_user, ClaudeQueueJobAuthMode.API_KEY)
        except MissingClaudeCredential:
            return False
        return True

    def _park_for_limit(self, job, wait):
        """Move a limit-hit job to ``WAITING_LIMIT`` until the quota rolls over.

        Records the (best-effort) reset time so the claim query re-picks it then,
        and writes a visible "waiting" note. Deliberately does **not** touch
        ``error_text`` or release the item: waiting is not a failure.
        """
        reset_at = wait.reset_at or (
            timezone.now() + timedelta(seconds=DEFAULT_LIMIT_BACKOFF_SECONDS)
        )
        when = timezone.localtime(reset_at).strftime('%Y-%m-%d %H:%M')
        note = f"Abo-Kontingent erreicht – wartet auf Rollover (frühestens {when})."
        job.limit_reset_at = reset_at
        job.progress_text = note[:2000]
        job.transition_to(ClaudeQueueJobStatus.WAITING_LIMIT)
        self.stdout.write(self.style.WARNING(
            f"Job #{job.pk} waiting for subscription quota until {when}"
        ))

    def _match_markers(self, result, markers):
        """True if any marker appears in the run's result text or stderr."""
        haystack = (
            f"{result.get('result_text', '')}\n{result.get('stderr', '')}"
        ).lower()
        return any(marker in haystack for marker in markers)

    def _is_limit_error(self, result):
        """True if an *errored* run looks like a subscription usage-limit hit.

        Gated on the run actually erroring (``is_error`` or a non-zero exit) so a
        successful run that merely mentions "quota" in its summary is not
        misread as a limit.
        """
        errored = result.get('is_error') or result.get('returncode', 0) != 0
        return bool(errored) and self._match_markers(result, LIMIT_MARKERS)

    def _is_auth_error(self, result):
        """True if an errored run looks like a broken/expired credential."""
        errored = result.get('is_error') or result.get('returncode', 0) != 0
        return bool(errored) and self._match_markers(result, AUTH_ERROR_MARKERS)

    def _limit_detail(self, result):
        """A short, log-safe detail string for a limit hit."""
        detail = (result.get('result_text') or result.get('stderr') or '').strip()
        return detail[:500]

    def _auth_error_message(self, result, job=None):
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

    def _parse_limit_reset(self, result):
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
        parts.append(COMMIT_MESSAGE_INSTRUCTIONS.format(item_id=item.id))
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
        """Resolve running jobs left behind by a worker that is no longer here.

        Runs once at startup, before the first claim. A ``running`` job whose
        supervisor is gone would otherwise hold its repo lane forever — the
        per-repo concurrency gate in ``claim_next_job`` treats *any* ``running``
        job as making that whole repo busy (see ``busy_repos``), so a single
        zombie can block a lane indefinitely. Two dispositions (see
        ``_orphan_disposition``):

        * **Reclaim** — the owning worker process on this host is provably dead
          (hard kill / crash mid-run, #1110). The work itself is not at fault,
          so the job goes back to ``queued`` and simply runs again; its item
          stays in ``Working``.
        * **Fail** — the job outlived its timeout or never recorded an owner.
          We cannot prove a clean interrupt, so it is failed and its item
          released, exactly as before.
        """
        running = ClaudeQueueJob.objects.filter(status=ClaudeQueueJobStatus.RUNNING)
        reclaimed = 0
        failed = 0
        for job in running:
            disposition = self._orphan_disposition(job, timeout)
            if disposition is None:
                continue
            action, reason = disposition
            if action == 'reclaim':
                self.stdout.write(self.style.WARNING(
                    f"Reclaiming orphaned job #{job.pk} to the queue: {reason}"
                ))
                self._reclaim_job(job, reason)
                reclaimed += 1
            else:
                self.stdout.write(self.style.WARNING(
                    f"Recovering orphaned job #{job.pk}: {reason}"
                ))
                self._fail_job(job, error=f"Crash recovery: {reason}")
                failed += 1
        if reclaimed or failed:
            self.stdout.write(self.style.SUCCESS(
                f"Crash recovery: requeued {reclaimed}, failed {failed} "
                f"orphaned job(s)"
            ))

    def _orphan_disposition(self, job, timeout):
        """Classify a running job for crash recovery.

        Returns ``None`` for a job that is still legitimately running, or an
        ``(action, reason)`` pair where ``action`` is:

        * ``'reclaim'`` — the worker that owned this job is provably dead: its
          PID on *this* host no longer exists. That is the hard-kill-mid-run
          case (systemd stop, SIGKILL, crash), so the job is put back to
          ``queued`` and runs again rather than being failed or left to block
          its repo lane.
        * ``'fail'`` — the job outlived its wall-clock timeout, or is running
          with no owner recorded at all. Neither proves a clean interrupt (the
          owner may be a live process on another host we cannot probe, or the
          run blew its budget), so it is failed and its item released.
        """
        # Authoritative: a job owned by a dead process on *this* host was cut
        # off mid-run — reclaim it so it runs again instead of stranding its
        # repo lane behind a zombie ``running`` row.
        if job.worker_host == socket.gethostname() and job.worker_pid:
            if not self._pid_alive(job.worker_pid):
                return 'reclaim', 'worker process no longer running'

        # Ran longer than its own timeout could allow: a live worker would have
        # enforced it locally, so its supervisor is gone. We can't probe a
        # foreign host's PID, and a run that already blew its budget must not
        # restart into the same wall — fail it.
        if job.started_at is not None:
            age = (timezone.now() - job.started_at).total_seconds()
            if age > timeout + STALE_BUFFER_SECONDS:
                return 'fail', f"running for {int(age)}s, exceeds timeout of {timeout}s"

        # Running with no owner recorded — nobody is driving it. An anomaly (a
        # claim always records its owner), so fail rather than assume a rerun is
        # safe.
        if not job.worker_pid:
            return 'fail', 'running with no worker owner recorded'

        return None

    def _reclaim_job(self, job, reason):
        """Return an interrupted running job to the queue so it runs again.

        Clears the dead worker's ownership and moves the job back to ``queued``;
        the next poll re-claims it like any fresh entry (``transition_to`` then
        re-stamps ``started_at``, so the age check measures the new run, not the
        killed one). Deliberately leaves the item in ``Working`` and does not
        set ``error_text`` — an interrupted run is not a failed one.
        """
        job.worker_host = ''
        job.worker_pid = None
        job.progress_text = (
            f"Reclaim nach Worker-Neustart ({reason}); zurück in die Queue."
        )[:2000]
        job.transition_to(ClaudeQueueJobStatus.QUEUED)

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
    def _configure_unbuffered_output(self):
        """Make stdout/stderr line-buffered so logs surface immediately (#1110).

        Under systemd (and any pipe) Python block-buffers stdout, so the start
        banner and the ``Claimed job``/recovery lines can sit unflushed for many
        minutes — the worker looks dead in ``journalctl`` while it is in fact
        just idle-polling. That false "the worker crashed" trail is exactly what
        cost so much time in the #1109 debug session. Reconfiguring the streams
        to line buffering flushes every newline-terminated ``write`` as it
        happens — the same effect as ``PYTHONUNBUFFERED=1`` / ``python -u``, but
        without depending on the deployment unit remembering to set it.

        Best-effort: a stream that can't be reconfigured (a ``StringIO`` in
        tests, an already-detached stream) is left as-is.
        """
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, 'reconfigure', None)
            if reconfigure is None:
                continue
            try:
                reconfigure(line_buffering=True)
            except (ValueError, OSError):
                pass

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
