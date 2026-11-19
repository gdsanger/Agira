import json

from django.test import TestCase

from core.models import (
    ClaudeQueueJob, ClaudeQueueJobKind, ClaudeQueueJobStatus, CommentKind,
    CommentVisibility, ExternalIssueKind, ExternalIssueMapping, Item,
    ItemComment, ItemRelation, ItemStatus, ItemStatusChange, ItemType, Project,
)
from core.models import Activity
from core.services.claude_queue.review_apply import apply_review_result

PR_URL = 'https://github.com/acme/repo-a/pull/7'
ORIGIN_DESC = 'Baue X.\n- [ ] Kriterium A\n\n<!-- claude-queue:git-workflow-hint -->\n---\nHINT'


def _verdict(**over):
    data = {
        'verdict': 'pass',
        'summary': 'Alles erfüllt.',
        'criteria': [
            {'text': 'A', 'status': 'met', 'evidence': 'core/x.py:10'},
            {'text': 'B', 'status': 'accepted_deviation', 'evidence': 'PR-Begründung Y'},
        ],
        'deviations': [],
    }
    data.update(over)
    return json.dumps(data)


DEVIATIONS = dict(
    verdict='deviations',
    criteria=[
        {'text': 'A', 'status': 'not_met', 'evidence': 'core/x.py:12'},
        {'text': 'B', 'status': 'accepted_deviation', 'evidence': 'PR-Begründung Y'},
    ],
    deviations=[{'title': 'A fehlt', 'description': 'Soll Z tun', 'criterion': 'A'}],
)


class ApplyReviewResultTestsBase(TestCase):
    def setUp(self):
        self.type = ItemType.objects.create(key='bug', name='Bug')
        self.project = Project.objects.create(name='P', github_owner='acme', github_repo='repo-a')
        self.epic = Item.objects.create(project=self.project, title='Epic', type=self.type)
        self.item = Item.objects.create(
            project=self.project, parent=self.epic, title='Origin', type=self.type,
            status=ItemStatus.INTEGRATED, description=ORIGIN_DESC,
        )

    def _pr(self, **kw):
        return ExternalIssueMapping.objects.create(
            item=self.item, github_id=1, number=7, kind=ExternalIssueKind.PR,
            state='closed', html_url=PR_URL, merge_commit_sha='abc123', **kw,
        )

    def _job(self, report, **kw):
        return ClaudeQueueJob.objects.create(
            item=self.item, project=self.project, kind=ClaudeQueueJobKind.REVIEW,
            status=ClaudeQueueJobStatus.RUNNING, review_report=report, **kw,
        )

    def _comments(self):
        return ItemComment.objects.filter(item=self.item)


