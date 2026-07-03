"""
Tests for the Claude queue worker command (run_claude_worker).

Covers the two hard guarantees from the issue:

* Two queued jobs of the *same* project never run in parallel.
* Jobs of *different* projects may run in parallel.

plus the timeout / error end-states and crash recovery.
"""

import os
import subprocess
from io import StringIO
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from core.management.commands.run_claude_worker import Command
from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobStatus,
    Item,
    ItemStatus,
    ItemType,
    Project,
)


class ClaudeWorkerTestBase(TestCase):
    def setUp(self):
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.project_a = Project.objects.create(name='Project A')
        self.project_b = Project.objects.create(name='Project B')

    def _item(self, project, status=ItemStatus.BACKLOG):
        return Item.objects.create(
            project=project,
            title='Item',
            type=self.item_type,
            status=status,
        )

    def _job(self, project, status=ClaudeQueueJobStatus.QUEUED, **kwargs):
        item = kwargs.pop('item', None) or self._item(project)
        job = ClaudeQueueJob.objects.create(
            item=item,
            project=project,
            status=status,
            **kwargs,
        )
        return job


class ClaimNextJobTests(ClaudeWorkerTestBase):
    def test_claims_oldest_queued_job(self):
        first = self._job(self.project_a)
        second = self._job(self.project_a)

        claimed = Command().claim_next_job()

        self.assertEqual(claimed.pk, first.pk)
        first.refresh_from_db()
        self.assertEqual(first.status, ClaudeQueueJobStatus.RUNNING)
        self.assertIsNotNone(first.started_at)
        self.assertEqual(first.worker_pid, os.getpid())
        # Second stays queued.
        second.refresh_from_db()
        self.assertEqual(second.status, ClaudeQueueJobStatus.QUEUED)

    def test_skips_project_with_running_job(self):
        # Project A already has a running job → its queued job is off-limits.
        self._job(self.project_a, status=ClaudeQueueJobStatus.RUNNING)
        queued_a = self._job(self.project_a)
        queued_b = self._job(self.project_b)

        claimed = Command().claim_next_job()

        # Only project B is eligible.
        self.assertEqual(claimed.project_id, self.project_b.id)
        self.assertEqual(claimed.pk, queued_b.pk)
        queued_a.refresh_from_db()
        self.assertEqual(queued_a.status, ClaudeQueueJobStatus.QUEUED)

    def test_only_head_of_line_job_per_project_is_a_candidate(self):
        # The head-of-line predicate must expose exactly one candidate per
        # project, so a second worker can't grab the 2nd-oldest queued job.
        head = self._job(self.project_a)
        self._job(self.project_a)  # newer, must not be a candidate
        self._job(self.project_a)  # newer, must not be a candidate

        older = ClaudeQueueJob.objects.filter(
            project_id=head.project_id,
            status=ClaudeQueueJobStatus.QUEUED,
            created_at__lt=head.created_at,
        )
        self.assertFalse(older.exists())

        claimed = Command().claim_next_job()
        self.assertEqual(claimed.pk, head.pk)

    def test_returns_none_when_nothing_eligible(self):
        self._job(self.project_a, status=ClaudeQueueJobStatus.RUNNING)
        self._job(self.project_a)  # blocked by the running job above

        self.assertIsNone(Command().claim_next_job())

    def test_different_projects_can_both_be_claimed(self):
        job_a = self._job(self.project_a)
        job_b = self._job(self.project_b)

        first = Command().claim_next_job()
        second = Command().claim_next_job()

        claimed_projects = {first.project_id, second.project_id}
        self.assertEqual(claimed_projects, {self.project_a.id, self.project_b.id})
        for job in (job_a, job_b):
            job.refresh_from_db()
            self.assertEqual(job.status, ClaudeQueueJobStatus.RUNNING)


