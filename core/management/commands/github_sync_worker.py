"""
Django management command for GitHub sync worker.

This command synchronizes ExternalIssueMapping entries with GitHub,
updates Item statuses, links PRs, and pushes content to Weaviate.
"""

import logging
from typing import Optional, Dict, Any, List
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import (
    ExternalIssueMapping,
    ExternalIssueKind,
    Item,
    ItemStatus,
)
from core.services.github.service import GitHubService
from core.services.integrations.base import IntegrationError
from core.services.weaviate.service import (
    upsert_instance,
    exists_instance,
    fetch_object,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Synchronize GitHub issues/PRs with Agira items and push to Weaviate'

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            '--batch-size',
            type=int,
            default=50,
            help='Number of mappings to process per batch (default: 50)',
        )
        parser.add_argument(
            '--project-id',
            type=int,
            help='Only sync mappings for a specific project ID',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be synced without making changes',
        )

    def handle(self, *args, **options):
        """Execute the sync worker."""
        batch_size = options['batch_size']
        project_id = options.get('project_id')
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('Running in DRY RUN mode - no changes will be made'))

        self.stdout.write("Starting GitHub sync worker...")

        # Initialize GitHub service
        github_service = GitHubService()
        
        # Check if GitHub is available
        if not github_service.is_enabled():
            raise CommandError(
                "GitHub integration is not enabled. "
                "Please enable it in Django admin first."
            )
        
        if not github_service.is_configured():
            raise CommandError(
                "GitHub integration is not configured. "
                "Please configure GitHub token in Django admin."
            )

        # Build queryset
        queryset = ExternalIssueMapping.objects.select_related('item', 'item__project')
        
        if project_id:
            queryset = queryset.filter(item__project_id=project_id)
            self.stdout.write(f"Filtering to project ID: {project_id}")
        
        # Only process ISSUE kind (not PRs directly, they are linked via issues)
        queryset = queryset.filter(kind=ExternalIssueKind.ISSUE)
        
        total = queryset.count()
        self.stdout.write(f"Found {total} issue mappings to sync")

        if total == 0:
            self.stdout.write(self.style.SUCCESS("No mappings to sync"))
            return

        # Process in batches
        synced_count = 0
        status_updated_count = 0
        prs_linked_count = 0
        weaviate_pushed_count = 0
        error_count = 0

        for batch_start in range(0, total, batch_size):
            batch_end = min(batch_start + batch_size, total)
            self.stdout.write(f"\nProcessing batch {batch_start + 1}-{batch_end} of {total}...")

            batch = queryset[batch_start:batch_end]

            for mapping in batch:
                try:
                    result = self._sync_mapping(
                        mapping,
                        github_service,
                        dry_run=dry_run,
                    )
                    
                    synced_count += 1
                    if result['status_updated']:
                        status_updated_count += 1
                    prs_linked_count += result['prs_linked']
                    if result['weaviate_pushed']:
                        weaviate_pushed_count += 1

                except Exception as e:
                    error_count += 1
                    logger.error(
                        f"Error syncing mapping {mapping.id} (Issue #{mapping.number}): {e}",
                        exc_info=True,
                    )
                    self.stdout.write(
                        self.style.ERROR(
                            f"  ✗ Error syncing Issue #{mapping.number}: {e}"
                        )
                    )

        # Print summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("Sync Summary:"))
        self.stdout.write(f"  Total mappings processed: {synced_count}/{total}")
        self.stdout.write(f"  Item statuses updated: {status_updated_count}")
        self.stdout.write(f"  PRs linked: {prs_linked_count}")
        self.stdout.write(f"  Objects pushed to Weaviate: {weaviate_pushed_count}")
        if error_count > 0:
            self.stdout.write(self.style.ERROR(f"  Errors: {error_count}"))
        self.stdout.write("=" * 60)

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - No changes were made'))
        else:
            self.stdout.write(self.style.SUCCESS('\n✓ GitHub sync completed successfully'))

    def _sync_mapping(
        self,
        mapping: ExternalIssueMapping,
        github_service: GitHubService,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Sync a single ExternalIssueMapping.
        
        Args:
            mapping: The mapping to sync
            github_service: GitHub service instance
            dry_run: If True, don't make actual changes
            
        Returns:
            Dictionary with sync results:
                - status_updated: bool
                - prs_linked: int
                - weaviate_pushed: bool
        """
        result = {
            'status_updated': False,
            'prs_linked': 0,
            'weaviate_pushed': False,
        }

        item = mapping.item
        old_mapping_state = mapping.state
        old_item_status = item.status

        # 1. Sync mapping state from GitHub
        if not dry_run:
            github_service.sync_mapping(mapping)
        
        # Reload to get updated state
        mapping.refresh_from_db()
        state_changed = old_mapping_state != mapping.state

        self.stdout.write(
            f"  Issue #{mapping.number}: {old_mapping_state} → {mapping.state}"
        )

        # 2. Update Item status if issue was closed
        if mapping.state == 'closed' and item.status != ItemStatus.TESTING:
            if not dry_run:
                with transaction.atomic():
                    item.status = ItemStatus.TESTING
                    item.save(update_fields=['status'])
                
                self.stdout.write(
                    self.style.SUCCESS(
                        f"    ✓ Updated Item #{item.id} status: {old_item_status} → Testing"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"    [DRY RUN] Would update Item #{item.id} status to Testing"
                    )
                )
            result['status_updated'] = True

        # 3. Link related PRs
        linked_prs = self._link_prs_for_issue(
            mapping,
            github_service,
            dry_run=dry_run,
        )
        result['prs_linked'] = linked_prs

        # 4. Push to Weaviate if status changed or not yet synced
        should_push = self._should_push_to_weaviate(mapping, state_changed)
        
        if should_push:
            if not dry_run:
                pushed = self._push_to_weaviate(mapping, github_service)
                result['weaviate_pushed'] = pushed
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"    [DRY RUN] Would push to Weaviate"
                    )
                )
                result['weaviate_pushed'] = True

        return result

    def _link_prs_for_issue(
        self,
        mapping: ExternalIssueMapping,
        github_service: GitHubService,
        dry_run: bool = False,
    ) -> int:
        """
        Find and link PRs related to an issue.
        
        Args:
            mapping: Issue mapping
            github_service: GitHub service instance
            dry_run: If True, don't make actual changes
            
        Returns:
            Number of PRs linked
        """
        try:
            owner, repo = github_service._get_repo_info(mapping.item)
            client = github_service._get_client()
            
            # Get timeline events to find linked PRs
            timeline = client.get_issue_timeline(owner, repo, mapping.number)
            
            pr_numbers = set()
            
            # Look for cross-referenced PRs in timeline
            for event in timeline:
                event_type = event.get('event')
                
                # Check for cross-reference events
                if event_type == 'cross-referenced':
                    source = event.get('source', {})
                    if source.get('type') == 'issue':
                        # In GitHub, PRs are also issues
                        issue_data = source.get('issue', {})
                        if 'pull_request' in issue_data:
                            # This is a PR
                            pr_number = issue_data.get('number')
                            if pr_number:
                                pr_numbers.add(pr_number)
                
                # Also check for referenced events (mentions in commits/PRs)
                elif event_type == 'referenced':
                    # Check if the reference comes from a commit in a PR
                    commit_id = event.get('commit_id')
                    if commit_id:
                        # We could fetch the PR for this commit, but that's expensive
                        # For now, we rely on cross-references
                        pass

            # Create mappings for each found PR
            linked_count = 0
            for pr_number in pr_numbers:
                try:
                    if not dry_run:
                        # Use upsert_mapping_from_github to create/update PR mapping
                        pr_mapping = github_service.upsert_mapping_from_github(
                            item=mapping.item,
                            number=pr_number,
                            kind='pr',
                        )
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"    ✓ Linked PR #{pr_number} to Item #{mapping.item.id}"
                            )
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"    [DRY RUN] Would link PR #{pr_number}"
                            )
                        )
                    linked_count += 1
                except Exception as e:
                    logger.warning(f"Failed to link PR #{pr_number}: {e}")
                    self.stdout.write(
                        self.style.WARNING(
                            f"    ⚠ Could not link PR #{pr_number}: {e}"
                        )
                    )
            
            return linked_count

        except Exception as e:
            logger.warning(f"Failed to fetch timeline for issue #{mapping.number}: {e}")
            return 0

    def _should_push_to_weaviate(
        self,
        mapping: ExternalIssueMapping,
        state_changed: bool,
    ) -> bool:
        """
        Determine if mapping should be pushed to Weaviate.
        
        Per requirements: Only update if status changed or object doesn't exist.
        
        Args:
            mapping: The mapping to check
            state_changed: Whether the GitHub state changed
            
        Returns:
            True if should push to Weaviate
        """
        # Always push if state changed
        if state_changed:
            return True
        
        # Check if object exists in Weaviate
        try:
            from core.services.weaviate.service import exists_object
            exists = exists_object('github_issue', str(mapping.id))
            # Push if it doesn't exist
            return not exists
        except Exception as e:
            logger.debug(f"Could not check Weaviate existence: {e}")
            # If we can't check, don't push (conservative approach)
            return False

    def _push_to_weaviate(
        self,
        mapping: ExternalIssueMapping,
        github_service: GitHubService,
    ) -> bool:
        """
        Push issue and linked PRs to Weaviate.
        
        Args:
            mapping: Issue mapping to push
            github_service: GitHub service instance
            
        Returns:
            True if successfully pushed
        """
        try:
            from core.services.weaviate import is_available
            
            # Check if Weaviate is available
            if not is_available():
                logger.debug("Weaviate is not available, skipping push")
                return False

            # Get GitHub issue data for richer content
            owner, repo = github_service._get_repo_info(mapping.item)
            client = github_service._get_client()
            issue_data = client.get_issue(owner, repo, mapping.number)
            
            # Update mapping with latest data before serializing
            # The serializer will use this data
            
            # Push the issue mapping itself (serializer handles GitHub issue type)
            uuid_str = upsert_instance(mapping)
            
            if uuid_str:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"    ✓ Pushed Issue #{mapping.number} to Weaviate"
                    )
                )
            
            # Also push the Item itself (with updated status)
            item_uuid = upsert_instance(mapping.item)
            
            # Push linked PRs
            pr_mappings = ExternalIssueMapping.objects.filter(
                item=mapping.item,
                kind=ExternalIssueKind.PR,
            )
            
            for pr_mapping in pr_mappings:
                try:
                    pr_uuid = upsert_instance(pr_mapping)
                    if pr_uuid:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"    ✓ Pushed PR #{pr_mapping.number} to Weaviate"
                            )
                        )
                except Exception as e:
                    logger.warning(f"Failed to push PR #{pr_mapping.number} to Weaviate: {e}")

            return bool(uuid_str)

        except Exception as e:
            logger.error(f"Failed to push to Weaviate: {e}", exc_info=True)
            return False