class ApplyReviewResultTests(ApplyReviewResultTestsBase):

    def test_pass_closes_item_with_comment_and_no_followup(self):
        self._pr()
        job = self._job(_verdict())
        res = apply_review_result(job)

        self.assertEqual(res.outcome, 'closed')
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.CLOSED)
        self.assertTrue(ItemStatusChange.objects.filter(item=self.item, to_status='Closed').exists())
        c = self._comments().get()
        self.assertEqual(c.kind, CommentKind.AI_GENERATED)
        self.assertEqual(c.visibility, CommentVisibility.INTERNAL)
        self.assertIn(PR_URL, c.body)
        self.assertIn('akzeptierte Abweichung', c.body)
        self.assertEqual(Item.objects.count(), 2)
        job.refresh_from_db()
        self.assertIsNone(job.review_followup_item)
        self.assertTrue(Activity.objects.filter(verb='claudequeuejob.review_applied').exists())

    def test_job_597_redundant_deviation_on_accepted_criterion_closes(self):
        # All criteria met/accepted; the same accepted deviation is also
        # (redundantly) listed in ``deviations`` -> pass, no follow-up.
        self._pr()
        job = self._job(_verdict(
            verdict='deviations',
            deviations=[{'title': 'Abweichung', 'description': 'D', 'criterion': 'B'}],
        ))
        res = apply_review_result(job)

        self.assertEqual(res.outcome, 'closed')
        self.assertIsNone(res.followup)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.CLOSED)
        self.assertEqual(Item.objects.count(), 2)

    def test_followup_lists_only_not_met_criteria(self):
        self._pr()
        data = dict(DEVIATIONS)
        data['deviations'] = DEVIATIONS['deviations'] + [
            {'title': 'Redundant', 'description': 'x', 'criterion': 'B'},
        ]
        res = apply_review_result(self._job(_verdict(**data)))

        self.assertEqual(res.outcome, 'followup')
        self.assertEqual(Item.objects.count(), 3)
        self.assertIn('A fehlt', res.followup.description)
        self.assertNotIn('### 2.', res.followup.description)
        self.assertNotIn('Redundant', res.comment.body)

    def test_pass_with_not_met_is_unclear_without_close_or_followup(self):
        self._pr()
        job = self._job(_verdict(
            criteria=[{'text': 'A', 'status': 'not_met', 'evidence': ''}],
        ))
        res = apply_review_result(job)

        self.assertEqual(res.outcome, 'manual')
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.INTEGRATED)
        self.assertEqual(Item.objects.count(), 2)

    def test_followup_requester_is_codex_with_its_primary_organisation(self):
        from core.models import Organisation, User, UserOrganisation

        org = Organisation.objects.create(name='ISARTec', short='ISAR')
        codex = User.objects.create(username='cx', email='cx@example.com', name='Codex')
        UserOrganisation.objects.create(user=codex, organisation=org, is_primary=True)
        self._pr()
        job = self._job(_verdict(**DEVIATIONS), provider='openai')
        apply_review_result(job)

        f = Item.objects.get(pk=job.review_followup_item_id)
        self.assertEqual(f.requester, codex)
        self.assertEqual(f.organisation, org)
        self.assertIsNone(f.parent)

    def test_deviations_create_single_self_contained_followup(self):
        self._pr()
        job = self._job(_verdict(**DEVIATIONS))
        res = apply_review_result(job)

        self.assertEqual(res.outcome, 'followup')
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.INTEGRATED)
        f = Item.objects.get(pk=job.review_followup_item_id)
        self.assertEqual(f.title, 'Folge zu PR #7: Origin – Abweichungen aus Review')
        self.assertEqual(f.status, ItemStatus.BACKLOG)
        self.assertEqual(f.type, self.type)
        self.assertEqual(f.project, self.project)
        self.assertIsNone(f.parent)                          # epic is not inherited
        self.assertEqual(f.requester.name, 'Claude Code')
        self.assertIn(PR_URL, f.description)
        self.assertIn('acme/repo-a#7', f.description)
        self.assertIn('Kriterium A', f.description)          # original task inline
        self.assertNotIn('HINT', f.description)
        self.assertIn('core/x.py:12', f.description)         # evidence
        self.assertIn('nicht erneut umsetzen', f.description)
        self.assertIn('PR-Begründung Y', f.description)
        # no Agira reference as source
        for text in (f.title, f.description):
            self.assertNotIn(f'#{self.item.pk} ', text)
            self.assertNotIn(f'/items/{self.item.pk}', text)
        self.assertTrue(ItemRelation.objects.filter(from_item=f, to_item=self.item).exists())
        self.assertIn('Folge-Issue', self._comments().get().body)

    def test_deviations_without_pr_url_behave_like_unclear(self):
        job = self._job(_verdict(**DEVIATIONS))
        res = apply_review_result(job)

        self.assertEqual(res.outcome, 'manual')
        self.assertEqual(Item.objects.count(), 2)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.INTEGRATED)
        job.refresh_from_db()
        self.assertTrue(job.completion_uncertain)
        self.assertIn('Manuelle Prüfung nötig', self._comments().get().body)

    def test_unclear_verdict_neither_closes_nor_follows_up(self):
        self._pr()
        job = self._job('kein json')
        res = apply_review_result(job)

        self.assertEqual(res.outcome, 'manual')
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.INTEGRATED)
        self.assertEqual(Item.objects.count(), 2)
        self.assertIn('Manuelle Prüfung nötig', self._comments().get().body)
        job.refresh_from_db()
        self.assertTrue(job.completion_uncertain)

    def test_completion_uncertain_blocks_close(self):
        self._pr()
        job = self._job(_verdict(), completion_uncertain=True)
        res = apply_review_result(job)

        self.assertEqual(res.outcome, 'manual')
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.INTEGRATED)

    def test_repeated_application_is_idempotent(self):
        self._pr()
        job = self._job(_verdict(**DEVIATIONS))
        apply_review_result(job)
        again = apply_review_result(ClaudeQueueJob.objects.get(pk=job.pk))

        self.assertEqual(again.outcome, 'already_applied')
        self.assertEqual(self._comments().count(), 1)
        self.assertEqual(Item.objects.count(), 3)

    def test_repeated_pass_does_not_duplicate_comment(self):
        self._pr()
        job = self._job(_verdict())
        apply_review_result(job)
        apply_review_result(job)
        self.assertEqual(self._comments().count(), 1)


