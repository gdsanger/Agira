"""
Daily status report of all Agira items, sent as HTML mail with text fallback.

Scheduled daily at 07:30 Europe/Berlin (systemd timer, see
docs/DAILY_STATUS_REPORT.md).

Usage:
    python manage.py daily_status_report                    # build, snapshot, send
    python manage.py daily_status_report --dry-run          # print text report only
    python manage.py daily_status_report --dry-run --html-out /tmp/report.html
    python manage.py daily_status_report --date 2026-10-05  # past cut-off
"""

import logging
from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.daily_report import (
    build_report,
    local_today,
    render_html,
    render_text,
    write_snapshot,
)
from core.services.graph.mail_service import send_multipart_email

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Erzeugt den täglichen Status-Report aller Agira-Items und versendet ihn per E-Mail.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report nur ausgeben, nicht senden und keinen Snapshot schreiben.',
        )
        parser.add_argument(
            '--date',
            help='Stichtag YYYY-MM-DD (Standard: heute). Vergangene Stichtage nur soweit die Historie reicht.',
        )
        parser.add_argument(
            '--html-out',
            help='HTML-Version zusätzlich in diese Datei schreiben (Vorschau).',
        )
        parser.add_argument(
            '--to',
            help='Empfänger (kommagetrennt) statt DAILY_REPORT_RECIPIENTS.',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = local_today()
        report_date = self._parse_date(options.get('date'), today)

        recipients = (
            [a.strip() for a in options['to'].split(',') if a.strip()]
            if options.get('to') else list(settings.DAILY_REPORT_RECIPIENTS)
        )
        if not dry_run and not recipients:
            logger.error('Daily status report: no recipients configured (DAILY_REPORT_RECIPIENTS)')
            raise CommandError('Keine Empfänger konfiguriert (DAILY_REPORT_RECIPIENTS).')

        try:
            # Snapshot first, so the trend is kept even if sending fails.
            if not dry_run and report_date == today:
                if write_snapshot(report_date):
                    logger.info(f'Daily status report: snapshot for {report_date} written')
            report = build_report(report_date)
            text_body = render_text(report)
            html_body = render_html(report)
        except Exception as exc:
            logger.exception(f'Daily status report for {report_date} could not be generated')
            raise CommandError(f'Report konnte nicht erzeugt werden: {exc}') from exc

        if options.get('html_out'):
            with open(options['html_out'], 'w', encoding='utf-8') as fh:
                fh.write(html_body)

        if dry_run:
            self.stdout.write(text_body)
            return

        result = send_multipart_email(
            subject=report.subject,
            text_body=text_body,
            html_body=html_body,
            to=recipients,
            sender=settings.DAILY_REPORT_SENDER,
        )
        if not result.success:
            logger.error(f'Daily status report for {report_date} could not be sent: {result.error}')
            raise CommandError(f'Versand fehlgeschlagen: {result.error}')

        logger.info(f"Daily status report for {report_date} sent to {', '.join(recipients)}")
        self.stdout.write(self.style.SUCCESS(f"Report '{report.subject}' an {', '.join(recipients)} gesendet."))

    @staticmethod
    def _parse_date(value, today: date) -> date:
        if not value:
            return today
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise CommandError(f'Ungültiges Datum "{value}", erwartet YYYY-MM-DD.')
        if parsed > today:
            raise CommandError('Der Stichtag darf nicht in der Zukunft liegen.')
        return parsed
