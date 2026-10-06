"""
Tests for the daily status report (status history, counters, windows, command).
"""
from datetime import date, datetime, timedelta
from io import StringIO
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from core.models import (
    Activity,
    GraphAPIConfiguration,
    Item,
    ItemStatus,
    ItemStatusChange,
    ItemStatusSnapshot,
    ItemType,
    Project,
    User,
    UserRole,
)
from core.services.daily_report import build_report, render_html, render_text, report_window, write_snapshot
from core.services.daily_report.report import NO_REQUESTER, NO_RESPONSIBLE, cutoff, day_state
from core.services.workflow import ItemWorkflowGuard

BERLIN = ZoneInfo('Europe/Berlin')
UTC = ZoneInfo('UTC')


def berlin(y, m, d, hh=12, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=BERLIN)


class ReportWindowTests(TestCase):
    """Window = previous day 07:30 to report day 07:30, wall-clock in Berlin."""

    def test_regular_day_is_24_hours(self):
        start, end = report_window(date(2026, 10, 6))
        self.assertEqual(start, berlin(2026, 10, 5, 7, 30))
        self.assertEqual(end, berlin(2026, 10, 6, 7, 30))
        self.assertEqual(end - start, timedelta(hours=24))
        # CEST: 07:30 local is 05:30 UTC
        self.assertEqual(end.astimezone(UTC).hour, 5)

    def test_winter_time_cutoff(self):
        _, end = report_window(date(2026, 12, 1))
        self.assertEqual(end.astimezone(UTC).hour, 6)
        self.assertEqual(end.astimezone(UTC).minute, 30)

    def test_dst_start_window_is_23_hours(self):
        # 2026-03-29: clocks go 02:00 → 03:00
        start, end = report_window(date(2026, 3, 29))
        self.assertEqual(end - start, timedelta(hours=23))
        self.assertEqual(start.astimezone(UTC), datetime(2026, 3, 28, 6, 30, tzinfo=UTC))
        self.assertEqual(end.astimezone(UTC), datetime(2026, 3, 29, 5, 30, tzinfo=UTC))

    def test_dst_end_window_is_25_hours(self):
        # 2026-10-25: clocks go 03:00 → 02:00
        start, end = report_window(date(2026, 10, 25))
        self.assertEqual(end - start, timedelta(hours=25))
        self.assertEqual(start.astimezone(UTC), datetime(2026, 10, 24, 5, 30, tzinfo=UTC))
        self.assertEqual(end.astimezone(UTC), datetime(2026, 10, 25, 6, 30, tzinfo=UTC))

    def test_consecutive_windows_are_gapless(self):
        for day in (date(2026, 3, 29), date(2026, 3, 30), date(2026, 10, 25), date(2026, 10, 26)):
            self.assertEqual(report_window(day)[0], report_window(day - timedelta(days=1))[1])


class ReportTestBase(TestCase):
    # History "started" well before the report dates used below.
    HISTORY_START = berlin(2026, 9, 1, 0, 0)
    REPORT_DATE = date(2026, 10, 6)
    NOW = berlin(2026, 10, 6, 7, 30)

    def setUp(self):
        self.type = ItemType.objects.create(key='bug', name='Bug')
        self.agira = Project.objects.create(name='Agira')
        self.zenico = Project.objects.create(name='Zenico')
        self.empty_project = Project.objects.create(name='Leer')
        self.alice = User.objects.create_user(
            username='alice', email='alice@example.com', password='x', name='Alice Agent', role=UserRole.AGENT,
        )
        self.bob = User.objects.create_user(
            username='bob', email='bob@example.com', password='x', name='Bob Builder', role=UserRole.AGENT,
        )

    def make_item(self, title, status=ItemStatus.INBOX, project=None, requester=None, responsible=None,
                  created_at=None):
        item = Item.objects.create(
            project=project or self.agira, title=title, type=self.type,
            requester=requester, responsible=responsible,
        )
        created_at = created_at or self.HISTORY_START
        if status != ItemStatus.INBOX:
            item.status = status
            item.save()
        ItemStatusChange.objects.filter(item=item).update(changed_at=created_at)
        Item.objects.filter(pk=item.pk).update(created_at=created_at)
        item.refresh_from_db()
        return item

    def set_status(self, item, status, at):
        item.refresh_from_db()
        item.status = status
        item.save()
        ItemStatusChange.objects.filter(item=item, changed_at__gt=at).update(changed_at=at)

    def report(self, report_date=None, now=None):
        return build_report(report_date or self.REPORT_DATE, now=now or self.NOW)


