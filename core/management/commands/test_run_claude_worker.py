"""
Tests for the Claude queue worker command (run_claude_worker).

Covers the two hard guarantees from the issue:

* Two queued jobs of the *same* project (repo) never run in parallel — and
  neither do two different projects that share a repo.
* Jobs of *different* projects/repos may run in parallel.

plus the timeout / error end-states and crash recovery.
"""

import json
import os
import subprocess
import tempfile
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from core.management.commands.run_claude_worker import (
    Command,
    DEFAULT_LIMIT_BACKOFF_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
)
from core.models import (
    ClaudeQueueJob,
    ClaudeQueueJobAuthMode,
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
        self.project_a = Project.objects.create(
            name='Project A', github_owner='acme', github_repo='repo-a',
        )
        self.project_b = Project.objects.create(
            name='Project B', github_owner='acme', github_repo='repo-b',
        )

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
        # repo, so a second worker can't grab the 2nd-oldest queued job.
        head = self._job(self.project_a)
        self._job(self.project_a)  # newer, must not be a candidate
        self._job(self.project_a)  # newer, must not be a candidate

        older = ClaudeQueueJob.objects.filter(
            project__github_owner=head.project.github_owner,
            project__github_repo=head.project.github_repo,
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

    def test_projects_sharing_a_repo_are_locked_together(self):
        # Two projects that (accidentally) point at the same github_owner/
        # github_repo must not run at once — they would share a checkout.
        shared = Project.objects.create(
            name='Project A2', github_owner='acme', github_repo='repo-a',
        )
        self._job(self.project_a, status=ClaudeQueueJobStatus.RUNNING)
        queued_shared = self._job(shared)
        queued_b = self._job(self.project_b)

        claimed = Command().claim_next_job()

        # Only project B (a different repo) is eligible.
        self.assertEqual(claimed.pk, queued_b.pk)
        queued_shared.refresh_from_db()
        self.assertEqual(queued_shared.status, ClaudeQueueJobStatus.QUEUED)


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
                patch.object(Command, '_create_branch_and_pr', return_value=('fix/x-1', 'bootstrap-sha')), \
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
        self.assertFalse(job.completion_uncertain)

    def test_uncertain_completion_still_marks_done_but_flags_job(self):
        job = self._claimed_job(self.project_a)
        with patch.object(Command, '_detect_completion_uncertain',
                           return_value='Leerer PR: keine Änderungen über den Start-Commit hinaus.'):
            self._run(job)

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.DONE)
        self.assertTrue(job.completion_uncertain)
        self.assertIn('Leerer PR', job.completion_uncertain_reason)

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

    def test_default_timeout_is_sixty_minutes(self):
        self.assertEqual(DEFAULT_TIMEOUT_SECONDS, 3600)

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
            started_at=timezone.now() - timedelta(seconds=4000),
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
                patch.object(Command, '_create_branch_and_pr', return_value=('fix/x-1', 'bootstrap-sha')), \
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


class CompletionUncertainTests(ClaudeWorkerTestBase):
    """Unit tests for the post-run outcome/prose detection (issue #850)."""

    def _init_repo(self, tmp_path):
        subprocess.run(['git', 'init'], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=tmp_path, check=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=tmp_path, check=True)
        (Path(tmp_path) / 'README.md').write_text('hello\n')
        subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'init'], cwd=tmp_path, check=True, capture_output=True)
        sha = subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=tmp_path, check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        return sha

    def test_is_empty_diff_true_when_no_commits_since_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            self.assertTrue(Command()._is_empty_diff(tmp_path, bootstrap_sha))

    def test_is_empty_diff_false_after_a_real_change(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            (Path(tmp_path) / 'feature.py').write_text('print("hi")\n')
            subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True, capture_output=True)
            subprocess.run(['git', 'commit', '-m', 'add feature'], cwd=tmp_path,
                            check=True, capture_output=True)

            self.assertFalse(Command()._is_empty_diff(tmp_path, bootstrap_sha))

    def test_is_empty_diff_false_on_missing_repo(self):
        # Unreadable/missing checkout must not be mistaken for "empty" (no diff).
        self.assertFalse(Command()._is_empty_diff('/no/such/repo', 'deadbeef'))

    def test_find_background_marker_matches_english_and_german_phrases(self):
        find = Command()._find_background_marker
        self.assertEqual(find('I moved this to a background task.'), 'background')
        self.assertEqual(find('Ich habe das im Hintergrund weiterlaufen lassen.'), 'im hintergrund')
        self.assertEqual(find('Want me to proceed with the migration?'), 'want me to')
        self.assertEqual(find('Soll ich mit dem nächsten Schritt fortfahren?'), 'soll ich')

    def test_find_background_marker_matches_trailing_question(self):
        self.assertEqual(
            Command()._find_background_marker('Alles bereit, aber wie soll es weitergehen?'),
            'endet mit einer Frage',
        )

    def test_find_background_marker_none_for_clean_summary(self):
        self.assertIsNone(Command()._find_background_marker('Implemented the fix and pushed the commit.'))

    def test_find_background_marker_none_for_empty_text(self):
        self.assertIsNone(Command()._find_background_marker(''))
        self.assertIsNone(Command()._find_background_marker(None))

    def test_detect_completion_uncertain_prefers_outcome_over_prose(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            reason = Command()._detect_completion_uncertain(
                tmp_path, bootstrap_sha, 'Implemented everything, all good.',
            )
            self.assertIn('Leerer PR', reason)

    def test_detect_completion_uncertain_falls_back_to_prose(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            (Path(tmp_path) / 'feature.py').write_text('print("hi")\n')
            subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True, capture_output=True)
            subprocess.run(['git', 'commit', '-m', 'add feature'], cwd=tmp_path,
                            check=True, capture_output=True)

            reason = Command()._detect_completion_uncertain(
                tmp_path, bootstrap_sha,
                'Partially done — want me to continue with the rest?',
            )
            self.assertIn('Warten/Hintergrund', reason)

    def test_detect_completion_uncertain_none_for_a_clean_run(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            (Path(tmp_path) / 'feature.py').write_text('print("hi")\n')
            subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True, capture_output=True)
            subprocess.run(['git', 'commit', '-m', 'add feature'], cwd=tmp_path,
                            check=True, capture_output=True)

            reason = Command()._detect_completion_uncertain(
                tmp_path, bootstrap_sha, 'Implemented the fix and pushed the commit.',
            )
            self.assertIsNone(reason)


class CommitUncommittedWorkTests(ClaudeWorkerTestBase):
    """Unit tests for _commit_uncommitted_work: rescue a Claude run's uncommitted edits."""

    def _init_repo(self, tmp_path):
        subprocess.run(['git', 'init'], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=tmp_path, check=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=tmp_path, check=True)
        (Path(tmp_path) / 'README.md').write_text('hello\n')
        subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'init'], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '--allow-empty', '-m', 'bootstrap'],
                        cwd=tmp_path, check=True, capture_output=True)
        return subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=tmp_path, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def test_commits_uncommitted_changes(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            (Path(tmp_path) / 'feature.py').write_text('print("hi")\n')
            job = self._job(self.project_a)

            rescued = Command()._commit_uncommitted_work(tmp_path, job)

            self.assertTrue(rescued)
            self.assertFalse(Command()._is_empty_diff(tmp_path, bootstrap_sha))
            subject = subprocess.run(
                ['git', 'log', '-1', '--format=%s'], cwd=tmp_path,
                capture_output=True, text=True, check=True,
            ).stdout.strip()
            self.assertIn('auto-commit uncommitted work', subject)
            self.assertIn(f'#{job.item_id}', subject)

    def test_ignores_claude_settings_local_json(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            claude_dir = Path(tmp_path) / '.claude'
            claude_dir.mkdir()
            (claude_dir / 'settings.local.json').write_text('{"a": 1}\n')
            job = self._job(self.project_a)

            rescued = Command()._commit_uncommitted_work(tmp_path, job)

            self.assertFalse(rescued)
            self.assertTrue(Command()._is_empty_diff(tmp_path, bootstrap_sha))
            status = subprocess.run(
                ['git', 'status', '--porcelain'], cwd=tmp_path,
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertIn('.claude', status)

    def test_commits_real_change_while_excluding_settings_file(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            self._init_repo(tmp_path)
            claude_dir = Path(tmp_path) / '.claude'
            claude_dir.mkdir()
            (claude_dir / 'settings.local.json').write_text('{"a": 1}\n')
            (Path(tmp_path) / 'feature.py').write_text('print("hi")\n')
            job = self._job(self.project_a)

            rescued = Command()._commit_uncommitted_work(tmp_path, job)

            self.assertTrue(rescued)
            changed = subprocess.run(
                ['git', 'show', '--stat', '--format=', 'HEAD'], cwd=tmp_path,
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertIn('feature.py', changed)
            self.assertNotIn('settings.local.json', changed)

    def test_no_op_on_clean_tree(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            self._init_repo(tmp_path)
            job = self._job(self.project_a)

            self.assertFalse(Command()._commit_uncommitted_work(tmp_path, job))

    def test_swallows_git_errors_on_bad_repo_dir(self):
        job = self._job(self.project_a)
        self.assertFalse(Command()._commit_uncommitted_work('/no/such/repo', job))


class EmptyRunHandlingTests(ClaudeWorkerTestBase):
    """Process-level tests: a run with no committed changes must not look like success."""

    def _init_repo(self, tmp_path):
        subprocess.run(['git', 'init'], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=tmp_path, check=True)
        subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=tmp_path, check=True)
        (Path(tmp_path) / 'README.md').write_text('hello\n')
        subprocess.run(['git', 'add', '.'], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '-m', 'init'], cwd=tmp_path, check=True, capture_output=True)
        subprocess.run(['git', 'commit', '--allow-empty', '-m', 'bootstrap'],
                        cwd=tmp_path, check=True, capture_output=True)
        return subprocess.run(
            ['git', 'rev-parse', 'HEAD'], cwd=tmp_path, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def _claimed_job(self, project, item_status=ItemStatus.WORKING):
        item = self._item(project, status=item_status)
        self._job(project, item=item)
        return Command().claim_next_job()

    def _run(self, job, tmp_path, bootstrap_sha, run_cli):
        with patch.object(Command, '_prepare_checkout', return_value=tmp_path), \
                patch.object(Command, '_create_branch_and_pr',
                             return_value=('fix/x-1', bootstrap_sha)), \
                patch.object(Command, '_push_branch'), \
                patch.object(Command, '_run_cli', side_effect=run_cli):
            Command().process_job(job, timeout=30, idle_timeout=5)

    def test_true_empty_run_is_marked_failed_not_done(self):
        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            job = self._claimed_job(self.project_a)

            self._run(job, tmp_path, bootstrap_sha, run_cli=lambda *a, **k: _ok_result(
                result_text='Implemented everything, all good.',
            ))

            job.refresh_from_db()
            self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
            self.assertIn('Kein Code committet', job.error_text)
            self.assertTrue(job.completion_uncertain)
            self.assertIn('Leerer PR', job.completion_uncertain_reason)
            job.item.refresh_from_db()
            self.assertEqual(job.item.status, ItemStatus.BACKLOG)

    def test_true_empty_run_pr_body_does_not_show_success_summary(self):
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            job = self._claimed_job(self.project_a)
            job.pr_number = 42
            job.save(update_fields=['pr_number'])
            fake_service = MagicMock()

            with patch('core.services.github.service.GitHubService',
                       return_value=fake_service):
                self._run(job, tmp_path, bootstrap_sha, run_cli=lambda *a, **k: _ok_result(
                    result_text='Implemented everything, all good.',
                ))

            call_kwargs = fake_service.update_pr_body.call_args[1]
            self.assertIn('Kein Code committet', call_kwargs['body'])
            self.assertNotIn('## Claude Summary', call_kwargs['body'])
            self.assertNotIn('Implemented everything', call_kwargs['body'])

    def test_uncommitted_changes_are_rescued_and_run_still_marked_done(self):
        def leave_uncommitted(job, repo_dir, timeout, idle_timeout, pr_body_file, **kwargs):
            (Path(repo_dir) / 'feature.py').write_text('print("hi")\n')
            return _ok_result(result_text='Implemented the fix.')

        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            job = self._claimed_job(self.project_a)

            self._run(job, tmp_path, bootstrap_sha, run_cli=leave_uncommitted)

            job.refresh_from_db()
            self.assertEqual(job.status, ClaudeQueueJobStatus.DONE)
            self.assertFalse(job.completion_uncertain)
            log = subprocess.run(
                ['git', 'log', '--format=%s'], cwd=tmp_path,
                capture_output=True, text=True, check=True,
            ).stdout
            self.assertIn('auto-commit uncommitted work', log)

    def test_settings_local_json_only_is_still_a_true_empty_run(self):
        def leave_only_settings(job, repo_dir, timeout, idle_timeout, pr_body_file, **kwargs):
            claude_dir = Path(repo_dir) / '.claude'
            claude_dir.mkdir(parents=True, exist_ok=True)
            (claude_dir / 'settings.local.json').write_text('{"a": 1}\n')
            return _ok_result(result_text='Nothing to change here.')

        with tempfile.TemporaryDirectory() as tmp_path:
            bootstrap_sha = self._init_repo(tmp_path)
            job = self._claimed_job(self.project_a)

            self._run(job, tmp_path, bootstrap_sha, run_cli=leave_only_settings)

            job.refresh_from_db()
            self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
            self.assertIn('Kein Code committet', job.error_text)


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
        fake_service.find_open_pr_for_branch.return_value = None
        fake_service.create_draft_pr_for_item.return_value = mapping

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service):
            Command()._open_draft_pr(job, 'fix/x-1', '/tmp/repo')

        job.refresh_from_db()
        self.assertEqual(job.pr_number, 42)
        self.assertEqual(job.pr_url, 'https://github.com/o/r/pull/42')
        fake_service.create_draft_pr_for_item.assert_called_once()

    def test_open_draft_pr_reuses_existing_open_pr_without_creating(self):
        """A retry hits the same deterministic branch — reuse its open PR."""
        from unittest.mock import MagicMock
        from core.models import ExternalIssueKind, ExternalIssueMapping

        item = self._item(self.project_a)
        job = self._job(self.project_a, item=item, branch_name='fix/x-1')

        mapping = ExternalIssueMapping.objects.create(
            item=item, github_id=555, number=42, kind=ExternalIssueKind.PR,
            state='open', html_url='https://github.com/o/r/pull/42',
        )
        fake_service = MagicMock()
        fake_service.find_open_pr_for_branch.return_value = mapping

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service):
            Command()._open_draft_pr(job, 'fix/x-1', '/tmp/repo')

        job.refresh_from_db()
        self.assertEqual(job.pr_number, 42)
        self.assertEqual(job.pr_url, 'https://github.com/o/r/pull/42')
        self.assertIn('Reusing existing PR #42', job.progress_text)
        fake_service.create_draft_pr_for_item.assert_not_called()

    def test_open_draft_pr_falls_back_to_existing_pr_after_422(self):
        """create_draft_pr_for_item 422s (already exists) -> re-check finds it."""
        from unittest.mock import MagicMock
        from core.models import ExternalIssueKind, ExternalIssueMapping
        from core.services.integrations.errors import IntegrationPermanentError

        item = self._item(self.project_a)
        job = self._job(self.project_a, item=item, branch_name='fix/x-1')

        mapping = ExternalIssueMapping.objects.create(
            item=item, github_id=555, number=42, kind=ExternalIssueKind.PR,
            state='open', html_url='https://github.com/o/r/pull/42',
        )
        fake_service = MagicMock()
        fake_service.find_open_pr_for_branch.side_effect = [None, mapping]
        fake_service.create_draft_pr_for_item.side_effect = IntegrationPermanentError(
            "Client error (HTTP 422): {\"message\":\"Validation Failed\","
            "\"errors\":[{\"message\":\"A pull request already exists for "
            "o:fix/x-1.\"}]}"
        )

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service):
            Command()._open_draft_pr(job, 'fix/x-1', '/tmp/repo')

        job.refresh_from_db()
        self.assertEqual(job.pr_number, 42)
        self.assertEqual(job.pr_url, 'https://github.com/o/r/pull/42')
        self.assertIn('Reusing existing PR #42', job.progress_text)

    def test_open_draft_pr_lookup_failure_still_allows_creation(self):
        """A broken existing-PR lookup must not block the normal create path."""
        from unittest.mock import MagicMock
        from core.models import ExternalIssueKind, ExternalIssueMapping

        item = self._item(self.project_a)
        job = self._job(self.project_a, item=item)

        mapping = ExternalIssueMapping.objects.create(
            item=item, github_id=555, number=42, kind=ExternalIssueKind.PR,
            state='open', html_url='https://github.com/o/r/pull/42',
        )
        fake_service = MagicMock()
        fake_service.find_open_pr_for_branch.side_effect = RuntimeError('boom')
        fake_service.create_draft_pr_for_item.return_value = mapping

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service):
            Command()._open_draft_pr(job, 'fix/x-1', '/tmp/repo')

        job.refresh_from_db()
        self.assertEqual(job.pr_number, 42)
        fake_service.create_draft_pr_for_item.assert_called_once()

    def test_open_draft_pr_raises_when_no_pr_found_anywhere(self):
        """No existing PR and creation fails -> propagate (real job failure)."""
        from unittest.mock import MagicMock

        item = self._item(self.project_a)
        job = self._job(self.project_a, item=item)

        fake_service = MagicMock()
        fake_service.find_open_pr_for_branch.return_value = None
        fake_service.create_draft_pr_for_item.side_effect = RuntimeError(
            'network is down'
        )

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service), \
             patch.object(Command, '_pr_from_gh_fallback', return_value=None):
            with self.assertRaises(RuntimeError):
                Command()._open_draft_pr(job, 'fix/x-1', '/tmp/repo')


