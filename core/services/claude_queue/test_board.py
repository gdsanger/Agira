"""Tests for the derived board state of queue jobs."""

from unittest.mock import PropertyMock, patch

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
        # PR closed without a merge: nothing left to merge.
        self.assertEqual(
            b.derive_board_state(self.job(pr_number=1, pr_state='closed')), b.DONE)
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

    def test_resolved_review_findings_leave_the_attention_columns(self):
        from core.models import ItemStatus
        rv = dict(kind=ClaudeQueueJobKind.REVIEW)
        followup = Item.objects.create(
            title='F', description='d', project=self.project, type=self.type)
        job = self.job(review_verdict='deviations', review_followup_item=followup, **rv)
        self.assertEqual(b.derive_board_state(job), b.REVIEW_DEVIATION_FOLLOWUP)
        followup.status = ItemStatus.CLOSED
        followup.save()
        job = ClaudeQueueJob.objects.select_related('item', 'review_followup_item').get(pk=job.pk)
        self.assertEqual(b.derive_board_state(job), b.DONE)

        unclear = self.job(review_verdict='unclear', **rv)
        self.assertEqual(b.derive_board_state(unclear), b.UNCERTAIN)
        unclear.review_overridden_at = timezone.now()
        self.assertEqual(b.derive_board_state(unclear), b.DONE)

        dev = self.job(review_verdict='deviations', **rv)
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        dev = ClaudeQueueJob.objects.select_related('item').get(pk=dev.pk)
        self.assertEqual(b.derive_board_state(dev), b.DONE)

    def test_can_override_review(self):
        rv = dict(kind=ClaudeQueueJobKind.REVIEW)
        self.assertTrue(self.job(review_verdict='unclear', **rv).can_override_review)
        self.assertFalse(self.job(review_verdict='pass', **rv).can_override_review)
        self.assertFalse(self.job().can_override_review)

    def test_acknowledged_hints_move_review_to_done(self):
        job = self.job(kind=ClaudeQueueJobKind.REVIEW, review_verdict='pass')
        with patch.object(ClaudeQueueJob, 'review_hint_count', new_callable=PropertyMock,
                          return_value=2):
            self.assertTrue(job.can_acknowledge_hints)
            self.assertEqual(b.derive_board_state(job), b.REVIEW_PASS_HINTS)
            job.review_hints_acknowledged_at = timezone.now()
            self.assertFalse(job.can_acknowledge_hints)
            self.assertEqual(b.derive_board_state(job), b.DONE)

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
        # Card carries the action menu with the merge action.
        self.assertContains(r, 'Merge hinterlegen')
        r = self.client.get(reverse('claude-queue-jobs') + '?view=list')
        self.assertNotContains(r, 'cqb-col-')
        self.assertContains(r, 'Current step')
        # HTMX poll keeps the board.
        r = self.client.get(reverse('claude-queue-jobs'), HTTP_HX_REQUEST='true')
        self.assertContains(r, 'cqb-col-queued')

    def test_unclear_review_card_offers_override_and_quiet_columns_are_flagged(self):
        ClaudeQueueJob.objects.create(
            item=self.item, project=self.project, status=S.DONE,
            kind=ClaudeQueueJobKind.REVIEW, review_verdict='unclear')
        r = self.client.get(reverse('claude-queue-jobs'))
        self.assertContains(r, 'Trotz Befunden schließen')
        self.assertContains(r, 'cqb-col is-quiet')

    def test_list_pagination_links_keep_list_view(self):
        for _ in range(25):
            ClaudeQueueJob.objects.create(item=self.item, project=self.project, status=S.DONE)
        r = self.client.get(reverse('claude-queue-jobs') + '?view=list')
        self.assertContains(r, '?page=2')
        self.assertContains(r, '&view=list">Next')


class AcknowledgeHintsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='u', password='pw', email='u@e.com')
        self.user.name = 'U'
        self.user.active = True
        self.user.role = 'Agent'
        self.user.save()
        self.client.login(username='u', password='pw')
        self.project = Project.objects.create(name='P')
        t = ItemType.objects.create(key='bug', name='Bug')
        self.item = Item.objects.create(title='I', description='d', project=self.project, type=t)
        self.job = ClaudeQueueJob.objects.create(
            item=self.item, project=self.project, status=S.DONE,
            kind=ClaudeQueueJobKind.REVIEW, review_verdict='pass')

    def test_acknowledge_is_idempotent_and_logged_once(self):
        from core.models import Activity
        from core.services.claude_queue.ack_hints import acknowledge_hints
        url = reverse('claude-queue-job-ack-hints', args=[self.job.pk])
        with patch.object(ClaudeQueueJob, 'review_hint_count', new_callable=PropertyMock,
                          return_value=1):
            self.assertEqual(self.client.post(url).status_code, 200)
            self.assertEqual(self.client.post(url).status_code, 200)
            self.job.refresh_from_db()
            self.assertIsNotNone(self.job.review_hints_acknowledged_at)
            self.assertEqual(self.job.review_hints_acknowledged_by, self.user)
            self.assertFalse(acknowledge_hints(self.job, self.user))
        self.assertEqual(
            Activity.objects.filter(verb='claudequeuejob.review_hints_acknowledged').count(), 1)

    def test_review_without_hints_is_refused(self):
        url = reverse('claude-queue-job-ack-hints', args=[self.job.pk])
        self.assertEqual(self.client.post(url).status_code, 400)
        self.job.refresh_from_db()
        self.assertIsNone(self.job.review_hints_acknowledged_at)

    def test_menu_offers_merge_for_review_with_open_pr_and_ack_for_hints(self):
        self.job.pr_number = 7
        self.job.pr_state = 'open'
        self.job.save()
        with patch.object(ClaudeQueueJob, 'review_hint_count', new_callable=PropertyMock,
                          return_value=1):
            r = self.client.get(reverse('claude-queue-jobs'))
        self.assertContains(r, 'Merge hinterlegen')
        self.assertContains(r, 'Hinweise gelesen')
