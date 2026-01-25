"""
Markdown Sync Service

Synchronizes markdown files from GitHub repositories to Agira project attachments.
"""

import io
import logging
from typing import List, Dict, Any, Optional, Tuple
from django.db import transaction
from django.utils import timezone

from core.models import Project, Attachment, AttachmentLink, AttachmentRole
from core.services.github.client import GitHubClient
from core.services.storage.service import AttachmentStorageService
from core.services.weaviate.service import upsert_instance

logger = logging.getLogger(__name__)


class MarkdownSyncService:
    """
    Service for syncing markdown files from GitHub repositories to Agira.
    
    Handles:
    - Finding all .md files in a repository
    - Creating/updating attachments for markdown files
    - Tracking versions via GitHub SHA
    - Indexing content in Weaviate
    """
    
    def __init__(self, github_client: GitHubClient):
        """
        Initialize markdown sync service.
        
        Args:
            github_client: Configured GitHub client instance
        """
        self.github_client = github_client
        self.storage_service = AttachmentStorageService()
    
    def sync_project_markdown_files(
        self,
        project: Project,
        ref: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Sync all markdown files for a project from its GitHub repository.
        
        Args:
            project: Project with GitHub repo configuration
            ref: Git reference (branch/tag/sha), defaults to repo's default branch
            
        Returns:
            Dictionary with sync statistics:
                - files_found: Number of .md files found
                - files_created: Number of new attachments created
                - files_updated: Number of existing attachments updated
                - files_skipped: Number of files skipped (no changes)
                - errors: List of error messages
        """
        stats = {
            'files_found': 0,
            'files_created': 0,
            'files_updated': 0,
            'files_skipped': 0,
            'errors': [],
        }
        
        # Validate project has GitHub repo configured
        if not project.github_owner or not project.github_repo:
            error_msg = f"Project {project.id} has no GitHub repository configured"
            logger.warning(error_msg)
            stats['errors'].append(error_msg)
            return stats
        
        owner = project.github_owner
        repo = project.github_repo
        
        logger.info(f"Syncing markdown files for project {project.id} from {owner}/{repo}")
        
        try:
            # Find all markdown files in the repository
            md_files = self._find_markdown_files(owner, repo, ref=ref)
            stats['files_found'] = len(md_files)
            
            logger.info(f"Found {len(md_files)} markdown files in {owner}/{repo}")
            
            # Sync each file
            for file_info in md_files:
                try:
                    result = self._sync_markdown_file(
                        project=project,
                        owner=owner,
                        repo=repo,
                        file_info=file_info,
                        ref=ref,
                    )
                    
                    if result == 'created':
                        stats['files_created'] += 1
                    elif result == 'updated':
                        stats['files_updated'] += 1
                    elif result == 'skipped':
                        stats['files_skipped'] += 1
                        
                except Exception as e:
                    error_msg = f"Error syncing {file_info['path']}: {str(e)}"
                    logger.error(error_msg, exc_info=True)
                    stats['errors'].append(error_msg)
            
            logger.info(
                f"Sync complete for project {project.id}: "
                f"{stats['files_created']} created, "
                f"{stats['files_updated']} updated, "
                f"{stats['files_skipped']} skipped, "
                f"{len(stats['errors'])} errors"
            )
            
        except Exception as e:
            error_msg = f"Failed to sync markdown files for project {project.id}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            stats['errors'].append(error_msg)
        
        return stats
    
    def _find_markdown_files(
        self,
        owner: str,
        repo: str,
        path: str = '',
        ref: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Recursively find all .md files in a GitHub repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            path: Current path to search (empty for root)
            ref: Git reference
            
        Returns:
            List of file info dictionaries with 'path', 'sha', 'size' keys
        """
        markdown_files = []
        
        try:
            # Get contents at current path
            contents = self.github_client.get_repository_contents(
                owner, repo, path, ref
            )
            
            # Handle single file response (shouldn't happen for directory listing)
            if isinstance(contents, dict):
                contents = [contents]
            
            for item in contents:
                item_type = item.get('type')
                item_path = item.get('path', '')
                
                if item_type == 'file' and item_path.lower().endswith('.md'):
                    # This is a markdown file
                    markdown_files.append({
                        'path': item_path,
                        'sha': item.get('sha', ''),
                        'size': item.get('size', 0),
                        'name': item.get('name', ''),
                    })
                    
                elif item_type == 'dir':
                    # Recursively search subdirectories
                    try:
                        subdir_files = self._find_markdown_files(
                            owner, repo, item_path, ref
                        )
                        markdown_files.extend(subdir_files)
                    except Exception as e:
                        logger.warning(f"Failed to search directory {item_path}: {e}")
                        
        except Exception as e:
            logger.error(f"Failed to get repository contents at {path}: {e}")
            raise
        
        return markdown_files
    
    def _sync_markdown_file(
        self,
        project: Project,
        owner: str,
        repo: str,
        file_info: Dict[str, Any],
        ref: Optional[str] = None,
    ) -> str:
        """
        Sync a single markdown file to project attachments.
        
        Args:
            project: Target project
            owner: Repository owner
            repo: Repository name
            file_info: File metadata from GitHub (path, sha, size, name)
            ref: Git reference
            
        Returns:
            'created', 'updated', or 'skipped'
        """
        file_path = file_info['path']
        github_sha = file_info['sha']
        file_name = file_info['name']
        
        # Build unique identifier: owner/repo/path
        repo_identifier = f"{owner}/{repo}"
        
        # Check if attachment already exists
        existing_attachment = self._find_existing_attachment(
            project, repo_identifier, file_path
        )
        
        if existing_attachment:
            # Check if file has changed
            if existing_attachment.github_sha == github_sha:
                logger.debug(f"File {file_path} unchanged (SHA: {github_sha})")
                return 'skipped'
            
            # File has changed, update it
            logger.info(f"Updating changed file: {file_path}")
            self._update_attachment(
                existing_attachment, owner, repo, file_path, github_sha, ref
            )
            return 'updated'
        else:
            # New file, create attachment
            logger.info(f"Creating new attachment for: {file_path}")
            self._create_attachment(
                project, owner, repo, file_path, github_sha, file_name, ref
            )
            return 'created'
    
    def _find_existing_attachment(
        self,
        project: Project,
        repo_identifier: str,
        file_path: str,
    ) -> Optional[Attachment]:
        """
        Find existing attachment for a GitHub file.
        
        Args:
            project: Project to search in
            repo_identifier: Repository identifier (owner/repo)
            file_path: File path in repository
            
        Returns:
            Attachment if found, None otherwise
        """
        # Build the repo path we'd store: owner/repo:path
        github_repo_path = f"{repo_identifier}:{file_path}"
        
        # Find attachments linked to this project with matching github_repo_path
        from django.contrib.contenttypes.models import ContentType
        project_ct = ContentType.objects.get_for_model(Project)
        
        # Find attachment links to this project
        links = AttachmentLink.objects.filter(
            target_content_type=project_ct,
            target_object_id=project.id,
            role=AttachmentRole.PROJECT_FILE,
        ).select_related('attachment')
        
        # Check each linked attachment for matching github_repo_path
        for link in links:
            if link.attachment.github_repo_path == github_repo_path:
                return link.attachment
        
        return None
    
    @transaction.atomic
    def _create_attachment(
        self,
        project: Project,
        owner: str,
        repo: str,
        file_path: str,
        github_sha: str,
        file_name: str,
        ref: Optional[str] = None,
    ) -> Attachment:
        """
        Create new attachment for a GitHub markdown file.
        
        Args:
            project: Target project
            owner: Repository owner
            repo: Repository name  
            file_path: File path in repository
            github_sha: GitHub blob SHA
            file_name: File name
            ref: Git reference
            
        Returns:
            Created Attachment instance
        """
        # Download file content
        content = self.github_client.get_file_content(owner, repo, file_path, ref)
        
        # Create a file-like object
        file_obj = io.BytesIO(content)
        file_obj.name = file_name
        
        # Store using AttachmentStorageService
        attachment = self.storage_service.store_attachment(
            file=file_obj,
            target=project,
            created_by=None,  # System-created
            compute_hash=True,
        )
        
        # Update GitHub metadata
        repo_identifier = f"{owner}/{repo}"
        attachment.github_repo_path = f"{repo_identifier}:{file_path}"
        attachment.github_sha = github_sha
        attachment.github_last_synced = timezone.now()
        attachment.content_type = 'text/markdown'
        attachment.save(update_fields=[
            'github_repo_path', 'github_sha', 'github_last_synced', 'content_type'
        ])
        
        logger.info(f"Created attachment {attachment.id} for {file_path}")
        
        # Index in Weaviate
        try:
            upsert_instance(attachment)
            logger.debug(f"Indexed attachment {attachment.id} in Weaviate")
        except Exception as e:
            logger.warning(f"Failed to index attachment {attachment.id} in Weaviate: {e}")
        
        return attachment
    
    @transaction.atomic
    def _update_attachment(
        self,
        attachment: Attachment,
        owner: str,
        repo: str,
        file_path: str,
        github_sha: str,
        ref: Optional[str] = None,
    ) -> None:
        """
        Update existing attachment with new content from GitHub.
        
        Args:
            attachment: Existing attachment to update
            owner: Repository owner
            repo: Repository name
            file_path: File path in repository
            github_sha: New GitHub blob SHA
            ref: Git reference
        """
        # Download new content
        content = self.github_client.get_file_content(owner, repo, file_path, ref)
        
        # Get absolute path to existing file
        file_path_abs = self.storage_service.get_file_path(attachment)
        
        # Write new content
        import hashlib
        with open(file_path_abs, 'wb') as f:
            f.write(content)
        
        # Update metadata
        attachment.size_bytes = len(content)
        attachment.github_sha = github_sha
        attachment.github_last_synced = timezone.now()
        
        # Recompute hash
        sha256_hash = hashlib.sha256(content).hexdigest()
        attachment.sha256 = sha256_hash
        
        attachment.save(update_fields=[
            'size_bytes', 'github_sha', 'github_last_synced', 'sha256'
        ])
        
        logger.info(f"Updated attachment {attachment.id} for {file_path}")
        
        # Update in Weaviate
        try:
            upsert_instance(attachment)
            logger.debug(f"Updated attachment {attachment.id} in Weaviate")
        except Exception as e:
            logger.warning(f"Failed to update attachment {attachment.id} in Weaviate: {e}")
