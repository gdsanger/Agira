"""
Management command to backfill ItemRelations from Item.parent field.

This command creates ItemRelation entries (type=Related) for all Items
that have a parent field set but no corresponding ItemRelation entry.

Usage:
    python manage.py backfill_item_relations

The command is idempotent - running it multiple times will not create duplicates.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import Item, ItemRelation, RelationType


class Command(BaseCommand):
    help = 'Backfill ItemRelations from Item.parent field (idempotent)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be created without actually creating relations',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Find all items with parent set
        items_with_parent = Item.objects.filter(parent__isnull=False).select_related('parent')
        total_items = items_with_parent.count()
        
        self.stdout.write(f'Found {total_items} items with parent field set')
        
        created_count = 0
        skipped_count = 0
        error_count = 0
        
        for item in items_with_parent:
            # Check if relation already exists
            existing = ItemRelation.objects.filter(
                from_item=item.parent,
                to_item=item,
                relation_type=RelationType.RELATED
            ).exists()
            
            if existing:
                skipped_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f'  SKIP: Relation already exists for Item {item.id} → {item.title}'
                    )
                )
                continue
            
            # Create the relation
            try:
                if not dry_run:
                    with transaction.atomic():
                        ItemRelation.objects.create(
                            from_item=item.parent,
                            to_item=item,
                            relation_type=RelationType.RELATED
                        )
                
                created_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  CREATE: Item {item.parent.id} ({item.parent.title[:50]}) '
                        f'→ Item {item.id} ({item.title[:50]})'
                    )
                )
            except Exception as e:
                error_count += 1
                self.stdout.write(
                    self.style.ERROR(
                        f'  ERROR: Failed to create relation for Item {item.id}: {str(e)}'
                    )
                )
        
        # Summary
        self.stdout.write('\n' + '=' * 70)
        self.stdout.write(self.style.SUCCESS(f'Backfill completed!'))
        self.stdout.write(f'  Total items with parent: {total_items}')
        self.stdout.write(self.style.SUCCESS(f'  Created: {created_count}'))
        self.stdout.write(self.style.WARNING(f'  Skipped (already exists): {skipped_count}'))
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f'  Errors: {error_count}'))
        
        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - No changes were made'))
            self.stdout.write('Run without --dry-run to apply changes')