class UpdatePrBodyTests(ClaudeWorkerTestBase):
    """_update_pr_body replaces the draft body via GitHubService, not a parallel path."""

    def _job_with_pr(self, pr_number=42):
        item = self._item(self.project_a)
        job = self._job(self.project_a, item=item)
        job.pr_number = pr_number
        job.save(update_fields=['pr_number'])
        return job

    def test_success_body_includes_header_and_summary(self):
        from unittest.mock import MagicMock

        job = self._job_with_pr()
        fake_service = MagicMock()

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service):
            Command()._update_pr_body(job, summary='Implemented the thing.')

        call_kwargs = fake_service.update_pr_body.call_args[1]
        self.assertEqual(call_kwargs['number'], 42)
        self.assertIn('Automated draft PR', call_kwargs['body'])
        self.assertIn('## Claude Summary', call_kwargs['body'])
        self.assertIn('Implemented the thing.', call_kwargs['body'])

    def test_failure_body_includes_header_and_error_not_summary_heading(self):
        from unittest.mock import MagicMock

        job = self._job_with_pr()
        fake_service = MagicMock()

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service):
            Command()._update_pr_body(job, error='Claude reported an error.')

        call_kwargs = fake_service.update_pr_body.call_args[1]
        self.assertIn('Automated draft PR', call_kwargs['body'])
        self.assertIn('Run failed', call_kwargs['body'])
        self.assertIn('Claude reported an error.', call_kwargs['body'])
        self.assertNotIn('## Claude Summary', call_kwargs['body'])

    def test_no_pr_number_skips_update(self):
        from unittest.mock import MagicMock

        item = self._item(self.project_a)
        job = self._job(self.project_a, item=item)  # pr_number left unset
        fake_service = MagicMock()

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service):
            Command()._update_pr_body(job, summary='Should not be sent.')

        fake_service.update_pr_body.assert_not_called()

    def test_body_update_failure_does_not_raise(self):
        from unittest.mock import MagicMock

        job = self._job_with_pr()
        fake_service = MagicMock()
        fake_service.update_pr_body.side_effect = RuntimeError('API down')

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service):
            Command()._update_pr_body(job, summary='fine')  # must not raise

    def test_prefers_structured_pr_body_file_over_summary(self):
        from unittest.mock import MagicMock

        job = self._job_with_pr()
        fake_service = MagicMock()
        pr_body_file = Path(tempfile.gettempdir()) / 'test-pr-body-structured.md'
        structured = (
            "## Zusammenfassung\nDid the thing.\n\n## Änderungen\n"
            "- `a.py` — changed\n\n## Warum / Entscheidungen\n"
            "- nicht X, weil Y\n\n## Test-Hinweise\n- ran tests"
        )
        pr_body_file.write_text(structured)
        try:
            with patch('core.services.github.service.GitHubService',
                       return_value=fake_service):
                Command()._update_pr_body(
                    job, summary='Should be ignored.', pr_body_file=pr_body_file,
                )
        finally:
            pr_body_file.unlink(missing_ok=True)

        call_kwargs = fake_service.update_pr_body.call_args[1]
        self.assertIn('## Zusammenfassung', call_kwargs['body'])
        self.assertIn('## Warum / Entscheidungen', call_kwargs['body'])
        self.assertNotIn('Should be ignored.', call_kwargs['body'])
        self.assertNotIn('## Claude Summary', call_kwargs['body'])

    def test_falls_back_to_summary_when_pr_body_file_missing(self):
        from unittest.mock import MagicMock

        job = self._job_with_pr()
        fake_service = MagicMock()
        missing_file = Path(tempfile.gettempdir()) / 'test-pr-body-does-not-exist.md'

        with patch('core.services.github.service.GitHubService',
                   return_value=fake_service):
            Command()._update_pr_body(
                job, summary='Fallback summary.', pr_body_file=missing_file,
            )

        call_kwargs = fake_service.update_pr_body.call_args[1]
        self.assertIn('## Claude Summary', call_kwargs['body'])
        self.assertIn('Fallback summary.', call_kwargs['body'])

    def test_falls_back_to_summary_when_pr_body_file_empty(self):
        from unittest.mock import MagicMock

        job = self._job_with_pr()
        fake_service = MagicMock()
        empty_file = Path(tempfile.gettempdir()) / 'test-pr-body-empty.md'
        empty_file.write_text('   \n')
        try:
            with patch('core.services.github.service.GitHubService',
                       return_value=fake_service):
                Command()._update_pr_body(
                    job, summary='Fallback summary.', pr_body_file=empty_file,
                )
        finally:
            empty_file.unlink(missing_ok=True)

        call_kwargs = fake_service.update_pr_body.call_args[1]
        self.assertIn('## Claude Summary', call_kwargs['body'])
        self.assertIn('Fallback summary.', call_kwargs['body'])


