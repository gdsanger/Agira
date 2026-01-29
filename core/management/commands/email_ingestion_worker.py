"""
Django management command for email ingestion worker.

This command fetches emails from Microsoft Graph API inbox and creates
items in Agira projects with AI-powered classification.
"""

import logging
from django.core.management.base import BaseCommand, CommandError

from core.services.graph.email_ingestion_service import EmailIngestionService
from core.services.exceptions import ServiceNotConfigured, ServiceDisabled

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fetch emails from Microsoft Graph API and create items in Agira'

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            '--max-messages',
            type=int,
            default=50,
            help='Maximum number of messages to process (default: 50)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be processed without making changes',
        )

    def handle(self, *args, **options):
        """Execute the email ingestion worker."""
        max_messages = options['max_messages']
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('Running in DRY RUN mode - no changes will be made'))

        self.stdout.write("Starting email ingestion worker...")

        try:
            # Initialize email ingestion service
            service = EmailIngestionService()
            
        except ServiceDisabled as e:
            raise CommandError(f"Graph API service is disabled: {e}")
            
        except ServiceNotConfigured as e:
            raise CommandError(f"Graph API service is not configured: {e}")

        # Process inbox
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(f"Processing inbox: {service.mailbox}")
        self.stdout.write("=" * 60)

        try:
            stats = service.process_inbox(
                max_messages=max_messages,
                dry_run=dry_run,
            )
            
            # Display statistics
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write("Processing Statistics")
            self.stdout.write("=" * 60)
            self.stdout.write(f"Messages fetched:  {stats['fetched']}")
            self.stdout.write(f"Messages processed: {stats['processed']}")
            self.stdout.write(f"Errors:            {stats['errors']}")
            self.stdout.write(f"Skipped:           {stats['skipped']}")
            
            if stats['errors'] > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"\nCompleted with {stats['errors']} error(s). "
                        "Check logs for details."
                    )
                )
            elif stats['processed'] > 0:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\nSuccessfully processed {stats['processed']} message(s)"
                    )
                )
            else:
                self.stdout.write(self.style.SUCCESS("\nNo messages to process"))
                
        except Exception as e:
            logger.exception("Error during email ingestion")
            raise CommandError(f"Email ingestion failed: {e}")
