"""
GitHub Service

Main service for GitHub integration with Agira Items.
"""

import logging
from typing import Optional
from django.db import transaction
from django.utils import timezone

from core.models import (
    GitHubConfiguration,
    Project,
    Item,
    ItemStatus,
    ExternalIssueMapping,
    ExternalIssueKind,
    Activity,
    User,
)
from core.services.integrations.base import (
    IntegrationBase,
    IntegrationDisabled,
    IntegrationNotConfigured,
)
from .client import GitHubClient

logger = logging.getLogger(__name__)



class GitHubService(IntegrationBase):
    """
    GitHub service for issue and PR management.
    
    Features:
    - Create issues from Agira items
    - Sync GitHub issues/PRs to Agira
    - Maintain ExternalIssueMapping
    - Log activities
    """
    
    def __init__(self):
        """Initialize GitHub service."""
        self._client = None
        self._config = None
    
    def _get_config(self) -> GitHubConfiguration:
        """Get GitHub configuration singleton."""
        if self._config is None:
            self._config = GitHubConfiguration.load()
        return self._config
    
    def is_enabled(self) -> bool:
        """Check if GitHub integration is enabled."""
        config = self._get_config()
        return config.enable_github
    
    def is_configured(self) -> bool:
        """Check if GitHub has required configuration."""
        config = self._get_config()
        return bool(config.github_token)
    
    def _get_client(self) -> GitHubClient:
        """
        Get GitHub API client.
        
        Returns:
            Configured GitHub client
            
        Raises:
            IntegrationDisabled: If GitHub is disabled
            IntegrationNotConfigured: If GitHub is not configured
        """
        self._check_availability()
        
        if self._client is None:
            config = self._get_config()
            self._client = GitHubClient(
                token=config.github_token,
                base_url=config.github_api_base_url,
            )
        
        return self._client
    
    def _get_repo_info(self, item: Item) -> tuple[str, str]:
        """
        Get GitHub owner and repo from item's project.
        
        Args:
            item: Agira item
            
        Returns:
            Tuple of (owner, repo)
            
        Raises:
            ValueError: If project doesn't have GitHub repo configured
        """
        project = item.project
        
        if not project.github_owner or not project.github_repo:
            raise ValueError(
                f"Project '{project.name}' does not have GitHub repository configured"
            )
        
        return project.github_owner, project.github_repo
    
    def _map_state(self, github_data: dict, kind: str) -> str:
        """
        Map GitHub state to our state format.
        
        Args:
            github_data: GitHub issue/PR data
            kind: 'issue' or 'pr'
            
        Returns:
            State string ('open', 'closed', or 'merged' for PRs)
        """
        state = github_data.get('state', 'open')
        
        # For PRs, check if merged
        if kind == 'pr' and github_data.get('merged_at'):
            return 'merged'
        
        return state
    
    def _log_activity(
        self,
        item: Item,
        verb: str,
        summary: str,
        actor=None
    ):
        """
        Log activity for an item.
        
        Args:
            item: Agira item
            verb: Activity verb (e.g., 'github.issue_created')
            summary: Activity summary
            actor: User performing the action (optional)
        """
        try:
            from django.contrib.contenttypes.models import ContentType
            from django.core.exceptions import ObjectDoesNotExist
            
            Activity.objects.create(
                target_content_type=ContentType.objects.get_for_model(Item),
                target_object_id=item.id,
                verb=verb,
                actor=actor,
                summary=summary,
            )
        except (ObjectDoesNotExist, ValueError, TypeError) as e:
            # Activity logging is non-critical, log and continue
            logger.warning(f"Failed to log activity: {e}")
    
    def can_create_issue_for_item(self, item: Item) -> bool:
        """
        Check if a GitHub issue can be created for the given item.
        
        An issue can be created if the item's status is one of:
        - Backlog
        - Working
        - Testing
        
        Args:
            item: Item to check
            
        Returns:
            True if issue can be created, False otherwise
        """
        allowed_statuses = [
            ItemStatus.BACKLOG,
            ItemStatus.WORKING,
            ItemStatus.TESTING,
        ]
        
        return item.status in allowed_statuses
    
    def create_issue_for_item(
        self,
        item: Item,
        *,
        title: Optional[str] = None,
        body: Optional[str] = None,
        labels: Optional[list[str]] = None,
        actor=None,
    ) -> ExternalIssueMapping:
        """
        Create a GitHub issue for an Agira item.
        
        Args:
            item: Agira item to create issue for
            title: Issue title (default: item.title)
            body: Issue body (default: rendered from item.description)
            labels: List of label names
            actor: User creating the issue
            
        Returns:
            Created ExternalIssueMapping
            
        Raises:
            IntegrationDisabled: If GitHub is disabled
            IntegrationNotConfigured: If GitHub is not configured
            ValueError: If project doesn't have GitHub repo
        """
        client = self._get_client()
        owner, repo = self._get_repo_info(item)
        
        # Prepare issue data
        issue_title = title or item.title
        issue_body = body
        
        if issue_body is None:
            # Build default body from item
            parts = []
            
            if item.description:
                parts.append(item.description)
            
            # Add metadata
            parts.append(f"\n---\n**Agira Item ID:** {item.id}")
            parts.append(f"**Project:** {item.project.name}")
            parts.append(f"**Type:** {item.type.name}")
            
            issue_body = '\n\n'.join(parts)
        
        # Create issue in GitHub without assignee
        # The item will be assigned locally in Agira to track that Copilot is working on it
        try:
            github_issue = client.create_issue(
                owner=owner,
                repo=repo,
                title=issue_title,
                body=issue_body,
                labels=labels,
            )
        except Exception as e:
            # If the API request fails completely, log and re-raise
            logger.error(
                f"Error creating GitHub issue for item {item.id} in {owner}/{repo}: {e}"
            )
            raise
        
        # Assign item locally to Copilot user in Agira
        try:
            copilot_user = User.objects.get(username='Copilot')
            
            # Use transaction and select_for_update to prevent race conditions
            with transaction.atomic():
                # Re-fetch the item with a lock to ensure consistency
                locked_item = Item.objects.select_for_update().get(pk=item.pk)
                locked_item.assigned_to = copilot_user
                locked_item.save()
            
            # Refresh the item object from database to get the updated assigned_to value
            # This ensures the returned item object reflects the database state
            item.refresh_from_db()
            
            logger.info(
                f"Assigned item {item.id} to Copilot user locally in Agira"
            )
        except User.DoesNotExist:
            logger.warning(
                f"Copilot user does not exist in Agira. Item {item.id} not assigned locally. "
                f"Please create a user with username 'Copilot' to enable local assignment tracking."
            )
        
        # Create mapping
        state = self._map_state(github_issue, 'issue')
        
        mapping = ExternalIssueMapping.objects.create(
            item=item,
            github_id=github_issue['id'],
            number=github_issue['number'],
            kind=ExternalIssueKind.ISSUE,
            state=state,
            html_url=github_issue['html_url'],
        )
        
        # Log activity
        self._log_activity(
            item=item,
            verb='github.issue_created',
            summary=f"Created GitHub issue #{github_issue['number']}: {issue_title}",
            actor=actor,
        )
        
        logger.info(
            f"Created GitHub issue #{github_issue['number']} for item {item.id}"
        )
        
        return mapping
    
    def sync_mapping(self, mapping: ExternalIssueMapping) -> ExternalIssueMapping:
        """
        Synchronize an ExternalIssueMapping with GitHub.
        
        Updates state, html_url, and last_synced_at from GitHub.
        
        Args:
            mapping: ExternalIssueMapping to sync
            
        Returns:
            Updated mapping
            
        Raises:
            IntegrationDisabled: If GitHub is disabled
            IntegrationNotConfigured: If GitHub is not configured
        """
        client = self._get_client()
        owner, repo = self._get_repo_info(mapping.item)
        
        # Fetch from GitHub
        if mapping.kind == ExternalIssueKind.ISSUE:
            github_data = client.get_issue(owner, repo, mapping.number)
        else:  # PR
            github_data = client.get_pr(owner, repo, mapping.number)
        
        # Update mapping
        old_state = mapping.state
        mapping.state = self._map_state(github_data, mapping.kind.lower())
        mapping.html_url = github_data['html_url']
        mapping.github_id = github_data['id']
        mapping.last_synced_at = timezone.now()
        mapping.save()
        
        # Log activity if state changed
        if old_state != mapping.state:
            kind_name = 'issue' if mapping.kind == ExternalIssueKind.ISSUE else 'PR'
            self._log_activity(
                item=mapping.item,
                verb=f'github.{mapping.kind.lower()}_state_changed',
                summary=f"GitHub {kind_name} #{mapping.number} changed from {old_state} to {mapping.state}",
            )
        
        logger.info(
            f"Synced mapping {mapping.id}: {mapping.kind} #{mapping.number} -> {mapping.state}"
        )
        
        return mapping
    
    def sync_item(self, item: Item) -> int:
        """
        Synchronize all ExternalIssueMappings for an item.
        
        Args:
            item: Agira item to sync
            
        Returns:
            Number of mappings updated
        """
        from core.services.integrations.base import IntegrationError
        
        mappings = item.external_mappings.all()
        count = 0
        
        for mapping in mappings:
            try:
                self.sync_mapping(mapping)
                count += 1
            except IntegrationError as e:
                # Log integration errors but continue with other mappings
                logger.error(
                    f"Failed to sync mapping {mapping.id}: {e}"
                )
            except Exception as e:
                # Catch unexpected errors to prevent partial failures
                logger.exception(
                    f"Unexpected error syncing mapping {mapping.id}: {e}"
                )
        
        return count
    
    def upsert_mapping_from_github(
        self,
        item: Item,
        *,
        number: int,
        kind: str,
    ) -> ExternalIssueMapping:
        """
        Create or update mapping from existing GitHub issue/PR.
        
        Useful when a GitHub issue/PR already exists and needs to be
        mapped to an Agira item.
        
        Args:
            item: Agira item to map to
            number: GitHub issue/PR number
            kind: 'issue' or 'pr'
            
        Returns:
            Created or updated ExternalIssueMapping
            
        Raises:
            IntegrationDisabled: If GitHub is disabled
            IntegrationNotConfigured: If GitHub is not configured
            ValueError: If project doesn't have GitHub repo or invalid kind
        """
        client = self._get_client()
        owner, repo = self._get_repo_info(item)
        
        # Validate kind
        if kind not in ['issue', 'pr']:
            raise ValueError(f"Invalid kind: {kind}. Must be 'issue' or 'pr'")
        
        # Fetch from GitHub
        if kind == 'issue':
            github_data = client.get_issue(owner, repo, number)
            mapping_kind = ExternalIssueKind.ISSUE
        else:
            github_data = client.get_pr(owner, repo, number)
            mapping_kind = ExternalIssueKind.PR
        
        github_id = github_data['id']
        state = self._map_state(github_data, kind)
        html_url = github_data['html_url']
        
        # Try to find existing mapping
        mapping = None
        
        # First, try by github_id (most reliable)
        try:
            mapping = ExternalIssueMapping.objects.get(github_id=github_id)
            # Update item if different
            if mapping.item != item:
                mapping.item = item
        except ExternalIssueMapping.DoesNotExist:
            pass
        
        # Second, try by (item, kind, number)
        if mapping is None:
            try:
                mapping = ExternalIssueMapping.objects.get(
                    item=item,
                    kind=mapping_kind,
                    number=number,
                )
            except ExternalIssueMapping.DoesNotExist:
                pass
        
        # Create or update
        if mapping is None:
            mapping = ExternalIssueMapping.objects.create(
                item=item,
                github_id=github_id,
                number=number,
                kind=mapping_kind,
                state=state,
                html_url=html_url,
            )
            action = 'created'
        else:
            mapping.state = state
            mapping.html_url = html_url
            mapping.github_id = github_id
            mapping.number = number
            mapping.kind = mapping_kind
            mapping.last_synced_at = timezone.now()
            mapping.save()
            action = 'updated'
        
        logger.info(
            f"{action.capitalize()} mapping for item {item.id}: "
            f"{kind} #{number} (GitHub ID {github_id})"
        )
        
        return mapping
    
    def import_closed_issues_for_project(
        self,
        project: Project,
        *,
        actor=None,
    ) -> dict:
        """
        Import all closed GitHub issues for a project.
        
        Creates Items with status Closed for each GitHub issue that doesn't
        already have a mapping, links related PRs, and indexes in Weaviate.
        
        Args:
            project: Project to import issues for
            actor: User performing the import (optional)
            
        Returns:
            Dictionary with import statistics:
                - issues_found: Total closed issues found
                - issues_imported: New issues imported
                - prs_linked: PRs linked to issues
                - errors: List of error messages
                
        Raises:
            IntegrationDisabled: If GitHub is disabled
            IntegrationNotConfigured: If GitHub is not configured
            ValueError: If project doesn't have GitHub repo configured
        """
        if not project.github_owner or not project.github_repo:
            raise ValueError(
                f"Project '{project.name}' does not have GitHub repository configured"
            )
        
        client = self._get_client()
        owner = project.github_owner
        repo = project.github_repo
        
        stats = {
            'issues_found': 0,
            'issues_imported': 0,
            'prs_linked': 0,
            'errors': [],
        }
        
        try:
            # Fetch all closed issues with pagination
            page = 1
            per_page = 100
            
            while True:
                issues = client.list_issues(
                    owner=owner,
                    repo=repo,
                    state='closed',
                    per_page=per_page,
                    page=page,
                )
                
                if not issues:
                    break
                
                for github_issue in issues:
                    # Skip pull requests (they have 'pull_request' key)
                    if 'pull_request' in github_issue:
                        continue
                    
                    stats['issues_found'] += 1
                    
                    try:
                        # Check if mapping already exists
                        github_id = github_issue['id']
                        number = github_issue['number']
                        
                        existing_mapping = ExternalIssueMapping.objects.filter(
                            github_id=github_id
                        ).first()
                        
                        if existing_mapping:
                            # Issue already imported, just link PRs
                            logger.info(
                                f"Issue #{number} already exists for item {existing_mapping.item.id}"
                            )
                            # Link PRs for this issue
                            prs_linked = self._link_prs_to_issue(
                                existing_mapping,
                                client,
                                owner,
                                repo,
                            )
                            stats['prs_linked'] += prs_linked
                            continue
                        
                        # Create new item for this issue
                        item = self._create_item_from_github_issue(
                            project=project,
                            github_issue=github_issue,
                            actor=actor,
                        )
                        
                        # Create mapping
                        state = self._map_state(github_issue, 'issue')
                        mapping = ExternalIssueMapping.objects.create(
                            item=item,
                            github_id=github_id,
                            number=number,
                            kind=ExternalIssueKind.ISSUE,
                            state=state,
                            html_url=github_issue['html_url'],
                        )
                        
                        stats['issues_imported'] += 1
                        
                        # Log activity
                        self._log_activity(
                            item=item,
                            verb='github.issue_imported',
                            summary=f"Imported closed GitHub issue #{number}",
                            actor=actor,
                        )
                        
                        logger.info(
                            f"Imported closed issue #{number} as item {item.id}"
                        )
                        
                        # Link PRs for this issue
                        prs_linked = self._link_prs_to_issue(
                            mapping,
                            client,
                            owner,
                            repo,
                        )
                        stats['prs_linked'] += prs_linked
                        
                        # Index in Weaviate
                        try:
                            from core.services.weaviate.service import upsert_instance
                            from core.services.weaviate import is_available
                            
                            if is_available():
                                upsert_instance(item)
                                upsert_instance(mapping)
                        except Exception as e:
                            logger.warning(
                                f"Failed to index item {item.id} in Weaviate: {e}"
                            )
                    
                    except Exception as e:
                        error_msg = f"Error importing issue #{github_issue.get('number', 'unknown')}: {str(e)}"
                        stats['errors'].append(error_msg)
                        logger.error(error_msg, exc_info=True)
                
                # Check if there are more pages
                if len(issues) < per_page:
                    break
                
                page += 1
        
        except Exception as e:
            error_msg = f"Error fetching issues from GitHub: {str(e)}"
            stats['errors'].append(error_msg)
            logger.error(error_msg, exc_info=True)
        
        return stats
    
    def _create_item_from_github_issue(
        self,
        project: Project,
        github_issue: dict,
        actor=None,
    ) -> Item:
        """
        Create an Agira Item from a GitHub issue.
        
        Args:
            project: Project to create item in
            github_issue: GitHub issue data
            actor: User creating the item (optional)
            
        Returns:
            Created Item
        """
        # Extract data from GitHub issue
        title = github_issue.get('title', 'Untitled Issue')
        body = github_issue.get('body', '')
        
        # Build description with metadata
        description_parts = []
        
        if body:
            description_parts.append(body)
        
        # Add GitHub metadata
        description_parts.append(f"\n---\n**GitHub Issue:** #{github_issue.get('number')}")
        description_parts.append(f"**Repository:** {project.github_owner}/{project.github_repo}")
        description_parts.append(f"**URL:** {github_issue.get('html_url')}")
        
        description = '\n\n'.join(description_parts)
        
        # Get default item type
        # Try to find appropriate type based on common naming conventions
        from core.models import ItemType
        
        # Try different common item type names in order of preference
        type_preferences = ['Feature', 'Bug', 'Task', 'Story']
        item_type = None
        
        for type_name in type_preferences:
            item_type = ItemType.objects.filter(is_active=True, name=type_name).first()
            if item_type:
                break
        
        # If none of the preferred types exist, use any active type
        if not item_type:
            item_type = ItemType.objects.filter(is_active=True).first()
        
        if not item_type:
            raise ValueError("No active ItemType found. Please create one first.")
        
        # Create the item
        item = Item.objects.create(
            project=project,
            title=title,
            description=description,
            type=item_type,
            status=ItemStatus.CLOSED,
            assigned_to=actor if actor else None,
        )
        
        return item
    
    def _link_prs_to_issue(
        self,
        mapping: ExternalIssueMapping,
        client: GitHubClient,
        owner: str,
        repo: str,
    ) -> int:
        """
        Link PRs to an issue via timeline events.
        
        Args:
            mapping: Issue mapping
            client: GitHub client
            owner: Repository owner
            repo: Repository name
            
        Returns:
            Number of PRs linked
        """
        try:
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
            
            # Create mappings for each found PR
            linked_count = 0
            for pr_number in pr_numbers:
                try:
                    # Check if PR mapping already exists
                    existing = ExternalIssueMapping.objects.filter(
                        item=mapping.item,
                        number=pr_number,
                        kind=ExternalIssueKind.PR,
                    ).first()
                    
                    if existing:
                        continue
                    
                    # Use upsert_mapping_from_github to create/update PR mapping
                    self.upsert_mapping_from_github(
                        item=mapping.item,
                        number=pr_number,
                        kind='pr',
                    )
                    linked_count += 1
                    
                    logger.info(f"Linked PR #{pr_number} to item {mapping.item.id}")
                
                except Exception as e:
                    logger.warning(f"Failed to link PR #{pr_number}: {e}")
            
            return linked_count
        
        except Exception as e:
            logger.warning(f"Failed to fetch timeline for issue #{mapping.number}: {e}")
            return 0
