"""Tests for the derived board state of queue jobs."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    ClaudeQueueJob, ClaudeQueueJobKind, ClaudeQueueJobStatus as S, Item,
    ItemType, Project, User,
)
from core.services.claude_queue import board as b

REPORT_WITH_HINT = ''


class BoardStateTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name='P')
        self.type = ItemType.objects.create(key='bug', name='Bug')
        self.item = Item.objects.create(
            title='I', description='d', project=self.project, type=self.type)

    def job(self, **kw):
        kw.setdefault('status', S.DONE)
        return ClaudeQueueJob.objects.create(item=self.item, project=self.project, **kw)

    def test_lifecycle_states(self):
        self.assertEqual(b.derive_board_state(self.job(status=S.QUEUED)), b.QUEUED)
        self.assertEqual(b.derive_board_state(self.job(status=S.BLOCKED)), b.QUEUED)
        self.assertEqual(b.derive_board_state(self.job(status=S.RUNNING)), b.RUNNING)
        self.assertEqual(b.derive_board_state(self.job(status=S.WAITING_LIMIT)), b.RUNNING)
        self.assertEqual(b.derive_board_state(self.job(status=S.FAILED)), b.FAILED)
        self.assertEqual(b.derive_board_state(self.job(status=S.CANCELLED)), b.FAILED)

    def test_coding_done_states(self):
        self.assertEqual(b.derive_board_state(self.job()), b.DONE)
        self.assertEqual(
            b.derive_board_state(self.job(pr_number=1, pr_state='open')), b.MERGE_MISSING)
        self.assertEqual(
            b.derive_board_state(self.job(pr_number=1, pr_state='merged')), b.DONE)
        self.assertEqual(
            b.derive_board_state(self.job(completion_uncertain=True, pr_number=1)), b.UNCERTAIN)
        confirmed = self.job(completion_uncertain=True, pr_number=1,
                             completion_confirmed_at=timezone.now())
        self.assertEqual(b.derive_board_state(confirmed), b.MERGE_MISSING)

    def test_review_states(self):
        rv = dict(kind=ClaudeQueueJobKind.REVIEW)
        self.assertEqual(b.derive_board_state(
            self.job(review_verdict='pass', **rv), hint_count=0), b.REVIEW_PASS)
        self.assertEqual(b.derive_board_state(
            self.job(review_verdict='pass', **rv), hint_count=2), b.REVIEW_PASS_HINTS)
        self.assertEqual(b.derive_board_state(
            self.job(review_verdict='deviations', **rv)), b.REVIEW_DEVIATION)
        self.assertEqual(b.derive_board_state(
            self.job(review_verdict='deviations', review_followup_item=self.item, **rv)),
            b.REVIEW_DEVIATION_FOLLOWUP)
        self.assertEqual(b.derive_board_state(
            self.job(review_verdict='unclear', **rv)), b.UNCERTAIN)
        # A review's PR merge state is irrelevant.
        self.assertEqual(b.derive_board_state(
            self.job(review_verdict='pass', pr_number=3, pr_state='open', **rv), hint_count=0),
            b.REVIEW_PASS)

    def test_build_board_caps_finished_columns_only(self):
        jobs = [self.job() for _ in range(4)] + [self.job(status=S.QUEUED) for _ in range(4)]
        board = b.build_board(jobs, cap=2)
        self.assertEqual(len(board.cards[b.DONE]), 2)
        self.assertEqual(board.hidden[b.DONE], 2)
        self.assertEqual(len(board.cards[b.QUEUED]), 4)


class BoardViewTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(username='u', password='pw', email='u@e.com')
        user.name = 'U'
        user.active = True
        user.role = 'Agent'
        user.save()
        self.client.login(username='u', password='pw')
        self.project = Project.objects.create(name='P')
        t = ItemType.objects.create(key='bug', name='Bug')
        self.item = Item.objects.create(title='Board item', description='d',
                                        project=self.project, type=t)

    def test_board_is_default_and_list_still_available(self):
        ClaudeQueueJob.objects.create(item=self.item, project=self.project,
                                      status=S.DONE, pr_number=5, pr_state='open')
        r = self.client.get(reverse('claude-queue-jobs'))
        self.assertContains(r, 'cqb-col-merge_missing')
        self.assertContains(r, 'Board item')
        r = self.client.get(reverse('claude-queue-jobs') + '?view=list')
        self.assertNotContains(r, 'cqb-col-')
        self.assertContains(r, 'Current step')
        # HTMX poll keeps the board.
        r = self.client.get(reverse('claude-queue-jobs'), HTTP_HX_REQUEST='true')
        self.assertContains(r, 'cqb-col-queued')
