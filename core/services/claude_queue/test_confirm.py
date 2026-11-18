"""Tests for manually confirming a "Ggf. unvollständig" run (#1292)."""

from django.urls import reverse

from core.models import (
    ClaudeQueueJobStatus,
    CommentKind,
    ItemComment,
    User,
)
from core.models import Activity
from core.services.claude_queue.confirm import ConfirmCompleteError, confirm_complete
from core.services.claude_queue.orchestration import (
    ADVANCE_WAITING,
    SUB_SUCCESS,
    SUB_WAITING_MERGE,
    advance_epic,
    sub_job_state,
)
from core.services.claude_queue.test_orchestration import OrchestrationTestBase

REASON = 'Manuell geprüft, Umsetzung vollständig; rote Tests waren schon auf main rot'


class ConfirmCompleteTests(OrchestrationTestBase):

    def setUp(self):
        super().setUp()
        self.user = User.objects.create_user(
            username='rev', email='rev@example.com', name='Rev', password='x',
        )
        self.node = self._epic_node()
        advance_epic(self.node)
        self.entry = self._finish(
            self._entry(self.node, self.data_model), uncertain=True,
        )
        self.node.error_text = 'Claude meldet rote Tests …'
        self.node.save(update_fields=['error_text'])

    def test_can_confirm_only_when_done_and_uncertain(self):
        self.assertTrue(self.entry.can_confirm_complete)
        self.assertFalse(self.node.can_confirm_complete)
        other = self._entry(self.node, self.logic)
        self.assertFalse(other.can_confirm_complete)

    def test_reason_is_optional(self):
        self.assertTrue(confirm_complete(self.entry, self.user, ''))
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.completion_uncertain)
        self.assertEqual(self.entry.completion_confirmed_reason, '')
        comment = ItemComment.objects.get(item=self.data_model)
        self.assertNotIn('Begründung', comment.body)

    def test_merged_pr_chain_continues_and_documents(self):
        confirm_complete(self.entry, self.user, REASON)
        self.entry.refresh_from_db()
        self.assertFalse(self.entry.completion_uncertain)
        self.assertEqual(
            self.entry.completion_uncertain_reason, 'Claude spricht von Hintergrund-Job',
        )
        self.assertEqual(self.entry.completion_confirmed_reason, REASON)
        self.assertEqual(self.entry.completion_confirmed_by, self.user)
        self.assertIsNotNone(self.entry.completion_confirmed_at)
        self.assertEqual(sub_job_state(self.entry), SUB_SUCCESS)

        comment = ItemComment.objects.get(item=self.data_model)
        self.assertEqual(comment.kind, CommentKind.NOTE)
        self.assertIn(REASON, comment.body)
        self.assertIn(f'#{self.entry.pk}', comment.body)
        self.assertEqual(Activity.objects.filter(
            verb='claudequeuejob.completion_confirmed').count(), 1)

        # advanced directly: next sub-issue released, block hint cleared
        self.assertEqual(
            self._entry(self.node, self.logic).status, ClaudeQueueJobStatus.QUEUED,
        )
        self.node.refresh_from_db()
        self.assertEqual(self.node.error_text, '')

    def test_unmerged_pr_waits_instead_of_halting(self):
        self.data_model.external_mappings.all().delete()
        confirm_complete(self.entry, self.user, REASON)
        self.entry.refresh_from_db()
        self.assertEqual(sub_job_state(self.entry), SUB_WAITING_MERGE)
        self.assertEqual(advance_epic(self.node), ADVANCE_WAITING)

    def test_double_confirm_creates_no_duplicates(self):
        self.assertTrue(confirm_complete(self.entry, self.user, REASON))
        self.assertFalse(confirm_complete(self.entry, self.user, REASON))
        self.assertEqual(ItemComment.objects.filter(item=self.data_model).count(), 1)
        self.assertEqual(Activity.objects.filter(
            verb='claudequeuejob.completion_confirmed').count(), 1)

    def test_epic_node_is_refused(self):
        with self.assertRaises(ConfirmCompleteError):
            confirm_complete(self.node, self.user, REASON)

    def test_view_confirms_once_without_reason(self):
        self.client.force_login(self.user)
        url = reverse('claude-queue-job-confirm-complete', args=[self.entry.pk])
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.client.post(url, {'reason': REASON}).status_code, 200)
        self.assertEqual(ItemComment.objects.filter(item=self.data_model).count(), 1)
        self.assertEqual(self.client.get(url).status_code, 405)

    def test_view_rejects_epic_node_and_anonymous(self):
        url = reverse('claude-queue-job-confirm-complete', args=[self.node.pk])
        self.assertNotEqual(self.client.post(url, {'reason': REASON}).status_code, 200)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(url, {'reason': REASON}).status_code, 400)