class ReviewSeverityTests(ApplyReviewResultTestsBase):
    """Severity handling (major blocks, minor is a non-blocking hint)."""

    # Case from PR #42: formal finding "no models.py" although the issue says
    # the app has no models.
    MODELS_MINOR = dict(
        verdict='deviations',
        criteria=[
            {'text': 'A', 'status': 'not_met', 'evidence': 'apps/uisclient/'},
            {'text': 'B', 'status': 'met', 'evidence': 'core/y.py:1'},
        ],
        deviations=[{
            'title': 'models.py fehlt', 'description': 'Issue sagt selbst: keine Modelle',
            'criterion': 'A', 'severity': 'minor',
        }],
    )

    def test_only_minor_closes_with_hints_and_no_followup(self):
        self._pr()
        job = self._job(_verdict(**self.MODELS_MINOR))
        res = apply_review_result(job)

        self.assertEqual(res.outcome, 'closed')
        self.assertIsNone(res.followup)
        self.assertEqual(Item.objects.count(), 2)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.CLOSED)
        self.assertIn('Hinweise (nicht blockierend)', res.comment.body)
        self.assertIn('models.py fehlt', res.comment.body)
        self.assertIn('apps/uisclient/', res.comment.body)
        self.assertEqual(job.review_hint_count, 0)  # verdict not stored yet
        job.review_verdict = 'pass'
        self.assertEqual(job.review_hint_count, 1)

    def test_major_creates_followup_with_only_major(self):
        self._pr()
        data = dict(self.MODELS_MINOR)
        data['criteria'] = [
            {'text': 'A', 'status': 'not_met', 'evidence': 'x'},
            {'text': 'B', 'status': 'not_met', 'evidence': 'y'},
        ]
        data['deviations'] = self.MODELS_MINOR['deviations'] + [
            {'title': 'B fehlt', 'description': 'd', 'criterion': 'B', 'severity': 'major'},
        ]
        res = apply_review_result(self._job(_verdict(**data)))

        self.assertEqual(res.outcome, 'followup')
        self.assertIn(PR_URL, res.followup.description)
        self.assertIn('B fehlt', res.followup.description)
        self.assertNotIn('models.py fehlt', res.followup.description)
        self.assertIn('models.py fehlt', res.comment.body)

    def test_missing_or_invalid_severity_counts_as_major(self):
        for sev in (None, 'bogus'):
            with self.subTest(sev=sev):
                dev = {'title': 'A fehlt', 'description': 'd', 'criterion': 'A'}
                if sev:
                    dev['severity'] = sev
                from core.services.claude_queue.review import parse_review_verdict
                v = parse_review_verdict(_verdict(
                    verdict='deviations',
                    criteria=[{'text': 'A', 'status': 'not_met', 'evidence': ''}],
                    deviations=[dev],
                ))
                self.assertEqual(v.verdict, 'deviations')
                self.assertEqual(len(v.deviations), 1)
                self.assertEqual(v.hints, [])