class PrBodyFileLifecycleTests(ClaudeWorkerTestBase):
    """The worker creates PR_BODY_FILE before the run and removes it afterwards."""

    def _claimed_job(self, project, item_status=ItemStatus.WORKING):
        item = self._item(project, status=item_status)
        self._job(project, item=item)
        return Command().claim_next_job()

    def test_file_created_before_run_and_removed_after(self):
        job = self._claimed_job(self.project_a)
        captured = {}

        def fake_run_cli(job, repo_dir, timeout, idle_timeout, pr_body_file, **kwargs):
            captured['path'] = pr_body_file
            captured['existed_during_run'] = pr_body_file.exists()
            return _ok_result()

        with patch.object(Command, '_prepare_checkout', return_value='/tmp/repo'), \
                patch.object(Command, '_create_branch_and_pr', return_value=('fix/x-1', 'bootstrap-sha')), \
                patch.object(Command, '_push_branch'), \
                patch.object(Command, '_run_cli', side_effect=fake_run_cli):
            Command().process_job(job, timeout=30, idle_timeout=5)

        self.assertTrue(captured['existed_during_run'])
        self.assertFalse(captured['path'].exists())

    def test_file_removed_after_a_failed_run(self):
        job = self._claimed_job(self.project_a)
        captured = {}

        def fake_run_cli(job, repo_dir, timeout, idle_timeout, pr_body_file, **kwargs):
            captured['path'] = pr_body_file
            return _ok_result(is_error=True, result_text='exploded')

        with patch.object(Command, '_prepare_checkout', return_value='/tmp/repo'), \
                patch.object(Command, '_create_branch_and_pr', return_value=('fix/x-1', 'bootstrap-sha')), \
                patch.object(Command, '_push_branch'), \
                patch.object(Command, '_run_cli', side_effect=fake_run_cli):
            Command().process_job(job, timeout=30, idle_timeout=5)

        self.assertFalse(captured['path'].exists())

    def test_structured_body_file_content_flows_into_pr_body(self):
        from unittest.mock import MagicMock

        job = self._claimed_job(self.project_a)
        job.pr_number = 42
        job.save(update_fields=['pr_number'])
        fake_service = MagicMock()

        def fake_run_cli(job, repo_dir, timeout, idle_timeout, pr_body_file, **kwargs):
            pr_body_file.write_text(
                "## Zusammenfassung\nDid it.\n\n## Änderungen\n- `a.py`\n\n"
                "## Warum / Entscheidungen\n- nicht X, weil Y\n\n"
                "## Test-Hinweise\n- ran tests"
            )
            return _ok_result()

        with patch.object(Command, '_prepare_checkout', return_value='/tmp/repo'), \
                patch.object(Command, '_create_branch_and_pr', return_value=('fix/x-1', 'bootstrap-sha')), \
                patch.object(Command, '_push_branch'), \
                patch.object(Command, '_run_cli', side_effect=fake_run_cli), \
                patch('core.services.github.service.GitHubService',
                      return_value=fake_service):
            Command().process_job(job, timeout=30, idle_timeout=5)

        call_kwargs = fake_service.update_pr_body.call_args[1]
        self.assertIn('## Zusammenfassung', call_kwargs['body'])
        self.assertIn('nicht X, weil Y', call_kwargs['body'])
        self.assertNotIn('## Claude Summary', call_kwargs['body'])


