"""
Tests for:
- Comment count annotation surfaced in Item ListViews (no N+1 queries).
- Structured @mention parsing and email notification on comment save.
"""
from unittest.mock import patch

from django.test import TestCase, Client
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse

from core.models import (
    Item, ItemStatus, ItemType, Project, Organisation, User, ProjectStatus,
    ItemComment, MailTemplate, GlobalSettings,
)
from core.services.comments.mentions import extract_mentioned_user_ids


class CommentCountListViewTestCase(TestCase):
    """Comment counts must be annotated once per list, not per row."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create(username='lister', email='lister@example.com', active=True)
        self.user.set_password('testpass123')
        self.user.save()

        self.project = Project.objects.create(name='Project X', status=ProjectStatus.WORKING)
        self.item_type = ItemType.objects.create(key='bug', name='Bug')

        self.item_no_comments = Item.objects.create(
            title='No comments', project=self.project, type=self.item_type, status=ItemStatus.INBOX,
        )
        self.item_with_comments = Item.objects.create(
            title='Has comments', project=self.project, type=self.item_type, status=ItemStatus.INBOX,
        )
        ItemComment.objects.create(item=self.item_with_comments, author=self.user, body='First')
        ItemComment.objects.create(item=self.item_with_comments, author=self.user, body='Second')

        self.client.login(username='lister', password='testpass123')

    def test_comment_count_annotated_correctly(self):
        response = self.client.get(reverse('items-inbox'))
        self.assertEqual(response.status_code, 200)

        items_by_id = {item.id: item for item in response.context['items']}
        self.assertEqual(items_by_id[self.item_no_comments.id].comment_count, 0)
        self.assertEqual(items_by_id[self.item_with_comments.id].comment_count, 2)

    def test_zero_comments_render_no_badge(self):
        response = self.client.get(reverse('items-inbox'))
        content = response.content.decode()
        # The item without comments must not be adjacent to a comment badge.
        self.assertIn('No comments', content)

    def test_comment_count_does_not_add_per_row_queries(self):
        """Adding more commented items must not increase the query count (no N+1)."""
        with CaptureQueriesContext(connection) as ctx_before:
            self.client.get(reverse('items-inbox'))
        queries_before = len(ctx_before.captured_queries)

        # Add another commented item - if comment counting were per-row, this
        # would add at least one extra query.
        extra_item = Item.objects.create(
            title='Another item', project=self.project, type=self.item_type, status=ItemStatus.INBOX,
        )
        ItemComment.objects.create(item=extra_item, author=self.user, body='x')

        with CaptureQueriesContext(connection) as ctx_after:
            self.client.get(reverse('items-inbox'))
        queries_after = len(ctx_after.captured_queries)

        self.assertEqual(queries_before, queries_after)

    def test_comment_count_reflects_reload_after_new_comment(self):
        ItemComment.objects.create(item=self.item_no_comments, author=self.user, body='New')

        response = self.client.get(reverse('items-inbox'))
        items_by_id = {item.id: item for item in response.context['items']}
        self.assertEqual(items_by_id[self.item_no_comments.id].comment_count, 1)


class MentionExtractionTestCase(TestCase):
    """Unit tests for the structured mention token parser."""

    def test_extracts_single_mention(self):
        body = 'Hello @[Jane Doe](user:42), please check this.'
        self.assertEqual(extract_mentioned_user_ids(body), [42])

    def test_extracts_multiple_unique_mentions_in_order(self):
        body = '@[Jane Doe](user:42) and @[Bob](user:7) and @[Jane Doe](user:42) again'
        self.assertEqual(extract_mentioned_user_ids(body), [42, 7])

    def test_plain_text_at_sign_is_not_a_mention(self):
        body = 'Please ping @bob or email user@example.com about this.'
        self.assertEqual(extract_mentioned_user_ids(body), [])

    def test_empty_body_returns_empty_list(self):
        self.assertEqual(extract_mentioned_user_ids(''), [])
        self.assertEqual(extract_mentioned_user_ids(None), [])


class UserSearchEndpointTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.requester = User.objects.create(username='searcher', email='searcher@example.com', active=True)
        self.requester.set_password('testpass123')
        self.requester.save()

        self.active_match = User.objects.create(username='jdoe', name='Jane Doe', email='jane@example.com', active=True)
        self.inactive_match = User.objects.create(username='jretired', name='Jane Retired', email='retired@example.com', active=False)

        self.client.login(username='searcher', password='testpass123')

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse('user-search'), {'q': 'jane'})
        self.assertNotEqual(response.status_code, 200)

    def test_matches_active_users_by_name(self):
        response = self.client.get(reverse('user-search'), {'q': 'jane'})
        self.assertEqual(response.status_code, 200)
        ids = [row['id'] for row in response.json()['results']]
        self.assertIn(self.active_match.id, ids)
        self.assertNotIn(self.inactive_match.id, ids)


class CommentMentionNotificationTestCase(TestCase):
    """Mentions must be persisted and trigger exactly one email per mentioned user."""

    def setUp(self):
        self.client = Client()
        GlobalSettings.objects.create(id=1, base_url='https://agira.example.com')

        self.author = User.objects.create(username='author', email='author@example.com', active=True)
        self.author.set_password('testpass123')
        self.author.save()

        self.mentioned1 = User.objects.create(username='mentioned1', name='Mentioned One', email='m1@example.com', active=True)
        self.mentioned2 = User.objects.create(username='mentioned2', name='Mentioned Two', email='m2@example.com', active=True)
        self.inactive_user = User.objects.create(username='inactive', name='Inactive User', email='inactive@example.com', active=False)

        self.project = Project.objects.create(name='Project Y', status=ProjectStatus.WORKING)
        self.item_type = ItemType.objects.create(key='bug', name='Bug')
        self.item = Item.objects.create(title='Mention target', project=self.project, type=self.item_type)

        MailTemplate.objects.filter(key='comment-mention').delete()
        MailTemplate.objects.create(
            key='comment-mention',
            subject='Mentioned in {{ issue.title }}',
            message='{{ recipient_name }} - {{ comment.body }} - {{ issue.project }}',
            is_active=True,
        )

        self.client.login(username='author', password='testpass123')

    def _post_comment(self, body):
        return self.client.post(reverse('item-add-comment', args=[self.item.id]), {'body': body})

    @patch('core.services.graph.mail_service.send_email')
    def test_valid_mention_sends_one_email(self, mock_send_email):
        body = f'Ping @[Mentioned One](user:{self.mentioned1.id}) please look at this.'
        response = self._post_comment(body)

        self.assertEqual(response.status_code, 200)
        mock_send_email.assert_called_once()
        call_kwargs = mock_send_email.call_args[1]
        self.assertEqual(call_kwargs['to'], [self.mentioned1.email])

        comment = ItemComment.objects.get(item=self.item)
        self.assertEqual(list(comment.mentioned_users.all()), [self.mentioned1])

    @patch('core.services.graph.mail_service.send_email')
    def test_duplicate_mention_of_same_user_sends_exactly_one_email(self, mock_send_email):
        body = (
            f'@[Mentioned One](user:{self.mentioned1.id}) see this, '
            f'cc @[Mentioned One](user:{self.mentioned1.id}) again.'
        )
        self._post_comment(body)

        mock_send_email.assert_called_once()

    @patch('core.services.graph.mail_service.send_email')
    def test_multiple_distinct_mentions_send_one_email_each(self, mock_send_email):
        body = (
            f'@[Mentioned One](user:{self.mentioned1.id}) and '
            f'@[Mentioned Two](user:{self.mentioned2.id}) please review.'
        )
        self._post_comment(body)

        self.assertEqual(mock_send_email.call_count, 2)
        recipients = {call.kwargs['to'][0] for call in mock_send_email.call_args_list}
        self.assertEqual(recipients, {self.mentioned1.email, self.mentioned2.email})

    @patch('core.services.graph.mail_service.send_email')
    def test_plain_text_mention_sends_no_email(self, mock_send_email):
        self._post_comment('Hey @mentioned1 check this out.')

        mock_send_email.assert_not_called()
        comment = ItemComment.objects.get(item=self.item)
        self.assertEqual(comment.mentioned_users.count(), 0)

    @patch('core.services.graph.mail_service.send_email')
    def test_self_mention_sends_no_email(self, mock_send_email):
        body = f'Note to self @[Author](user:{self.author.id})'
        with self.assertLogs('core.views', level='INFO') as log_ctx:
            self._post_comment(body)

        mock_send_email.assert_not_called()
        self.assertTrue(any('mentioned themselves' in message for message in log_ctx.output))

    @patch('core.services.graph.mail_service.send_email')
    def test_inactive_mentioned_user_sends_no_email(self, mock_send_email):
        body = f'@[Inactive User](user:{self.inactive_user.id}) fyi'
        with self.assertLogs('core.views', level='INFO') as log_ctx:
            self._post_comment(body)

        mock_send_email.assert_not_called()
        self.assertTrue(any('is inactive' in message for message in log_ctx.output))

    @patch('core.services.graph.mail_service.send_email')
    def test_editing_comment_does_not_resend_notification(self, mock_send_email):
        comment = ItemComment.objects.create(item=self.item, author=self.author, body='Plain comment')

        response = self.client.post(
            reverse('item-update-comment', args=[comment.id]),
            data=f'{{"body": "@[Mentioned One](user:{self.mentioned1.id}) added on edit"}}',
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        mock_send_email.assert_not_called()
        comment.refresh_from_db()
        self.assertEqual(list(comment.mentioned_users.all()), [self.mentioned1])
