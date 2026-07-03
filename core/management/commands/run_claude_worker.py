"""
Django management command: Claude Code queue worker.

This is the *engine* of the Claude queue. It claims queued ``ClaudeQueueJob``
rows and runs them. This command deliberately covers only **claiming &
concurrency** plus the lifecycle scaffolding (timeout, error paths, crash
recovery). The actual PR-creation / Claude CLI invocation is a seam
(``_run_cli`` / the ``--cli-command`` template) that is filled in by #832.

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

import logging
import os
import signal
import socket
import subprocess
import time

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobStatus,
    ItemStatus,
)

logger = logging.getLogger(__name__)

# Default wall-clock budget for a single CLI invocation (30 minutes). A hung
# job must not block its project lane forever.
DEFAULT_TIMEOUT_SECONDS = 30 * 60

# Default poll interval for daemon mode.
DEFAULT_INTERVAL_SECONDS = 5

# A running job whose start is older than ``timeout + STALE_BUFFER`` is treated
# as orphaned during crash recovery: a live worker would have enforced the
# timeout itself, so if the job is still "running" its supervisor is gone.
STALE_BUFFER_SECONDS = 60

# Placeholder command used until #832 wires the real Claude CLI invocation.
# ``true`` exits 0 without doing anything, so a queued job cleanly reaches DONE.
DEFAULT_CLI_COMMAND = 'true'


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
            help=f'Per-job CLI timeout in seconds (default: {DEFAULT_TIMEOUT_SECONDS}).',
        )
        parser.add_argument(
            '--cli-command',
            type=str,
            default=DEFAULT_CLI_COMMAND,
            help='Shell command executed per job (seam for #832). The job id is '
                 'exported as CLAUDE_QUEUE_JOB_ID.',
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
        cli_command = options['cli_command']

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
                self.process_job(job, timeout, cli_command)
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
            self.process_job(job, timeout, cli_command)
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

            # Take ownership *before* the long-running CLI part, and commit it
            # with this transaction so the row is visibly ``running`` to peers.
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
    def process_job(self, job, timeout, cli_command):
        """Run a claimed job to a terminal state (done/failed).

        Wraps the CLI invocation in a timeout. Non-zero exit or timeout drives
        the job to ``failed`` with diagnostics and releases the item so it does
        not starve in ``Working``.
        """
        try:
            returncode, stdout, stderr = self._run_cli(job, cli_command, timeout)
        except subprocess.TimeoutExpired:
            self._fail_job(
                job,
                error=f"Job exceeded the {timeout}s timeout and was terminated.",
            )
            self.stdout.write(self.style.ERROR(f"Job #{job.pk} timed out after {timeout}s"))
            return
        except Exception as exc:  # noqa: BLE001 — any failure to launch is a job failure
            logger.exception("Failed to launch CLI for job #%s", job.pk)
            self._fail_job(job, error=f"Failed to launch worker CLI: {exc}")
            self.stdout.write(self.style.ERROR(f"Job #{job.pk} failed to launch: {exc}"))
            return

        if returncode != 0:
            detail = (stderr or stdout or '').strip()
            self._fail_job(
                job,
                error=detail or f"CLI exited with non-zero status {returncode}.",
            )
            self.stdout.write(self.style.ERROR(
                f"Job #{job.pk} failed (exit {returncode})"
            ))
            return

        # Success. #832 fills in PR metadata / result fields before this point.
        if stdout.strip():
            job.progress_text = stdout.strip()[:2000]
        job.transition_to(ClaudeQueueJobStatus.DONE)
        self.stdout.write(self.style.SUCCESS(f"Job #{job.pk} done"))

    def _run_cli(self, job, cli_command, timeout):
        """Execute the per-job CLI command under a hard timeout.

        Seam for #832: today this runs ``cli_command`` (a no-op by default);
        #832 replaces the command with the real Claude Code invocation. Returns
        ``(returncode, stdout, stderr)``; raises ``subprocess.TimeoutExpired``
        on timeout.
        """
        env = dict(os.environ, CLAUDE_QUEUE_JOB_ID=str(job.pk))
        proc = subprocess.run(
            cli_command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout, proc.stderr

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
