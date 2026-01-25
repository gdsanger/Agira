"""
GitHub Service

Main service for GitHub integration with Agira Items.
"""

import logging
from typing import Optional
from django.utils import timezone

from core.models import (
    GitHubConfiguration,
    Project,
    Item,
    ExternalIssueMapping,
    ExternalIssueKind,
    Activity,
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
            item: Agira item to check
            
        Returns:
            True if issue can be created, False otherwise
        """
        from core.models import ItemStatus
        
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
        
        # Create issue in GitHub
        github_issue = client.create_issue(
            owner=owner,
            repo=repo,
            title=issue_title,
            body=issue_body,
            labels=labels,
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