class StatusHistoryRecordingTests(ReportTestBase):

    def test_creation_and_change_are_recorded(self):
        item = Item.objects.create(project=self.agira, title='x', type=self.type)
        item.status = ItemStatus.BACKLOG
        item.save()
        item.title = 'only the title changes'
        item.save()
        changes = list(ItemStatusChange.objects.filter(item=item).values_list('from_status', 'to_status'))
        self.assertEqual(changes, [('', ItemStatus.INBOX), (ItemStatus.INBOX, ItemStatus.BACKLOG)])

    def test_workflow_guard_records_actor(self):
        item = Item.objects.create(project=self.agira, title='x', type=self.type)
        ItemWorkflowGuard().transition(item, ItemStatus.WORKING, self.alice)
        change = ItemStatusChange.objects.filter(item=item).last()
        self.assertEqual(change.to_status, ItemStatus.WORKING)
        self.assertEqual(change.changed_by, self.alice)
        self.assertFalse(change.backfilled)

    def test_backfill_from_activity_log(self):
        import importlib

        from django.apps import apps
        from django.contrib.contenttypes.models import ContentType

        migration = importlib.import_module('core.migrations.0082_item_status_history')
        item = Item.objects.create(project=self.agira, title='x', type=self.type)
        ItemStatusChange.objects.all().delete()
        ct = ContentType.objects.get_for_model(Item)
        Activity.objects.create(target_content_type=ct, target_object_id=str(item.pk),
                                verb='item.status_changed', actor=self.bob, summary='Status: Testing → Closed')
        Activity.objects.create(target_content_type=ct, target_object_id=str(item.pk),
                                verb='item.status_changed', summary='Status: garbage')
        Activity.objects.create(target_content_type=ct, target_object_id='999999',
                                verb='item.status_changed', summary='Status: Inbox → Closed')

        migration.backfill_from_activity(apps, None)

        change = ItemStatusChange.objects.get()
        self.assertEqual((change.from_status, change.to_status), ('Testing', 'Closed'))
        self.assertTrue(change.backfilled)
        self.assertEqual(change.changed_by, self.bob)


class DailyReportCounterTests(ReportTestBase):

    def test_new_items_use_created_at_window(self):
        start, end = report_window(self.REPORT_DATE)
        inside = self.make_item('inside', requester=self.alice, created_at=start + timedelta(minutes=1))
        self.make_item('at end is next window', created_at=end)
        self.make_item('before', created_at=start - timedelta(minutes=1))
        at_start = self.make_item('at start', created_at=start)

        report = self.report()

        self.assertEqual([i.id for i in report.new_items], sorted([inside.id, at_start.id]))
        line = next(i for i in report.new_items if i.id == inside.id)
        self.assertEqual(line.person, 'Alice Agent')
        self.assertEqual(line.project, 'Agira')

    def test_closed_uses_transition_not_updated_at(self):
        start, end = report_window(self.REPORT_DATE)
        closed_in_window = self.make_item('closed now', ItemStatus.TESTING, responsible=self.bob)
        self.set_status(closed_in_window, ItemStatus.CLOSED, start + timedelta(hours=2))
        closed_earlier = self.make_item('closed before', ItemStatus.CLOSED)
        # Touched inside the window, but the close happened long before.
        Item.objects.filter(pk=closed_earlier.pk).update(updated_at=start + timedelta(hours=3))

        report = self.report()

        self.assertEqual([i.id for i in report.closed_items], [closed_in_window.id])
        self.assertEqual(report.closed_items[0].person, 'Bob Builder')
        self.assertTrue(report.closed_complete)

    def test_closed_and_reopened_in_window_counts_once(self):
        start, _ = report_window(self.REPORT_DATE)
        item = self.make_item('flip', ItemStatus.WORKING)
        self.set_status(item, ItemStatus.CLOSED, start + timedelta(hours=1))
        self.set_status(item, ItemStatus.WORKING, start + timedelta(hours=2))
        self.set_status(item, ItemStatus.CLOSED, start + timedelta(hours=3))
        self.assertEqual(len(self.report().closed_items), 1)

    def test_status_distribution_and_projects(self):
        self.make_item('a', ItemStatus.INBOX)
        self.make_item('b', ItemStatus.INBOX)
        self.make_item('c', ItemStatus.BACKLOG, project=self.zenico)
        self.make_item('d', ItemStatus.REVIEW, project=self.zenico)
        self.make_item('e', ItemStatus.CLOSED)

        report = self.report()

        self.assertEqual(report.state.total, 4)
        self.assertEqual(report.state.counts[ItemStatus.INBOX], 2)
        self.assertEqual(report.state.counts[ItemStatus.BACKLOG], 1)
        self.assertEqual(report.state.counts[ItemStatus.REVIEW], 1)
        self.assertNotIn(ItemStatus.CLOSED, report.state.counts)
        projects = {name: total for name, _, total in report.projects}
        self.assertEqual(projects, {'Agira': 2, 'Zenico': 2})  # 'Leer' and closed-only excluded

    def test_requester_counts_with_names_and_placeholder(self):
        self.make_item('a', requester=self.alice)
        self.make_item('b', ItemStatus.WORKING, requester=self.alice)
        self.make_item('c', requester=self.bob)
        self.make_item('d')
        self.make_item('closed', ItemStatus.CLOSED, requester=self.bob)

        rows = [(p.name, p.total) for p in self.report().requesters]

        self.assertEqual(rows, [('Alice Agent', 2), ('Bob Builder', 1), (NO_REQUESTER, 1)])

    def test_responsible_counts_only_active_statuses(self):
        self.make_item('w', ItemStatus.WORKING, responsible=self.alice)
        self.make_item('t', ItemStatus.TESTING, responsible=self.alice)
        self.make_item('r', ItemStatus.REVIEW)
        self.make_item('inbox', ItemStatus.INBOX, responsible=self.bob)
        self.make_item('ready', ItemStatus.READY_FOR_RELEASE, responsible=self.bob)

        rows = {p.name: (p.total, p.per_status) for p in self.report().responsibles}

        self.assertEqual(set(rows), {'Alice Agent', NO_RESPONSIBLE})
        self.assertEqual(rows['Alice Agent'][0], 2)
        self.assertEqual(rows['Alice Agent'][1][ItemStatus.WORKING], 1)
        self.assertEqual(rows[NO_RESPONSIBLE][0], 1)