class BuildPromptAndEnvTests(ClaudeWorkerTestBase):
    def test_prompt_includes_pr_body_file_instructions(self):
        item = self._item(self.project_a)
        prompt = Command()._build_prompt(item)

        self.assertIn('$PR_BODY_FILE', prompt)
        self.assertIn('## Zusammenfassung', prompt)
        self.assertIn('## Änderungen', prompt)
        self.assertIn('## Warum / Entscheidungen', prompt)
        self.assertIn('## Test-Hinweise', prompt)
        self.assertIn('nicht X, weil Y', prompt)

    def test_build_env_sets_pr_body_file(self):
        job = self._job(self.project_a)
        pr_body_file = Path(tempfile.gettempdir()) / 'claude-pr-body-test.md'

        env = Command()._build_env(job, pr_body_file)

        self.assertEqual(env['PR_BODY_FILE'], str(pr_body_file))

    def test_allowed_tools_includes_write(self):
        from core.management.commands.run_claude_worker import ALLOWED_TOOLS
        self.assertIn('Write', ALLOWED_TOOLS.split(','))


class AuthModeEnvTests(ClaudeWorkerTestBase):
    """The child environment must pick auth per-process, never inherit it."""

    def _env(self, auth_mode, **settings_over):
        job = self._job(self.project_a)
        pr_body_file = Path(tempfile.gettempdir()) / 'claude-pr-body-test.md'
        with override_settings(**settings_over):
            return Command()._build_env(job, pr_body_file, auth_mode=auth_mode)

    def test_oauth_run_strips_global_api_key(self):
        # Even with a globally exported key, an OAuth run must not carry it —
        # otherwise the CLI silently spends pay-per-use credit.
        with patch.dict(os.environ, {'ANTHROPIC_API_KEY': 'sk-global'}):
            env = self._env(
                ClaudeQueueJobAuthMode.OAUTH,
                ANTHROPIC_API_KEY='sk-global',
                CLAUDE_CODE_OAUTH_TOKEN='oauth-tok',
            )
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'], 'oauth-tok')

    def test_oauth_run_without_token_relies_on_host_login(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('CLAUDE_CODE_OAUTH_TOKEN', None)
            env = self._env(
                ClaudeQueueJobAuthMode.OAUTH,
                ANTHROPIC_API_KEY='',
                CLAUDE_CODE_OAUTH_TOKEN='',
            )
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN', env)

    def test_api_key_run_sets_key_and_strips_oauth_token(self):
        with patch.dict(os.environ, {'CLAUDE_CODE_OAUTH_TOKEN': 'oauth-tok'}):
            env = self._env(
                ClaudeQueueJobAuthMode.API_KEY,
                ANTHROPIC_API_KEY='sk-abc',
                CLAUDE_CODE_OAUTH_TOKEN='oauth-tok',
            )
        self.assertEqual(env['ANTHROPIC_API_KEY'], 'sk-abc')
        self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN', env)

    def test_api_key_run_without_key_raises(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ANTHROPIC_API_KEY', None)
            with self.assertRaises(RuntimeError):
                self._env(ClaudeQueueJobAuthMode.API_KEY, ANTHROPIC_API_KEY='')


class LimitDetectionTests(ClaudeWorkerTestBase):
    def test_rate_limit_on_errored_run_is_a_limit(self):
        result = _ok_result(is_error=True, result_text='Claude usage limit reached')
        self.assertTrue(Command()._is_limit_error(result))
        self.assertFalse(Command()._is_auth_error(result))

    def test_limit_wording_in_successful_run_is_not_a_limit(self):
        # Gated on the run erroring: a healthy run mentioning "quota" is fine.
        result = _ok_result(result_text='I reviewed the quota logic, all good.')
        self.assertFalse(Command()._is_limit_error(result))

    def test_expired_token_is_an_auth_error_not_a_limit(self):
        result = _ok_result(
            is_error=True, returncode=1,
            stderr='OAuth token has expired. Please run /login.',
        )
        self.assertTrue(Command()._is_auth_error(result))
        self.assertFalse(Command()._is_limit_error(result))

    def test_parse_limit_reset_from_pipe_epoch(self):
        reset = int((timezone.now() + timedelta(hours=2)).timestamp())
        result = _ok_result(
            is_error=True, result_text=f'Claude AI usage limit reached|{reset}',
        )
        parsed = Command()._parse_limit_reset(result)
        self.assertIsNotNone(parsed)
        self.assertEqual(int(parsed.timestamp()), reset)

    def test_parse_limit_reset_absent_returns_none(self):
        result = _ok_result(is_error=True, result_text='rate limit, try later')
        self.assertIsNone(Command()._parse_limit_reset(result))


class LimitHandlingProcessTests(ClaudeWorkerTestBase):
    """process_job's reactive behaviour when a run hits the subscription limit."""

    def _claimed_job(self, item_status=ItemStatus.WORKING, **job_kwargs):
        item = self._item(self.project_a, status=item_status)
        self._job(self.project_a, item=item, **job_kwargs)
        return Command().claim_next_job()

    def _run(self, job, run_cli, timeout=30):
        with patch.object(Command, '_prepare_checkout', return_value='/tmp/repo'), \
                patch.object(Command, '_create_branch_and_pr', return_value=('fix/x-1', 'sha')), \
                patch.object(Command, '_commit_uncommitted_work'), \
                patch.object(Command, '_push_branch'), \
                patch.object(Command, '_update_pr_body'), \
                patch.object(Command, '_run_cli', side_effect=run_cli):
            Command().process_job(job, timeout=timeout, idle_timeout=5)

    def test_limit_without_flag_parks_in_waiting_limit(self):
        reset = int((timezone.now() + timedelta(hours=1)).timestamp())
        job = self._claimed_job()
        self._run(job, run_cli=lambda *a, **k: _ok_result(
            is_error=True, result_text=f'usage limit reached|{reset}',
        ))

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.WAITING_LIMIT)
        self.assertEqual(int(job.limit_reset_at.timestamp()), reset)
        self.assertEqual(job.error_text, '')  # waiting is not a failure
        self.assertIn('Kontingent', job.progress_text)
        # Item is still being worked on — not released to Backlog.
        job.item.refresh_from_db()
        self.assertEqual(job.item.status, ItemStatus.WORKING)

    def test_limit_without_reset_uses_default_backoff(self):
        job = self._claimed_job()
        before = timezone.now()
        self._run(job, run_cli=lambda *a, **k: _ok_result(
            is_error=True, result_text='rate limit hit, no timestamp',
        ))

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.WAITING_LIMIT)
        delta = (job.limit_reset_at - before).total_seconds()
        self.assertGreater(delta, DEFAULT_LIMIT_BACKOFF_SECONDS - 60)

    @override_settings(ANTHROPIC_API_KEY='sk-fallback')
    def test_limit_with_flag_falls_back_to_api_key_and_completes(self):
        job = self._claimed_job(allow_api_key_fallback=True)
        calls = []

        def run_cli(job, repo_dir, timeout, idle_timeout, pr_body_file, *, auth_mode):
            calls.append(auth_mode)
            if auth_mode == ClaudeQueueJobAuthMode.OAUTH:
                return _ok_result(is_error=True, result_text='usage limit reached')
            return _ok_result(result_text='Done on API key.')

        with patch.object(Command, '_is_empty_diff', return_value=False), \
                patch.object(Command, '_detect_completion_uncertain', return_value=None):
            self._run(job, run_cli=run_cli)

        self.assertEqual(
            calls, [ClaudeQueueJobAuthMode.OAUTH, ClaudeQueueJobAuthMode.API_KEY]
        )
        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.DONE)
        self.assertEqual(job.auth_mode, ClaudeQueueJobAuthMode.API_KEY)

    def test_auth_error_fails_with_actionable_message(self):
        job = self._claimed_job()
        self._run(job, run_cli=lambda *a, **k: _ok_result(
            is_error=True, returncode=1,
            stderr='OAuth token has expired. Please run /login.',
        ))

        job.refresh_from_db()
        self.assertEqual(job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('setup-token', job.error_text)


class WaitingLimitClaimTests(ClaudeWorkerTestBase):
    def test_due_waiting_limit_job_is_reclaimed(self):
        item = self._item(self.project_a, status=ItemStatus.WORKING)
        job = self._job(
            self.project_a, item=item,
            status=ClaudeQueueJobStatus.WAITING_LIMIT,
            limit_reset_at=timezone.now() - timedelta(minutes=1),
        )

        claimed = Command().claim_next_job()

        self.assertIsNotNone(claimed)
        self.assertEqual(claimed.pk, job.pk)
        self.assertEqual(claimed.status, ClaudeQueueJobStatus.RUNNING)
        self.assertIsNone(claimed.limit_reset_at)

    def test_not_yet_due_waiting_limit_job_is_skipped(self):
        item = self._item(self.project_a, status=ItemStatus.WORKING)
        self._job(
            self.project_a, item=item,
            status=ClaudeQueueJobStatus.WAITING_LIMIT,
            limit_reset_at=timezone.now() + timedelta(hours=1),
        )

        self.assertIsNone(Command().claim_next_job())

    def test_waiting_limit_job_with_null_reset_is_due(self):
        item = self._item(self.project_a, status=ItemStatus.WORKING)
        job = self._job(
            self.project_a, item=item,
            status=ClaudeQueueJobStatus.WAITING_LIMIT,
            limit_reset_at=None,
        )

        claimed = Command().claim_next_job()

        self.assertEqual(claimed.pk, job.pk)
