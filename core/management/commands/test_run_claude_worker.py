"""
Tests for the Claude queue worker command (run_claude_worker).

Covers the two hard guarantees from the issue:

* Two queued jobs of the *same* project never run in parallel.
* Jobs of *different* projects may run in parallel.

plus the timeout / error end-states and crash recovery.
"""

import json
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


def _ok_result(**overrides):
    """A successful Claude result dict as returned by ``_run_cli``."""
    result = {
        'session_id': 'sess-123',
        'num_turns': 4,
        'total_cost_usd': '0.1234',
        'is_error': False,
        'result_text': 'Done.',
        'saw_result': True,
        'returncode': 0,
        'stderr': '',
    }
    result.update(overrides)
    return result


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
    """The git/PR/Claude steps are patched here; each is unit-tested on its own.

    These tests exercise the process_job orchestration: which result drives the
    job to done vs failed, and item release on failure.
    """

    def _claimed_job(self, project, item_status=ItemStatus.WORKING):
        item = self._item(project, status=item_status)
        self._job(project, item=item)
        return Command().claim_next_job()

    def _run(self, job, run_cli=None, timeout=30):
        """Run process_job with the side-effecting steps stubbed out."""
        run_cli = run_cli if run_cli is not None else (lambda *a, **k: _ok_result())
        with patch.object(Command, '_prepare_checkout', return_value='/tmp/repo'), \
                patch.object(Command, '_create_branch_and_pr', return_value='fix/x-1'), \
                patch.object(Command, '_push_branch'), \
                patch.object(Command, '_run_cli', side_effect=run_cli):
            Command().process_job(job, timeout=timeout, idle_timeout=5)

    def test_successful_run_marks_done_and_persists_result(self):
        job = self._claimed_job(self.project_a)
        self._run(job)

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.DONE)
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(job.error_text, '')

    def test_is_error_result_marks_failed(self):
        job = self._claimed_job(self.project_a)
        self._run(job, run_cli=lambda *a, **k: _ok_result(
            is_error=True, result_text='exploded',
        ))

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('exploded', job.error_text)
        self.assertIsNotNone(job.finished_at)

    def test_nonzero_exit_marks_failed_and_captures_stderr(self):
        job = self._claimed_job(self.project_a)
        self._run(job, run_cli=lambda *a, **k: _ok_result(
            returncode=3, saw_result=False, result_text='', stderr='boom',
        ))

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('boom', job.error_text)

    def test_missing_result_event_marks_failed(self):
        job = self._claimed_job(self.project_a)
        self._run(job, run_cli=lambda *a, **k: _ok_result(
            saw_result=False, result_text='',
        ))

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('result event', job.error_text)

    def test_failure_releases_item_from_working(self):
        job = self._claimed_job(self.project_a, item_status=ItemStatus.WORKING)
        self._run(job, run_cli=lambda *a, **k: _ok_result(is_error=True))

        job.item.refresh_from_db()
        self.assertEqual(job.item.status, ItemStatus.BACKLOG)

    def test_timeout_marks_failed(self):
        job = self._claimed_job(self.project_a)
        self._run(
            job, timeout=1,
            run_cli=lambda *a, **k: (_ for _ in ()).throw(
                subprocess.TimeoutExpired('claude', 1)
            ),
        )

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('timeout', job.error_text.lower())

    def test_setup_failure_marks_failed(self):
        job = self._claimed_job(self.project_a)
        with patch.object(Command, '_prepare_checkout',
                          side_effect=RuntimeError('git clone failed')):
            Command().process_job(job, timeout=30, idle_timeout=5)

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('git clone failed', job.error_text)


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
        with patch.object(Command, '_prepare_checkout', return_value='/tmp/repo'), \
                patch.object(Command, '_create_branch_and_pr', return_value='fix/x-1'), \
                patch.object(Command, '_push_branch'), \
                patch.object(Command, '_run_cli', return_value=_ok_result()):
            call_command('run_claude_worker', '--once', '--skip-recovery', stdout=out)

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.DONE)

    def test_once_with_no_jobs_is_a_noop(self):
        from django.core.management import call_command

        out = StringIO()
        call_command('run_claude_worker', '--once', '--skip-recovery', stdout=out)
        self.assertIn('No eligible job', out.getvalue())


