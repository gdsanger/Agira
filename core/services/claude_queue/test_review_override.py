"""Tests for the human review override (#1291): service, view and UI render."""
from django.test import Client, TestCase
from django.urls import reverse

from core.models import (
    Activity, ClaudeQueueJob, ClaudeQueueJobKind, ClaudeQueueJobStatus,
    ClaudeQueueReviewVerdict, CommentKind, CommentVisibility,
    ExternalIssueKind, ExternalIssueMapping, Item, ItemComment, ItemStatus,
    ItemType, Project, User,
)
from core.services.claude_queue.review_override import (
    ReviewOverrideError, overridable_review_job, override_review,
)

PR_URL = 'https://github.com/acme/repo-a/pull/7'
REASON = 'Befund ist pedantisch, wird anderweitig erledigt.'


class ReviewOverrideBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='tester', password='pw', email='t@example.com',
        )
        self.user.name = 'Tina Tester'
        self.user.active = True
        self.user.role = 'Agent'
        self.user.save()
        self.project = Project.objects.create(name='P')
        self.type = ItemType.objects.create(key='bug', name='Bug')
        self.item = self._item(ItemStatus.TESTING)
        ExternalIssueMapping.objects.create(
            item=self.item, github_id=1, number=7, kind=ExternalIssueKind.PR,
            state='open', html_url=PR_URL,
        )

    def _item(self, status, title='Item'):
        return Item.objects.create(
            title=title, description='d', project=self.project,
            type=self.type, status=status,
        )

    def _job(self, verdict=ClaudeQueueReviewVerdict.DEVIATIONS, item=None, **kw):
        return ClaudeQueueJob.objects.create(
            item=item or self.item, project=self.project,
            kind=ClaudeQueueJobKind.REVIEW, status=ClaudeQueueJobStatus.DONE,
            review_verdict=verdict, **kw,
        )


class OverrideServiceTests(ReviewOverrideBase):
    def test_overrides_and_documents(self):
        job = self._job()
        result = override_review(self.item, self.user, REASON)
        self.assertEqual(result.outcome, 'overridden')
        self.item.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.CLOSED)
        self.assertEqual(job.review_overridden_by, self.user)
        self.assertIsNotNone(job.review_overridden_at)
        self.assertEqual(job.review_override_reason, REASON)
        self.assertEqual(job.review_verdict, ClaudeQueueReviewVerdict.DEVIATIONS)
        comment = ItemComment.objects.get(item=self.item, subject='Review-Befund überschrieben')
        self.assertEqual(comment.kind, CommentKind.NOTE)
        self.assertEqual(comment.visibility, CommentVisibility.INTERNAL)
        for needle in (REASON, 'Tina Tester', f'#{job.pk}', 'deviations', PR_URL):
            self.assertIn(needle, comment.body)
        self.assertEqual(Activity.objects.filter(verb='claudequeuejob.review_overridden').count(), 1)

    def test_unclear_is_overridable(self):
        self._job(ClaudeQueueReviewVerdict.UNCLEAR)
        override_review(self.item, self.user, REASON)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.CLOSED)

    def test_short_or_empty_reason_rejected(self):
        self._job()
        for reason in ('', '   ', 'kurz'):
            with self.assertRaises(ReviewOverrideError):
                override_review(self.item, self.user, reason)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.TESTING)
        self.assertFalse(ItemComment.objects.exists())

    def test_not_allowed_for_pass_or_without_review(self):
        with self.assertRaises(ReviewOverrideError):
            override_review(self.item, self.user, REASON)
        self._job(ClaudeQueueReviewVerdict.PASS)
        self.assertIsNone(overridable_review_job(self.item))
        with self.assertRaises(ReviewOverrideError):
            override_review(self.item, self.user, REASON)

    def test_only_latest_review_counts(self):
        self._job()
        self._job(ClaudeQueueReviewVerdict.PASS)
        self.assertIsNone(overridable_review_job(self.item))

    def test_idempotent(self):
        self._job()
        override_review(self.item, self.user, REASON)
        again = override_review(self.item, self.user, REASON)
        self.assertEqual(again.outcome, 'already_overridden')
        self.assertEqual(ItemComment.objects.filter(item=self.item).count(), 1)
        self.assertEqual(Activity.objects.filter(verb='claudequeuejob.review_overridden').count(), 1)

    def test_followup_closed_on_consent(self):
        followup = self._item(ItemStatus.BACKLOG, 'Folge')
        self._job(review_followup_item=followup)
        result = override_review(self.item, self.user, REASON, close_followup=True)
        followup.refresh_from_db()
        self.assertTrue(result.followup_closed)
        self.assertEqual(followup.status, ItemStatus.CLOSED)
        note = ItemComment.objects.get(item=followup)
        self.assertEqual(note.subject, 'Durch Überschreiben des Review-Befunds erledigt')
        self.assertIn(REASON, note.body)

    def test_followup_kept_without_consent(self):
        followup = self._item(ItemStatus.BACKLOG, 'Folge')
        self._job(review_followup_item=followup)
        override_review(self.item, self.user, REASON, close_followup=False)
        followup.refresh_from_db()
        self.assertEqual(followup.status, ItemStatus.BACKLOG)

    def test_followup_in_progress_never_closed(self):
        for status in (ItemStatus.WORKING, ItemStatus.INTEGRATED, ItemStatus.TESTING):
            item = self._item(ItemStatus.TESTING)
            followup = self._item(status, 'Folge')
            self._job(item=item, review_followup_item=followup)
            result = override_review(item, self.user, REASON, close_followup=True)
            followup.refresh_from_db()
            self.assertFalse(result.followup_closed)
            self.assertEqual(followup.status, status)

    def test_followup_with_pr_never_closed(self):
        followup = self._item(ItemStatus.BACKLOG, 'Folge')
        ExternalIssueMapping.objects.create(
            item=followup, github_id=2, number=8, kind=ExternalIssueKind.PR,
            state='open', html_url='https://github.com/acme/repo-a/pull/8',
        )
        self._job(review_followup_item=followup)
        result = override_review(self.item, self.user, REASON, close_followup=True)
        followup.refresh_from_db()
        self.assertFalse(result.followup_closed)
        self.assertEqual(followup.status, ItemStatus.BACKLOG)