class DailyReportTrendTests(ReportTestBase):

    def test_trend_reconstructs_past_days_from_history(self):
        start, _ = report_window(self.REPORT_DATE)
        item = self.make_item('moves', ItemStatus.BACKLOG, created_at=berlin(2026, 10, 1))
        # Became Working after the 05.10. cut-off → on 05.10. it was still Backlog.
        self.set_status(item, ItemStatus.WORKING, start + timedelta(hours=1))
        self.make_item('new on 04.10.', created_at=berlin(2026, 10, 3, 9, 0))

        trend = {d.date: d for d in self.report().trend}

        self.assertEqual(len(trend), 7)
        self.assertEqual(trend[date(2026, 10, 2)].state.total, 1)  # only 'moves' existed
        self.assertEqual(trend[date(2026, 10, 4)].new, 1)
        self.assertEqual(trend[date(2026, 10, 5)].state.counts[ItemStatus.BACKLOG], 1)
        self.assertEqual(trend[date(2026, 10, 5)].state.counts[ItemStatus.WORKING], 0)
        self.assertEqual(trend[date(2026, 10, 6)].state.counts[ItemStatus.WORKING], 1)

    def test_days_before_history_start_are_gaps(self):
        self.make_item('x')
        ItemStatusChange.objects.update(changed_at=berlin(2026, 10, 4, 12, 0))

        report = self.report()
        trend = {d.date: d for d in report.trend}

        self.assertIsNone(trend[date(2026, 10, 4)].state)  # cut-off 07:30 < 12:00
        self.assertIsNotNone(trend[date(2026, 10, 5)].state)
        self.assertFalse(trend[date(2026, 10, 5)].closed_complete)  # window started 04.10. 07:30
        self.assertTrue(trend[date(2026, 10, 6)].closed_complete)
        self.assertTrue(report.trend_has_gaps)
        text = render_text(report)
        self.assertIn('keine Daten', text)
        self.assertIn('Hinweise', text)

    def test_snapshot_preferred_and_first_run_wins(self):
        self.make_item('a', ItemStatus.INBOX)
        self.assertTrue(write_snapshot(date(2026, 10, 3)))
        self.make_item('b', ItemStatus.INBOX)
        self.assertFalse(write_snapshot(date(2026, 10, 3)))
        self.assertEqual(ItemStatusSnapshot.objects.get(date=date(2026, 10, 3)).count, 1)

        state = day_state(date(2026, 10, 3), today=self.REPORT_DATE, tracking_start=self.HISTORY_START)

        self.assertEqual(state.source, 'snapshot')
        self.assertEqual(state.total, 1)  # reconstruction would say 2

    def test_cutoff_is_local(self):
        self.assertEqual(cutoff(date(2026, 1, 15)), datetime(2026, 1, 15, 6, 30, tzinfo=UTC))
        self.assertEqual(cutoff(date(2026, 7, 15)), datetime(2026, 7, 15, 5, 30, tzinfo=UTC))


class DailyReportRenderingTests(ReportTestBase):

    def test_html_has_all_sections_and_no_external_resources(self):
        self.make_item('Neues <Item>', requester=self.alice, created_at=berlin(2026, 10, 6, 6, 0))
        html = render_html(self.report())
        for heading in ('1. Neue Items', '2. Statusverteilung', '3. Geschlossen',
                        '4. Offen je Requester', '5. Responsible in Bearbeitung', '6. Verlauf 7 Tage'):
            self.assertIn(heading, html)
        self.assertIn('Alice Agent', html)
        self.assertIn('Neues &lt;Item&gt;', html)  # escaped
        self.assertNotIn('<link', html)
        self.assertNotIn('<script', html)
        self.assertNotIn('<img', html)
        self.assertNotIn('<style', html)

    def test_subject(self):
        self.assertEqual(self.report().subject, 'Agira Tagesreport – 06.10.2026')