class BranchNameTests(ClaudeWorkerTestBase):
    def test_branch_name_is_slugged_and_id_suffixed(self):
        item = self._item(self.project_a)
        item.title = 'Fix the Login Bug!'
        item.save(update_fields=['title'])

        branch = Command()._branch_name(item)
        self.assertEqual(branch, f'fix/fix-the-login-bug-{item.id}')

    def test_branch_name_falls_back_when_title_unsluggable(self):
        item = self._item(self.project_a)
        item.title = '!!!'
        item.save(update_fields=['title'])

        branch = Command()._branch_name(item)
        self.assertEqual(branch, f'fix/item-{item.id}')


class StreamParsingTests(ClaudeWorkerTestBase):
    """Unit tests for _consume_stream against synthetic stream-json lines."""

    def _job_with_item(self):
        item = self._item(self.project_a)
        return self._job(self.project_a, item=item)

    def test_init_event_sets_session_id(self):
        job = self._job_with_item()
        lines = [json.dumps({
            'type': 'system', 'subtype': 'init',
            'session_id': 'sess-abc', 'mcp_servers': [{'name': 'x'}],
        })]
        Command()._consume_stream(job, iter(lines))

        job.refresh_from_db()
        self.assertEqual(job.session_id, 'sess-abc')

    def test_assistant_tool_use_advances_progress(self):
        job = self._job_with_item()
        lines = [json.dumps({
            'type': 'assistant',
            'message': {'content': [
                {'type': 'tool_use', 'name': 'Edit',
                 'input': {'file_path': 'core/foo.py'}},
            ]},
        })]
        Command()._consume_stream(job, iter(lines))

        job.refresh_from_db()
        self.assertEqual(job.progress_text, 'Edit: core/foo.py')

    def test_result_event_persists_cost_and_turns(self):
        job = self._job_with_item()
        lines = [json.dumps({
            'type': 'result', 'subtype': 'success', 'is_error': False,
            'num_turns': 7, 'total_cost_usd': 0.42,
            'session_id': 'sess-final', 'result': 'All done.',
        })]
        result = Command()._consume_stream(job, iter(lines))

        self.assertTrue(result['saw_result'])
        self.assertFalse(result['is_error'])
        job.refresh_from_db()
        self.assertEqual(job.num_turns, 7)
        self.assertEqual(str(job.total_cost_usd), '0.420000')
        self.assertEqual(job.session_id, 'sess-final')
        self.assertEqual(job.progress_text, 'All done.')

    def test_error_result_is_flagged(self):
        job = self._job_with_item()
        lines = [json.dumps({
            'type': 'result', 'is_error': True, 'num_turns': 1,
            'total_cost_usd': 0.01, 'result': 'boom',
        })]
        result = Command()._consume_stream(job, iter(lines))
        self.assertTrue(result['is_error'])

    def test_non_json_noise_is_ignored(self):
        job = self._job_with_item()
        lines = [
            'not json at all',
            '',
            json.dumps({'type': 'result', 'is_error': False,
                        'num_turns': 1, 'total_cost_usd': 0.0, 'result': 'ok'}),
        ]
        result = Command()._consume_stream(job, iter(lines))
        self.assertTrue(result['saw_result'])


class DraftPrTests(ClaudeWorkerTestBase):
    def test_open_draft_pr_writes_job_fields(self):
        from unittest.mock import MagicMock
        from core.models import ExternalIssueKind, ExternalIssueMapping

        item = self._item(self.project_a)
        job = self._job(self.project_a, item=item)

        mapping = ExternalIssueMapping.objects.create(
            item=item, github_id=555, number=42, kind=ExternalIssueKind.PR,
            state='open', html_url='https://github.com/o/r/pull/42',
        )
        fake_service = MagicMock()
        fake_service.create_draft_pr_for_item.return_value = mapping

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service):
            Command()._open_draft_pr(job, 'fix/x-1', '/tmp/repo')

        job.refresh_from_db()
        self.assertEqual(job.pr_number, 42)
        self.assertEqual(job.pr_url, 'https://github.com/o/r/pull/42')
