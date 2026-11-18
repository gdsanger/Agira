"""Tests for the Codex provider (#1298): args, env, stream parser, errors."""

import json
import os
import subprocess
import tempfile
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from core.management.commands.run_claude_worker import Command
from core.models import (
    AgentProvider,
    ClaudeCredentialSource,
    ClaudeQueueJob,
    ClaudeQueueJobStatus,
    Item,
    ItemStatus,
    ItemType,
    Project,
    User,
)
from core.services.claude_queue.credentials import MissingOpenAICredential
from core.services.claude_queue.providers import CodexProvider, get_provider


def _stream(*events):
    return [json.dumps(e) for e in events]


SUCCESS = _stream(
    {'type': 'thread.started', 'thread_id': 'th-1'},
    {'type': 'turn.started'},
    {'type': 'item.started', 'item': {'id': 'i1', 'type': 'command_execution', 'command': 'ls'}},
    {'type': 'item.completed', 'item': {'id': 'i1', 'type': 'command_execution', 'command': 'ls'}},
    {'type': 'item.completed', 'item': {'id': 'i2', 'type': 'agent_message', 'text': 'Fertig.\nTESTS OK'}},
    {'type': 'turn.completed',
     'usage': {'input_tokens': 100, 'cached_input_tokens': 40, 'output_tokens': 10}},
)


class CodexProviderBase(TestCase):
    def setUp(self):
        self.provider = CodexProvider()
        t = ItemType.objects.create(key='bug', name='Bug')
        self.project = Project.objects.create(name='P', github_owner='acme', github_repo='r')
        self.item = Item.objects.create(project=self.project, title='I', type=t, status=ItemStatus.WORKING)
        self.user = User.objects.create(username='u', name='U', email='u@x.de')
        self.job = ClaudeQueueJob.objects.create(
            item=self.item, project=self.project, provider=AgentProvider.OPENAI,
            model='gpt-6.2-astra', auth_user=self.user,
        )


class RegistryAndArgsTests(CodexProviderBase):
    def test_registry(self):
        self.assertIsInstance(get_provider('openai'), CodexProvider)

    @override_settings(CODEX_CLI_BIN='codex')
    def test_implementation_args(self):
        args = self.provider.build_args(self.job)
        self.assertEqual(args[:3], ['codex', 'exec', '--json'])
        self.assertEqual(args[args.index('-m') + 1], 'gpt-6.2-astra')
        self.assertIn('--dangerously-bypass-approvals-and-sandbox', args)
        self.assertEqual(args[-1], '-')  # prompt via stdin

    def test_review_args_are_read_only(self):
        self.job.kind = 'review'
        args = self.provider.build_args(self.job)
        self.assertIn('read-only', args)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)


