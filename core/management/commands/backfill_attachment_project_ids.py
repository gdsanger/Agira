"""
Management command to backfill project_id in Weaviate for existing attachments.

This script updates AgiraObject entries in Weaviate to include the correct project_id
for all attachments. The project_id is determined via the AttachmentLink relationship
to the parent object (Project, Item, Comment, etc.).
"""

import logging
from django.core.management.base import BaseCommand
from core.models import Attachment, Project
from core.services.weaviate.service import upsert_instance

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Backfill project_id in Weaviate for existing attachments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be updated without making changes to Weaviate',
        )
        parser.add_argument(
            '--project-id',
            type=int,
            help='Only process attachments for a specific project ID',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        project_id_filter = options.get('project_id')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('Running in DRY RUN mode - no changes will be made to Weaviate'))
        
        # Get all attachments with links
        attachments = Attachment.objects.prefetch_related('links__target').all()
        
        if project_id_filter:
            # Filter to only attachments linked to objects in the specified project
            # This is complex due to generic foreign keys, so we'll filter during processing
            self.stdout.write(f'Filtering to attachments for project {project_id_filter}...')
        
        total_count = attachments.count()
        self.stdout.write(f'Found {total_count} total attachments to check...')
        
        processed_count = 0
        updated_count = 0
        skipped_count = 0
        error_count = 0
        
        for attachment in attachments:
            # Get project_id via serialization logic
            project_id = self._get_attachment_project_id(attachment)
            
            # Apply project filter if specified
            if project_id_filter and (not project_id or int(project_id) != project_id_filter):
                continue
            
            processed_count += 1
            
            if project_id:
                if dry_run:
                    self.stdout.write(
                        f'  Would update Attachment {attachment.id} ({attachment.original_name}): '
                        f'project_id={project_id}'
                    )
                    updated_count += 1
                else:
                    try:
                        # Upsert to Weaviate (this will use the fixed serializer)
                        upsert_instance(attachment)
                        updated_count += 1
                        
                        if updated_count % 100 == 0:
                            self.stdout.write(f'  Processed {updated_count} attachments...')
                    except Exception as e:
                        error_count += 1
                        logger.error(f'Error updating attachment {attachment.id} in Weaviate: {e}')
                        self.stdout.write(self.style.ERROR(
                            f'  Error updating Attachment {attachment.id}: {e}'
                        ))
            else:
                skipped_count += 1
                logger.debug(f'Skipped attachment {attachment.id} - no project_id found')
        
        # Print summary
        self.stdout.write('\n' + '=' * 60)
        self.stdout.write(self.style.SUCCESS('Backfill Summary:'))
        self.stdout.write(f'  Total attachments checked: {total_count}')
        self.stdout.write(f'  Attachments processed: {processed_count}')
        self.stdout.write(f'  Attachments updated: {updated_count}')
        self.stdout.write(f'  Attachments skipped (no project_id): {skipped_count}')
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f'  Errors: {error_count}'))
        self.stdout.write('=' * 60)
        
        if dry_run:
            self.stdout.write(self.style.WARNING(
                f'\nDRY RUN: Would have updated {updated_count} attachments in Weaviate. '
                f'Run without --dry-run to apply changes.'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\n✓ Successfully backfilled project_id for {updated_count} attachments in Weaviate.'
            ))
    
    def _get_attachment_project_id(self, attachment):
        """
        Extract project_id from attachment using the same logic as the serializer.
        
        Args:
            attachment: Attachment instance
            
        Returns:
            project_id as string, or None if not found
        """
        if not hasattr(attachment, 'links'):
            return None
        
        first_link = attachment.links.first()
        if not first_link:
            return None
        
        target = first_link.target
        if not target:
            return None
        
        # If target is a Project, use its ID as project_id
        if isinstance(target, Project):
            return str(target.id)
        
        # Otherwise, check if target has project_id attribute
        if hasattr(target, 'project_id') and target.project_id:
            return str(target.project_id)
        
        return None