@override_settings(DAILY_REPORT_RECIPIENTS=['report@example.com'], DAILY_REPORT_SENDER=None)
class DailyStatusReportCommandTests(ReportTestBase):

    def test_dry_run_prints_full_report_without_sending(self):
        self.make_item('x', ItemStatus.WORKING, requester=self.alice, responsible=self.bob)
        out = StringIO()
        with patch('core.management.commands.daily_status_report.send_multipart_email') as send:
            call_command('daily_status_report', '--dry-run', stdout=out)
        send.assert_not_called()
        self.assertFalse(ItemStatusSnapshot.objects.exists())
        text = out.getvalue()
        for heading in ('1. Neue Items', '2. Statusverteilung', '3. Geschlossen', '4. Offene Items je Requester',
                        '5. Responsible in Bearbeitung', '6. Verlauf 7 Tage'):
            self.assertIn(heading, text)
        self.assertIn('Alice Agent', text)
        self.assertIn('Bob Builder', text)

    def test_send_writes_snapshot_and_mails(self):
        self.make_item('x')
        with patch('core.management.commands.daily_status_report.send_multipart_email') as send:
            send.return_value = MagicMock(success=True)
            call_command('daily_status_report', stdout=StringIO())
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs['to'], ['report@example.com'])
        self.assertTrue(kwargs['subject'].startswith('Agira Tagesreport – '))
        self.assertIn('<html', kwargs['html_body'])
        self.assertIn('1. Neue Items', kwargs['text_body'])
        self.assertTrue(ItemStatusSnapshot.objects.exists())

    def test_send_failure_is_not_silent(self):
        with patch('core.management.commands.daily_status_report.send_multipart_email') as send:
            send.return_value = MagicMock(success=False, error='boom')
            with self.assertLogs('core.management.commands.daily_status_report', 'ERROR'):
                with self.assertRaisesMessage(CommandError, 'boom'):
                    call_command('daily_status_report', stdout=StringIO())

    def test_past_date_does_not_write_snapshot(self):
        out = StringIO()
        call_command('daily_status_report', '--dry-run', '--date', '2026-01-02', stdout=out)
        self.assertIn('Agira Tagesreport – 02.01.2026', out.getvalue())
        with self.assertRaises(CommandError):
            call_command('daily_status_report', '--dry-run', '--date', '2999-01-01', stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command('daily_status_report', '--dry-run', '--date', '06.10.2026', stdout=StringIO())


class MultipartMailTests(TestCase):

    def setUp(self):
        GraphAPIConfiguration.objects.create(
            tenant_id='t', client_id='c', client_secret='s', enabled=True,
            default_mail_sender='agira@example.com',
        )

    def test_sends_multipart_alternative_mime(self):
        import base64
        from email import message_from_bytes

        from core.services.graph.mail_service import send_multipart_email

        client = MagicMock()
        with patch('core.services.graph.mail_service.get_client', return_value=client):
            result = send_multipart_email('Betreff', 'Text', '<p>HTML</p>', ['to@example.com'])

        self.assertTrue(result.success)
        sender = client.send_mime_mail.call_args.kwargs['sender_upn']
        self.assertEqual(sender, 'agira@example.com')
        msg = message_from_bytes(client.send_mime_mail.call_args.kwargs['mime_message'])
        self.assertEqual(msg.get_content_type(), 'multipart/alternative')
        self.assertEqual([p.get_content_type() for p in msg.get_payload()], ['text/plain', 'text/html'])

        # Graph client posts the MIME base64-encoded as text/plain
        from core.services.graph.client import GraphClient
        graph = GraphClient()
        with patch.object(graph, 'request') as request:
            graph.send_mime_mail('agira@example.com', b'raw')
        request.assert_called_once_with(
            'POST', '/users/agira@example.com/sendMail',
            data=base64.b64encode(b'raw'), headers={'Content-Type': 'text/plain'},
        )

    def test_failure_is_returned_and_logged(self):
        from core.services.graph.mail_service import send_multipart_email

        client = MagicMock()
        client.send_mime_mail.side_effect = RuntimeError('graph down')
        with patch('core.services.graph.mail_service.get_client', return_value=client):
            with self.assertLogs('core.services.graph.mail_service', 'ERROR'):
                result = send_multipart_email('Betreff', 'Text', '<p>HTML</p>', ['to@example.com'])
        self.assertFalse(result.success)
        self.assertIn('graph down', result.error)

