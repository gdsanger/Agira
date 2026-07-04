"""
Tests for the GitHub `pull_request` webhook endpoint.
"""
import hashlib
import hmac
import json

from django.test import TestCase, Client
from django.urls import reverse

from core.models import (
    GitHubConfiguration,
    Project,
    Item,
    ItemType,
    ItemStatus,
    ExternalIssueMapping,
    ExternalIssueKind,
    ClaudeQueueJob,
)

WEBHOOK_SECRET = 'test-webhook-secret'


def sign(body: bytes, secret: str = WEBHOOK_SECRET) -> str:
    digest = hmac.new(secret.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return f'sha256={digest}'


def pr_payload(
    *,
    action='closed',
    number=42,
    github_id=9001,
    merged=True,
    state='closed',
    body='## Summary\n\nWhy we chose the queue-based approach.',
    merge_commit_sha='abc123def456',
):
    pull_request = {
        'id': github_id,
        'number': number,
        'state': state,
        'merged': merged,
        'html_url': f'https://github.com/testowner/testrepo/pull/{number}',
        'body': body,
    }
    if merged:
        pull_request['merged_at'] = '2026-07-03T10:00:00Z'
        pull_request['merge_commit_sha'] = merge_commit_sha
    else:
        pull_request['merged_at'] = None
    return {'action': action, 'number': number, 'pull_request': pull_request}


class GitHubPRWebhookTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse('github-pull-request-webhook')

        self.config = GitHubConfiguration.load()
        self.config.enable_github = True
        self.config.webhook_secret = WEBHOOK_SECRET
        self.config.save()

        self.project = Project.objects.create(
            name='Test Project',
            github_owner='testowner',
            github_repo='testrepo',
        )
        self.item_type = ItemType.objects.create(key='feature', name='Feature')
        self.item = Item.objects.create(
            project=self.project,
            title='Working item',
            type=self.item_type,
            status=ItemStatus.WORKING,
        )
        self.mapping = ExternalIssueMapping.objects.create(
            item=self.item,
            github_id=9001,
            number=42,
            kind=ExternalIssueKind.PR,
            state='open',
            html_url='https://github.com/testowner/testrepo/pull/42',
        )
        self.job = ClaudeQueueJob.objects.create(
            item=self.item,
            pr_number=42,
            pr_url='https://github.com/testowner/testrepo/pull/42',
        )

    def _post(self, payload, secret=WEBHOOK_SECRET, event='pull_request'):
        body = json.dumps(payload).encode('utf-8')
        headers = {'HTTP_X_GITHUB_EVENT': event}
        if secret is not None:
            headers['HTTP_X_HUB_SIGNATURE_256'] = sign(body, secret)
        return self.client.post(
            self.url,
            data=body,
            content_type='application/json',
            **headers,
        )

    def test_rejects_missing_signature(self):
        response = self._post(pr_payload(), secret=None)
        self.assertEqual(response.status_code, 403)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

    def test_rejects_wrong_signature(self):
        response = self._post(pr_payload(), secret='wrong-secret')
        self.assertEqual(response.status_code, 403)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

    def test_merged_pr_moves_working_item_to_testing(self):
        response = self._post(pr_payload(merged=True, state='closed'))
        self.assertEqual(response.status_code, 200)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.TESTING)

        self.mapping.refresh_from_db()
        self.assertEqual(self.mapping.state, 'merged')

        self.job.refresh_from_db()
        self.assertEqual(self.job.pr_state, 'merged')

    def test_redelivered_merged_event_is_idempotent(self):
        self._post(pr_payload(merged=True, state='closed'))
        # Simulate GitHub retrying the same delivery.
        response = self._post(pr_payload(merged=True, state='closed'))

        self.assertEqual(response.status_code, 200)
        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.TESTING)

    def test_closed_unmerged_pr_is_ignored(self):
        response = self._post(pr_payload(merged=False, state='closed'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

        self.mapping.refresh_from_db()
        self.assertEqual(self.mapping.state, 'open')

        self.job.refresh_from_db()
        self.assertFalse(self.job.pr_state)

    def test_opened_action_is_ignored(self):
        response = self._post(pr_payload(action='opened', merged=False, state='open'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

        self.mapping.refresh_from_db()
        self.assertEqual(self.mapping.state, 'open')

    def test_synchronize_action_is_ignored(self):
        response = self._post(pr_payload(action='synchronize', merged=False, state='open'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

        self.mapping.refresh_from_db()
        self.assertEqual(self.mapping.state, 'open')

    def test_labeled_action_is_ignored(self):
        response = self._post(pr_payload(action='labeled', merged=False, state='open'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

    def test_ready_for_review_action_is_ignored(self):
        response = self._post(pr_payload(action='ready_for_review', merged=False, state='open'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

    def test_unknown_action_is_ignored(self):
        response = self._post(pr_payload(action='review_requested', merged=False, state='open'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

    def test_unmatched_github_id_is_ignored(self):
        response = self._post(pr_payload(github_id=99999999))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['matched'])

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.WORKING)

    def test_non_pull_request_event_is_ignored(self):
        response = self._post(pr_payload(), event='ping')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['ignored'])

        self.mapping.refresh_from_db()
        self.assertEqual(self.mapping.state, 'open')

    def test_merged_pr_captures_final_body_and_merge_metadata(self):
        body = '## Summary\n\nThe reasoning that becomes RAG memory.'
        response = self._post(
            pr_payload(merged=True, state='closed', body=body, merge_commit_sha='deadbeef')
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['pr_body_indexed'])

        self.mapping.refresh_from_db()
        self.assertEqual(self.mapping.pr_body, body)
        self.assertEqual(self.mapping.merge_commit_sha, 'deadbeef')
        self.assertIsNotNone(self.mapping.merged_at)

    def test_merged_pr_null_body_does_not_blank_existing_body(self):
        self.mapping.pr_body = 'existing description'
        self.mapping.save()

        response = self._post(pr_payload(merged=True, state='closed', body=None))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['pr_body_indexed'])

        self.mapping.refresh_from_db()
        # Null body must not overwrite / blank the existing text.
        self.assertEqual(self.mapping.pr_body, 'existing description')
        # Merge metadata is still stamped even without a body.
        self.assertEqual(self.mapping.merge_commit_sha, 'abc123def456')

    def test_redelivered_merge_keeps_body(self):
        body = '## Summary\n\nStable content.'
        self._post(pr_payload(merged=True, state='closed', body=body))
        self._post(pr_payload(merged=True, state='closed', body=body))

        self.mapping.refresh_from_db()
        self.assertEqual(self.mapping.pr_body, body)

    def test_serialized_pr_indexes_final_body_not_item_description(self):
        from core.services.weaviate.serializers import to_agira_object

        self.item.description = 'stale bootstrap description'
        self.item.save()

        body = '## Summary\n\nFinal canonical PR reasoning.'
        self._post(pr_payload(merged=True, state='closed', body=body))

        self.mapping.refresh_from_db()
        obj = to_agira_object(self.mapping)
        # The text that gets indexed into Weaviate is the final PR body, with the
        # merged-state prefix — not the item description.
        self.assertIn('Final canonical PR reasoning.', obj['text'])
        self.assertNotIn('stale bootstrap description', obj['text'])
        self.assertEqual(obj['status'], 'merged')

    def test_merged_pr_populates_item_pr_description(self):
        body = '## Summary\n\nThe reasoning that becomes the PR-Description tab.'
        response = self._post(pr_payload(merged=True, state='closed', body=body))
        self.assertEqual(response.status_code, 200)

        self.item.refresh_from_db()
        self.assertEqual(self.item.pr_description, body)

    def test_merged_pr_null_body_does_not_blank_existing_pr_description(self):
        self.item.pr_description = 'existing pr description'
        self.item.save()

        response = self._post(pr_payload(merged=True, state='closed', body=None))
        self.assertEqual(response.status_code, 200)

        self.item.refresh_from_db()
        self.assertEqual(self.item.pr_description, 'existing pr description')

    def test_item_already_in_testing_is_left_untouched_by_late_merge_event(self):
        self.item.status = ItemStatus.TESTING
        self.item.save()

        response = self._post(pr_payload(merged=True, state='closed'))
        self.assertEqual(response.status_code, 200)

        self.item.refresh_from_db()
        self.assertEqual(self.item.status, ItemStatus.TESTING)
