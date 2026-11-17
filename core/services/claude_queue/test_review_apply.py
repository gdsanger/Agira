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


class ApplyReviewResultTests(TestCase):
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
        self.assertEqual(f.parent, self.epic)
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
