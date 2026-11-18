"""Codex review runs (#1299): read-only args, verdict channel, verdict cases."""

import json
import tempfile

from django.test import override_settings

from core.models import ClaudeQueueJobKind
from core.services.claude_queue.review import (
    VERDICT_DEVIATIONS, VERDICT_JSON_SCHEMA, VERDICT_PASS, VERDICT_UNCLEAR,
    parse_review_verdict,
)
from core.services.claude_queue.review_apply import build_report
from core.services.claude_queue.test_codex_provider import CodexProviderBase


def _answer(**over):
    data = {
        'verdict': 'pass', 'summary': 'ok',
        'criteria': [{'text': 'Kriterium A erfüllt', 'status': 'met', 'evidence': 'x.py:1'}],
        'deviations': [],
    }
    data.update(over)
    return json.dumps(data)


class CodexReviewTests(CodexProviderBase):
    def setUp(self):
        super().setUp()
        self.job.kind = ClaudeQueueJobKind.REVIEW
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.override = override_settings(REPO_BASE_DIR=self.tmp.name, CODEX_HOME='')
        self.override.enable()
        self.addCleanup(self.override.disable)

    def test_review_args_enforce_read_only_and_structured_output(self):
        args = self.provider.build_args(self.job)
        self.assertEqual(args[args.index('-s') + 1], 'read-only')
        self.assertIn('approval_policy=never', args)
        self.assertNotIn('--dangerously-bypass-approvals-and-sandbox', args)
        schema_file = args[args.index('--output-schema') + 1]
        self.assertIn('--output-last-message', args)
        with open(schema_file) as fh:
            self.assertEqual(json.load(fh), VERDICT_JSON_SCHEMA)

    def test_schema_is_strict_and_excludes_unclear(self):
        self.assertFalse(VERDICT_JSON_SCHEMA['additionalProperties'])
        self.assertEqual(
            set(VERDICT_JSON_SCHEMA['required']), set(VERDICT_JSON_SCHEMA['properties']),
        )
        self.assertNotIn('unclear', VERDICT_JSON_SCHEMA['properties']['verdict']['enum'])

    def _run_with_answer(self, file_text, stream_text=''):
        args = self.provider.build_args(self.job)
        if file_text is not None:
            with open(args[args.index('--output-last-message') + 1], 'w') as fh:
                fh.write(file_text)
        return self.provider.review_raw_answer(self.job, {'result_text': stream_text})

    def test_output_last_message_preferred(self):
        self.assertEqual(self._run_with_answer('{"a": 1}', 'stream'), '{"a": 1}')

    def test_fallback_to_stream_text(self):
        self.assertEqual(self._run_with_answer(None, 'stream'), 'stream')

    def test_stale_answer_file_removed_on_new_run(self):
        self._run_with_answer('{"old": 1}')
        self.provider.build_args(self.job)
        self.assertEqual(self.provider.review_raw_answer(self.job, {'result_text': 's'}), 's')

    def test_verdict_pass(self):
        v = parse_review_verdict(self._run_with_answer(_answer()))
        self.assertEqual(v.verdict, VERDICT_PASS)

    def test_verdict_deviations_major(self):
        raw = _answer(
            verdict='deviations',
            criteria=[{'text': 'Kriterium A erfüllt', 'status': 'not_met', 'evidence': ''}],
            deviations=[{'title': 'fehlt', 'description': 'd',
                         'criterion': 'Kriterium A erfüllt', 'severity': 'major'}],
        )
        v = parse_review_verdict(self._run_with_answer(raw))
        self.assertEqual(v.verdict, VERDICT_DEVIATIONS)
        self.assertEqual(len(v.deviations), 1)

    def test_verdict_minor_only_is_pass_with_hints(self):
        raw = _answer(deviations=[{'title': 'Docstring', 'description': '',
                                   'criterion': 'Kriterium A erfüllt', 'severity': 'minor'}])
        v = parse_review_verdict(self._run_with_answer(raw))
        self.assertEqual(v.verdict, VERDICT_PASS)
        self.assertEqual(len(v.hints), 1)
        self.assertEqual(v.deviations, [])

    def test_unreadable_answer_is_unclear(self):
        v = parse_review_verdict(self._run_with_answer('kein json', 'auch nicht'))
        self.assertEqual(v.verdict, VERDICT_UNCLEAR)

    def test_schema_violation_is_unclear(self):
        for raw in (_answer(verdict='unclear'), _answer(criteria='x'),
                    json.dumps({'verdict': 'pass'})):
            v = parse_review_verdict(self._run_with_answer(raw))
            self.assertEqual(v.verdict, VERDICT_UNCLEAR, raw)

    def test_report_names_provider_and_model(self):
        v = parse_review_verdict(_answer())
        report = build_report(self.job, self.item, v, VERDICT_PASS, None, None)
        self.assertIn('OpenAI Codex (gpt-5-codex-mini)', report)
        self.assertIn('## Review – Job', report)
