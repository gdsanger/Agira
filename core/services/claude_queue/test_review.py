import json

from django.test import SimpleTestCase, TestCase

from core.services.claude_queue.review import (
    VERDICT_DEVIATIONS, VERDICT_PASS, VERDICT_UNCLEAR, parse_review_verdict,
)


def _verdict(**over):
    data = {
        'verdict': 'pass',
        'summary': 'Alles erfüllt.',
        'criteria': [
            {'text': 'A', 'status': 'met', 'evidence': 'core/x.py:10'},
            {'text': 'B', 'status': 'accepted_deviation', 'evidence': 'PR #1'},
        ],
        'deviations': [],
    }
    data.update(over)
    return data


DEVIATING = dict(
    verdict='deviations',
    criteria=[{'text': 'A', 'status': 'not_met', 'evidence': ''}],
    deviations=[{'title': 'T', 'description': 'D', 'criterion': 'A'}],
)


class ParseReviewVerdictTests(SimpleTestCase):
    def test_valid_pass(self):
        r = parse_review_verdict(json.dumps(_verdict()))
        self.assertEqual(r.verdict, VERDICT_PASS)
        self.assertEqual(len(r.criteria), 2)
        self.assertEqual(r.criteria[0].evidence, 'core/x.py:10')
        self.assertEqual(r.error, '')

    def test_valid_deviations(self):
        r = parse_review_verdict(json.dumps(_verdict(**DEVIATING)))
        self.assertEqual(r.verdict, VERDICT_DEVIATIONS)
        self.assertEqual(r.deviations[0].title, 'T')
        self.assertEqual(r.deviations[0].criterion, 'A')

    def test_embedded_in_prose(self):
        text = f'Hier mein Urteil:\n{json.dumps(_verdict())}\nGruß'
        self.assertEqual(parse_review_verdict(text).verdict, VERDICT_PASS)

    def test_embedded_in_code_block(self):
        text = f'Ergebnis:\n```json\n{json.dumps(_verdict(), indent=2)}\n```\n'
        self.assertEqual(parse_review_verdict(text).verdict, VERDICT_PASS)

    def test_last_valid_object_wins(self):
        text = json.dumps(_verdict()) + '\nkorrigiert:\n' + json.dumps(_verdict(**DEVIATING))
        self.assertEqual(parse_review_verdict(text).verdict, VERDICT_DEVIATIONS)

    def test_garbage_is_unclear(self):
        for raw in ('', '   ', None, 'kein json', '{kaputt', '[1, 2]', '{"foo": 1}', 42):
            with self.subTest(raw=raw):
                self.assertEqual(parse_review_verdict(raw).verdict, VERDICT_UNCLEAR)

    def test_schema_violations_are_unclear(self):
        cases = [
            _verdict(verdict='unclear'),
            _verdict(verdict='maybe'),
            _verdict(summary=None),
            _verdict(criteria='x'),
            _verdict(criteria=[{'text': 'A', 'status': 'bogus'}]),
            _verdict(criteria=[{'status': 'met'}]),
            _verdict(criteria=['A']),
            _verdict(deviations='x'),
            _verdict(deviations=[{'description': 'no title'}]),
        ]
        for data in cases:
            with self.subTest(data=data):
                r = parse_review_verdict(json.dumps(data))
                self.assertEqual(r.verdict, VERDICT_UNCLEAR)
                self.assertTrue(r.error)

    def test_pass_with_not_met_is_unclear(self):
        data = _verdict(criteria=[{'text': 'A', 'status': 'not_met'}])
        self.assertEqual(parse_review_verdict(json.dumps(data)).verdict, VERDICT_UNCLEAR)

    def test_pass_with_deviations_is_unclear(self):
        data = _verdict(deviations=[{'title': 'T'}])
        self.assertEqual(parse_review_verdict(json.dumps(data)).verdict, VERDICT_UNCLEAR)

    def test_deviations_without_not_met_is_derived_pass(self):
        # The verdict follows the criteria, not the model's verdict field.
        data = _verdict(verdict='deviations')
        self.assertEqual(parse_review_verdict(json.dumps(data)).verdict, VERDICT_PASS)

    def test_redundant_deviation_on_accepted_criterion_is_dropped(self):
        # Regression for job #597.
        data = _verdict(
            verdict='deviations',
            deviations=[{'title': 'Abweichung', 'description': 'D', 'criterion': 'B'}],
        )
        r = parse_review_verdict(json.dumps(data))
        self.assertEqual(r.verdict, VERDICT_PASS)
        self.assertEqual(r.deviations, [])

    def test_deviation_on_met_criterion_is_dropped(self):
        data = _verdict(deviations=[{'title': 'T', 'criterion': ' a '}])
        r = parse_review_verdict(json.dumps(data))
        self.assertEqual(r.verdict, VERDICT_PASS)
        self.assertEqual(r.deviations, [])

    def test_deviation_without_matching_criterion_is_unclear(self):
        for crit in ('', 'gibt es nicht'):
            data = _verdict(deviations=[{'title': 'T', 'criterion': crit}])
            self.assertEqual(parse_review_verdict(json.dumps(data)).verdict, VERDICT_UNCLEAR)

    def test_paraphrased_criterion_is_matched_by_word_overlap(self):
        # Regression for job #640: the model reworded the criterion text.
        data = _verdict(
            verdict='deviations',
            criteria=[
                {'text': 'Vorlage ohne Reports: Verhalten unverändert.', 'status': 'met'},
                {'text': 'Report-Paket: Export/Re-Import erhalten alle Report-Zuordnungen '
                         'inkl. Filter und Dateiname; alte Pakete weiter importierbar.',
                 'status': 'not_met', 'evidence': 'x'},
            ],
            deviations=[{
                'title': 'Paket ohne Filter', 'severity': 'major',
                'criterion': 'Export und Re-Import erhalten alle Report-Zuordnungen '
                             'inklusive Filter und Dateiname.',
            }],
        )
        r = parse_review_verdict(json.dumps(data))
        self.assertEqual(r.verdict, VERDICT_DEVIATIONS)
        self.assertEqual(r.deviations[0].title, 'Paket ohne Filter')
        self.assertTrue(r.deviations[0].criterion.startswith('Report-Paket'))

    def test_minor_deviation_without_matching_criterion_becomes_hint(self):
        data = _verdict(deviations=[
            {'title': 'T', 'criterion': 'gibt es nicht', 'severity': 'minor'},
        ])
        r = parse_review_verdict(json.dumps(data))
        self.assertEqual(r.verdict, VERDICT_PASS)
        self.assertEqual(len(r.hints), 1)
        self.assertEqual(r.deviations, [])

    def test_only_not_met_criteria_remain_as_deviations(self):
        data = _verdict(
            verdict='deviations',
            criteria=[
                {'text': 'A', 'status': 'not_met', 'evidence': 'x'},
                {'text': 'B', 'status': 'accepted_deviation'},
            ],
            deviations=[
                {'title': 'T-B', 'criterion': 'B'},
                {'title': 'T-A', 'criterion': 'A'},
            ],
        )
        r = parse_review_verdict(json.dumps(data))
        self.assertEqual(r.verdict, VERDICT_DEVIATIONS)
        self.assertEqual([d.title for d in r.deviations], ['T-A'])

    def test_not_met_without_deviation_entry_is_synthesised(self):
        data = _verdict(
            verdict='deviations',
            criteria=[{'text': 'A', 'status': 'not_met', 'evidence': 'x'}],
        )
        r = parse_review_verdict(json.dumps(data))
        self.assertEqual(r.verdict, VERDICT_DEVIATIONS)
        self.assertEqual(r.deviations[0].criterion, 'A')

    def test_prompt_contains_deviations_rule(self):
        from core.services.claude_queue.review import REVIEW_RULES
        self.assertIn('ausschließlich', REVIEW_RULES)
        self.assertIn('accepted_deviation', REVIEW_RULES)


class ReviewJobModelTests(TestCase):
    def test_review_kind_and_defaults(self):
        from core.models import ClaudeQueueJob, ClaudeQueueJobKind
        job = ClaudeQueueJob(kind=ClaudeQueueJobKind.REVIEW)
        self.assertTrue(job.is_review)
        self.assertFalse(job.is_epic_node)
        self.assertEqual(job.review_verdict, '')
        self.assertEqual(job.review_report, '')
        self.assertIsNone(job.review_followup_item_id)