class EnvTests(CodexProviderBase):
    def _env(self, **settings_kw):
        with tempfile.TemporaryDirectory() as tmp, \
                override_settings(REPO_BASE_DIR=tmp, **settings_kw):
            return self.provider.build_env(self.job, '/tmp/pr.md', auth_mode='api_key', timeout=10)

    def test_foreign_vars_removed_and_shared_key_used(self):
        host = {
            'OPENAI_API_KEY': 'sk-host-env', 'CODEX_API_KEY': 'sk-foreign',
            'OPENAI_BASE_URL': 'http://evil', 'OPENAI_ORG_ID': 'org', 'CODEX_HOME': '/x',
        }
        with patch.dict(os.environ, host):
            env = self._env(OPENAI_API_KEY='sk-shared')
        self.assertEqual(env['CODEX_API_KEY'], 'sk-shared')
        self.assertEqual(env['OPENAI_API_KEY'], 'sk-shared')
        self.assertNotIn('OPENAI_BASE_URL', env)
        self.assertNotIn('OPENAI_ORG_ID', env)
        self.assertNotEqual(env['CODEX_HOME'], '/x')
        self.assertEqual(env['PR_BODY_FILE'], '/tmp/pr.md')
        self.job.refresh_from_db()
        self.assertEqual(self.job.auth_credential_source, ClaudeCredentialSource.SHARED)

    def test_personal_key_wins_and_source_is_user(self):
        with patch.object(User, 'openai_credential_for', return_value='sk-user'):
            env = self._env(OPENAI_API_KEY='sk-shared')
        self.assertEqual(env['CODEX_API_KEY'], 'sk-user')
        self.job.refresh_from_db()
        self.assertEqual(self.job.auth_credential_source, ClaudeCredentialSource.USER)

    def test_no_key_raises(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('OPENAI_API_KEY', None)
            with self.assertRaises(MissingOpenAICredential):
                self._env(OPENAI_API_KEY='')


class PrepareCheckoutTests(TestCase):
    def _repo(self, tmp, claude_md=True):
        subprocess.run(['git', 'init', '-q', tmp], check=True)
        if claude_md:
            (Path(tmp) / 'CLAUDE.md').write_text('rules')

    def test_agents_md_symlink_untracked_and_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp)
            provider = CodexProvider()
            provider.prepare_checkout(tmp)
            provider.prepare_checkout(tmp)  # idempotent
            agents = Path(tmp) / 'AGENTS.md'
            self.assertTrue(agents.is_symlink())
            self.assertEqual(agents.read_text(), 'rules')
            subprocess.run(['git', 'add', '-A'], cwd=tmp, check=True)
            staged = subprocess.run(
                ['git', 'diff', '--cached', '--name-only'], cwd=tmp,
                capture_output=True, text=True, check=True,
            ).stdout.split()
            self.assertEqual(staged, ['CLAUDE.md'])

    def test_existing_agents_md_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp)
            (Path(tmp) / 'AGENTS.md').write_text('own')
            CodexProvider().prepare_checkout(tmp)
            self.assertFalse((Path(tmp) / 'AGENTS.md').is_symlink())

    def test_without_claude_md_nothing_happens(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._repo(tmp, claude_md=False)
            CodexProvider().prepare_checkout(tmp)
            self.assertFalse((Path(tmp) / 'AGENTS.md').exists())


class StreamParserTests(CodexProviderBase):
    def test_success(self):
        in_flight = set()
        result = self.provider.parse_stream(self.job, SUCCESS, in_flight)
        self.assertTrue(result['saw_result'])
        self.assertFalse(result['is_error'])
        self.assertEqual(result['session_id'], 'th-1')
        self.assertEqual(result['result_text'], 'Fertig.\nTESTS OK')
        self.assertEqual(in_flight, set())
        self.job.refresh_from_db()
        self.assertEqual(
            (self.job.session_id, self.job.num_turns, self.job.input_tokens,
             self.job.cached_input_tokens, self.job.output_tokens),
            ('th-1', 1, 100, 40, 10),
        )
        self.assertIsNone(self.job.total_cost_usd)

    def test_tool_in_flight_while_command_runs(self):
        in_flight = set()
        self.provider.parse_stream(self.job, SUCCESS[:3], in_flight)
        self.assertEqual(in_flight, {'i1'})

    def test_progress_line_for_command(self):
        self.provider.parse_stream(self.job, SUCCESS[:3], set())
        self.job.refresh_from_db()
        self.assertEqual(self.job.progress_text, 'command: ls')

    def test_usage_is_summed_over_turns(self):
        turn = {'type': 'turn.completed', 'usage': {'input_tokens': 5, 'output_tokens': 1}}
        result = self.provider.parse_stream(self.job, _stream(turn, turn))
        self.assertEqual(result['num_turns'], 2)
        self.job.refresh_from_db()
        self.assertEqual((self.job.input_tokens, self.job.output_tokens), (10, 2))

    def test_turn_failed_is_error(self):
        result = self.provider.parse_stream(self.job, _stream(
            {'type': 'thread.started', 'thread_id': 't'},
            {'type': 'turn.failed', 'error': {'message': 'model not found'}},
        ))
        self.assertTrue(result['is_error'])
        self.assertTrue(result['saw_result'])
        self.assertEqual(result['result_text'], 'model not found')

    def test_error_event_without_turn_is_error(self):
        result = self.provider.parse_stream(
            self.job, _stream({'type': 'error', 'message': 'boom'}) + ['garbage'],
        )
        self.assertTrue(result['is_error'])
        self.assertFalse(result['saw_result'])
        self.assertEqual(result['result_text'], 'boom')

    def test_transient_error_before_completed_turn_is_ignored(self):
        result = self.provider.parse_stream(self.job, _stream(
            {'type': 'error', 'message': 'Reconnecting... 1/5'},
            {'type': 'item.completed', 'item': {'id': 'm', 'type': 'agent_message', 'text': 'ok'}},
            {'type': 'turn.completed', 'usage': {}},
        ))
        self.assertFalse(result['is_error'])
        self.assertEqual(result['result_text'], 'ok')

    def test_no_result_event(self):
        result = self.provider.parse_stream(self.job, SUCCESS[:2])
        self.assertFalse(result['saw_result'])
        self.assertFalse(result['is_error'])


class ErrorClassificationTests(CodexProviderBase):
    def _err(self, text, **kw):
        return {'is_error': True, 'result_text': text, 'stderr': '', 'returncode': 1, **kw}

    def test_rate_limit_with_relative_reset(self):
        result = self._err('Rate limit reached for gpt-6.2-sol. Please try again in 6m30s.')
        self.assertTrue(self.provider.is_limit_error(result))
        self.assertFalse(self.provider.is_auth_error(result))
        reset = self.provider.parse_limit_reset(result)
        delta = (reset - timezone.now()).total_seconds()
        self.assertTrue(380 < delta <= 391)

    def test_limit_without_hint_has_no_reset(self):
        result = self._err('429 Too Many Requests')
        self.assertTrue(self.provider.is_limit_error(result))
        self.assertIsNone(self.provider.parse_limit_reset(result))

    def test_insufficient_quota_is_not_a_limit(self):
        result = self._err('You exceeded your current quota (insufficient_quota)')
        self.assertFalse(self.provider.is_limit_error(result))
        self.assertTrue(self.provider.is_auth_error(result))
        self.assertIn('kein temporäres Limit', self.provider.auth_error_message(result, self.job))

    def test_invalid_key_is_auth_error(self):
        result = self._err('', stderr='401 Unauthorized: Incorrect API key provided')
        self.assertTrue(self.provider.is_auth_error(result))
        self.job.auth_credential_source = ClaudeCredentialSource.USER
        self.assertIn('persönliche API-Key', self.provider.auth_error_message(result, self.job))

    def test_success_mentioning_limit_is_not_an_error(self):
        result = {'is_error': False, 'returncode': 0, 'result_text': 'rate limit docs', 'stderr': ''}
        self.assertFalse(self.provider.is_limit_error(result))
        self.assertFalse(self.provider.is_auth_error(result))


class WorkerProviderSelectionTests(CodexProviderBase):
    """process_job picks the provider from ``job.provider`` and parks on a limit."""

    def _run(self, run_cli, **job_kw):
        ClaudeQueueJob.objects.filter(pk=self.job.pk).update(
            status=ClaudeQueueJobStatus.QUEUED, **job_kw,
        )
        job = Command().claim_next_job()
        seen = {}

        def fake(self_, job, *a, **k):
            seen['provider'] = self_.provider.name
            return run_cli()

        with patch.object(Command, '_prepare_checkout', return_value='/tmp/repo'), \
                patch.object(Command, '_create_branch_and_pr', return_value=('fix/x', 'sha')), \
                patch.object(Command, '_commit_uncommitted_work'), \
                patch.object(Command, '_push_branch'), \
                patch.object(Command, '_update_pr_body'), \
                patch.object(Command, '_is_empty_diff', return_value=False), \
                patch.object(Command, '_detect_completion_uncertain', return_value=None), \
                patch.object(Command, '_mark_pr_ready'), \
                patch.object(Command, '_run_cli', autospec=True, side_effect=fake), \
                override_settings(OPENAI_API_KEY='sk-x'):
            Command().process_job(job, timeout=30, idle_timeout=5)
        self.job.refresh_from_db()
        return seen

    def _ok(self, **kw):
        return {'session_id': 's', 'num_turns': 1, 'total_cost_usd': None, 'is_error': False,
                'result_text': 'Done.', 'saw_result': True, 'returncode': 0, 'stderr': '', **kw}

    def test_openai_job_completes_with_codex_provider(self):
        seen = self._run(self._ok)
        self.assertEqual(seen['provider'], 'openai')
        self.assertEqual(self.job.status, ClaudeQueueJobStatus.DONE)
        self.assertEqual(self.job.auth_mode, 'api_key')

    def test_openai_limit_parks_job_with_relative_reset(self):
        self._run(lambda: self._ok(
            is_error=True, returncode=1, result_text='Rate limit reached. Try again in 10m.',
        ))
        self.assertEqual(self.job.status, ClaudeQueueJobStatus.WAITING_LIMIT)
        delta = (self.job.limit_reset_at - timezone.now()).total_seconds()
        self.assertTrue(500 < delta <= 601)

    def test_openai_auth_error_fails(self):
        self._run(lambda: self._ok(is_error=True, returncode=1, result_text='invalid_api_key'))
        self.assertEqual(self.job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('OpenAI-Authentifizierung', self.job.error_text)

    def test_openai_no_result_event_fails(self):
        self._run(lambda: self._ok(saw_result=False))
        self.assertEqual(self.job.status, ClaudeQueueJobStatus.FAILED)
        self.assertIn('Codex exited without', self.job.error_text)

    def test_missing_openai_key_fails_before_checkout(self):
        ClaudeQueueJob.objects.filter(pk=self.job.pk).update(status=ClaudeQueueJobStatus.QUEUED)
        job = Command().claim_next_job()
        with patch.object(Command, '_prepare_checkout') as prep, \
                patch.dict(os.environ, {}, clear=False), \
                override_settings(OPENAI_API_KEY=''):
            os.environ.pop('OPENAI_API_KEY', None)
            Command().process_job(job, timeout=30, idle_timeout=5)
        prep.assert_not_called()
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, ClaudeQueueJobStatus.FAILED)