class OverrideViewTests(ReviewOverrideBase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.login(username='tester', password='pw')
        self.url = reverse('item-review-override', args=[self.item.id])

    def test_requires_post_and_login(self):
        self._job()
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(Client().post(self.url, {'reason': REASON}).status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.TESTING)

    def test_csrf_enforced(self):
        self._job()
        client = Client(enforce_csrf_checks=True)
        client.login(username='tester', password='pw')
        self.assertEqual(client.post(self.url, {'reason': REASON}).status_code, 403)

    def test_short_reason_rejected(self):
        self._job()
        response = self.client.post(self.url, {'reason': 'kurz'})
        self.assertEqual(response.status_code, 400)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.TESTING)

    def test_double_submit_is_noop(self):
        self._job()
        first = self.client.post(self.url, {'reason': REASON})
        second = self.client.post(self.url, {'reason': REASON})
        self.assertTrue(first.json()['success'])
        self.assertTrue(second.json()['no_change'])
        self.assertEqual(ItemComment.objects.filter(item=self.item).count(), 1)
        self.assertEqual(Activity.objects.filter(verb='claudequeuejob.review_overridden').count(), 1)

    def test_followup_checkbox(self):
        followup = self._item(ItemStatus.BACKLOG, 'Folge')
        self._job(review_followup_item=followup)
        self.client.post(self.url, {'reason': REASON})  # checkbox not sent -> off
        followup.refresh_from_db()
        self.assertEqual(followup.status, ItemStatus.BACKLOG)


class OverrideUiTests(ReviewOverrideBase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.client.login(username='tester', password='pw')

    def _detail(self, item=None):
        return self.client.get(reverse('item-detail', args=[(item or self.item).id]))

    def test_action_visible_only_for_deviations_and_unclear(self):
        self.assertNotContains(self._detail(), 'reviewOverrideModal')
        job = self._job(ClaudeQueueReviewVerdict.PASS)
        self.assertNotContains(self._detail(), 'reviewOverrideModal')
        job.delete()
        for verdict in (ClaudeQueueReviewVerdict.DEVIATIONS, ClaudeQueueReviewVerdict.UNCLEAR):
            job = self._job(verdict)
            response = self._detail()
            self.assertContains(response, 'Trotz Befunden schließen')
            self.assertTrue(response.context['can_review_override'])
            job.delete()

    def test_action_hidden_for_closed_item(self):
        self._job()
        self.item.status = ItemStatus.CLOSED
        self.item.save()
        self.assertNotContains(self._detail(), 'reviewOverrideModal')

    def test_modal_followup_checkbox_and_hint(self):
        followup = self._item(ItemStatus.BACKLOG, 'Folge')
        self._job(review_followup_item=followup)
        self.assertContains(self._detail(), 'Folge-Issue ebenfalls schließen')
        followup.status = ItemStatus.WORKING
        followup.save()
        response = self._detail()
        self.assertNotContains(response, 'Folge-Issue ebenfalls schließen')
        self.assertContains(response, 'bereits in Arbeit')

    def test_job_detail_and_queue_show_override(self):
        job = self._job()
        override_review(self.item, self.user, REASON)
        response = self.client.get(reverse('claude-queue-jobs'))
        self.assertContains(response, 'Überschrieben durch Tina Tester')
        self.assertContains(response, 'Abweichungen')  # original verdict stays
        detail = self.client.get(reverse('claude-queue-job-live', args=[job.pk]))
        self.assertContains(detail, 'Überschrieben durch Tina Tester')
        self.assertContains(detail, REASON)
