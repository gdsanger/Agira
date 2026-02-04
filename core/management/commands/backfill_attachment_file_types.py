"""
Management command to backfill file_type for existing Attachment records.
"""

from django.core.management.base import BaseCommand
from core.models import Attachment


class Command(BaseCommand):
    help = 'Backfill file_type field for existing Attachment records'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        # Get all attachments without file_type
        attachments = Attachment.objects.filter(file_type='')
        total_count = attachments.count()
        
        if total_count == 0:
            self.stdout.write(self.style.SUCCESS('No attachments need file_type backfill.'))
            return
        
        self.stdout.write(f'Found {total_count} attachments to process...')
        
        updated_count = 0
        for attachment in attachments:
            old_file_type = attachment.file_type
            new_file_type = attachment.determine_file_type()
            
            if dry_run:
                self.stdout.write(
                    f'  Would update Attachment {attachment.id} ({attachment.original_name}): '
                    f'"{old_file_type}" -> "{new_file_type}"'
                )
            else:
                attachment.file_type = new_file_type
                attachment.save(update_fields=['file_type'])
                updated_count += 1
                
                if updated_count % 100 == 0:
                    self.stdout.write(f'  Processed {updated_count}/{total_count}...')
        
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'DRY RUN: Would have updated {total_count} attachments. '
                f'Run without --dry-run to apply changes.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'Successfully backfilled file_type for {updated_count} attachments.'
            ))
