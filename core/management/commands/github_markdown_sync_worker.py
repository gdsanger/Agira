"""
Django management command for GitHub markdown sync worker.

This command synchronizes markdown files from GitHub repositories
to Agira project attachments and indexes them in Weaviate.
This worker is separate from the main github_sync_worker to allow
independent scheduling since markdown sync is slower and less frequent.
"""

import logging
from typing import Optional, Dict, Any
from django.core.management.base import BaseCommand, CommandError

from core.models import Project
from core.services.github.service import GitHubService
from core.services.github_sync.markdown_sync import MarkdownSyncService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Synchronize markdown files from GitHub repositories to Agira project attachments'

    def add_arguments(self, parser):
        """Add command arguments."""
        parser.add_argument(
            '--project-id',
            type=int,
            help='Only sync markdown files for a specific project ID',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be synced without making changes',
        )

    def handle(self, *args, **options):
        """Execute the markdown sync worker."""
        project_id = options.get('project_id')
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('Running in DRY RUN mode - no changes will be made'))

        self.stdout.write("Starting GitHub markdown sync worker...")

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

        # Sync markdown files from GitHub repositories
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Syncing Markdown Files from GitHub Repositories")
        self.stdout.write("=" * 60)
        
        markdown_stats = self._sync_markdown_files(
            github_service=github_service,
            project_id=project_id,
            dry_run=dry_run,
        )
        
        # Print summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("Sync Summary:"))
        self.stdout.write(f"  Projects processed: {markdown_stats['projects_processed']}")
        self.stdout.write(f"  Files found: {markdown_stats['total_files_found']}")
        self.stdout.write(f"  Files created: {markdown_stats['total_files_created']}")
        self.stdout.write(f"  Files updated: {markdown_stats['total_files_updated']}")
        self.stdout.write(f"  Files skipped: {markdown_stats['total_files_skipped']}")
        if markdown_stats['total_errors'] > 0:
            self.stdout.write(self.style.ERROR(f"  Errors: {markdown_stats['total_errors']}"))
        
        self.stdout.write("=" * 60)

        if dry_run:
            self.stdout.write(self.style.WARNING('\nDRY RUN - No changes were made'))
        else:
            self.stdout.write(self.style.SUCCESS('\n✓ GitHub markdown sync completed successfully'))
    
    def _sync_markdown_files(
        self,
        github_service: GitHubService,
        project_id: Optional[int] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Sync markdown files from GitHub repositories for all projects.
        
        Args:
            github_service: GitHub service instance
            project_id: Optional project ID to filter to
            dry_run: If True, don't make actual changes
            
        Returns:
            Dictionary with sync statistics
        """
        stats = {
            'projects_processed': 0,
            'total_files_found': 0,
            'total_files_created': 0,
            'total_files_updated': 0,
            'total_files_skipped': 0,
            'total_errors': 0,
        }
        
        # Get projects with GitHub repo configured
        projects = Project.objects.exclude(github_owner='').exclude(github_repo='')
        
        if project_id:
            projects = projects.filter(id=project_id)
        
        total_projects = projects.count()
        
        if total_projects == 0:
            self.stdout.write("No projects with GitHub repositories found")
            return stats
        
        self.stdout.write(f"Found {total_projects} projects with GitHub repositories")
        
        # Initialize markdown sync service
        client = github_service._get_client()
        markdown_service = MarkdownSyncService(github_client=client)
        
        # Process each project
        for project in projects:
            try:
                self.stdout.write(f"\n  Project: {project.name} ({project.github_owner}/{project.github_repo})")
                
                if dry_run:
                    self.stdout.write(self.style.WARNING("    [DRY RUN] Would sync markdown files"))
                    stats['projects_processed'] += 1
                    continue
                
                # Sync markdown files for this project
                project_stats = markdown_service.sync_project_markdown_files(project)
                
                # Update overall stats
                stats['projects_processed'] += 1
                stats['total_files_found'] += project_stats['files_found']
                stats['total_files_created'] += project_stats['files_created']
                stats['total_files_updated'] += project_stats['files_updated']
                stats['total_files_skipped'] += project_stats['files_skipped']
                stats['total_errors'] += len(project_stats['errors'])
                
                # Log results
                self.stdout.write(
                    f"    ✓ Found {project_stats['files_found']} .md files: "
                    f"{project_stats['files_created']} created, "
                    f"{project_stats['files_updated']} updated, "
                    f"{project_stats['files_skipped']} skipped"
                )
                
                # Log errors if any
                for error in project_stats['errors']:
                    self.stdout.write(self.style.ERROR(f"    ✗ {error}"))
                    
            except Exception as e:
                stats['total_errors'] += 1
                logger.error(
                    f"Error syncing markdown files for project {project.id}: {e}",
                    exc_info=True,
                )
                self.stdout.write(
                    self.style.ERROR(f"    ✗ Error: {e}")
                )
        
        return stats