class ProcessJobTests(ClaudeWorkerTestBase):
    def _claimed_job(self, project, item_status=ItemStatus.WORKING):
        item = self._item(project, status=item_status)
        job = self._job(project, item=item)
        return Command().claim_next_job()

    def test_successful_run_marks_done(self):
        job = self._claimed_job(self.project_a)
        Command().process_job(job, timeout=30, cli_command='true')

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.DONE)
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(job.error_text, '')

    def test_nonzero_exit_marks_failed_and_captures_stderr(self):
        job = self._claimed_job(self.project_a)
        Command().process_job(
            job, timeout=30, cli_command='echo "boom" >&2; exit 3',
        )

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('boom', job.error_text)
        self.assertIsNotNone(job.finished_at)

    def test_nonzero_exit_releases_item_from_working(self):
        job = self._claimed_job(self.project_a, item_status=ItemStatus.WORKING)
        Command().process_job(job, timeout=30, cli_command='exit 1')

        job.item.refresh_from_db()
        self.assertEqual(job.item.status, ItemStatus.BACKLOG)

    def test_timeout_marks_failed(self):
        job = self._claimed_job(self.project_a)

        with patch.object(Command, '_run_cli', side_effect=subprocess.TimeoutExpired('cmd', 1)):
            Command().process_job(job, timeout=1, cli_command='sleep 10')

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('timeout', job.error_text.lower())

    def test_launch_failure_marks_failed(self):
        job = self._claimed_job(self.project_a)

        with patch.object(Command, '_run_cli', side_effect=OSError('no such binary')):
            Command().process_job(job, timeout=30, cli_command='whatever')

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('no such binary', job.error_text)

    def test_job_id_exported_to_cli_env(self):
        job = self._claimed_job(self.project_a)
        # Fail only if the env var isn't set, proving it is passed through.
        Command().process_job(
            job, timeout=30,
            cli_command='test "$CLAUDE_QUEUE_JOB_ID" = "%d"' % job.pk,
        )
        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.DONE)


class CrashRecoveryTests(ClaudeWorkerTestBase):
    def test_recovers_running_job_with_dead_pid_on_this_host(self):
        import socket
        job = self._job(
            self.project_a,
            status=ClaudeQueueJobStatus.RUNNING,
            worker_host=socket.gethostname(),
            worker_pid=999_999_999,  # not a live pid
            started_at=timezone.now(),
        )
        job.item.status = ItemStatus.WORKING
        job.item.save(update_fields=['status'])

        cmd = Command()
        cmd.stdout = StringIO()
        cmd.recover_orphans(timeout=1800)

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('Crash recovery', job.error_text)
        job.item.refresh_from_db()
        self.assertEqual(job.item.status, ItemStatus.BACKLOG)

    def test_does_not_recover_job_with_live_pid(self):
        import socket
        job = self._job(
            self.project_a,
            status=ClaudeQueueJobStatus.RUNNING,
            worker_host=socket.gethostname(),
            worker_pid=os.getpid(),  # this test process is alive
            started_at=timezone.now(),
        )

        cmd = Command()
        cmd.stdout = StringIO()
        cmd.recover_orphans(timeout=1800)

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.RUNNING)

    def test_recovers_stale_job_beyond_timeout(self):
        # No pid info, but running far longer than the timeout allows.
        job = self._job(
            self.project_a,
            status=ClaudeQueueJobStatus.RUNNING,
            started_at=timezone.now() - timezone.timedelta(seconds=4000),
        )

        cmd = Command()
        cmd.stdout = StringIO()
        cmd.recover_orphans(timeout=1800)

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)

    def test_recovers_running_job_without_owner(self):
        job = self._job(
            self.project_a,
            status=ClaudeQueueJobStatus.RUNNING,
            started_at=timezone.now(),
        )

        cmd = Command()
        cmd.stdout = StringIO()
        cmd.recover_orphans(timeout=1800)

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)


class OnceModeTests(ClaudeWorkerTestBase):
    def test_once_processes_a_single_job(self):
        from django.core.management import call_command

        item = self._item(self.project_a)
        job = self._job(self.project_a, item=item)

        out = StringIO()
        call_command('run_claude_worker', '--once', '--cli-command', 'true', stdout=out)

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.DONE)

    def test_once_with_no_jobs_is_a_noop(self):
        from django.core.management import call_command

        out = StringIO()
        call_command('run_claude_worker', '--once', stdout=out)
        self.assertIn('No eligible job', out.getvalue())
