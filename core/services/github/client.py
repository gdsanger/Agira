"""
GitHub API Client

Low-level client for interacting with the GitHub REST API v3.
"""

import base64
import logging
from typing import Optional, Dict, Any, List, Union

from core.services.integrations.http import HTTPClient
from core.services.integrations.base import IntegrationError

logger = logging.getLogger(__name__)


class GitHubClient:
    """
    GitHub REST API v3 client.
    
    Handles authentication and API requests to GitHub.
    """
    
    def __init__(self, token: str, base_url: str = 'https://api.github.com'):
        """
        Initialize GitHub client.
        
        Args:
            token: GitHub Personal Access Token or App token
            base_url: GitHub API base URL (default: https://api.github.com)
        """
        headers = {
            'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        }
        
        self.http = HTTPClient(
            base_url=base_url,
            headers=headers,
            timeout=30.0,
            max_retries=3,
        )
    
    # Issue methods
    
    def get_issue(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        """
        Get a single issue.
        
        Args:
            owner: Repository owner
            repo: Repository name
            number: Issue number
            
        Returns:
            Issue data as dictionary
        """
        path = f'/repos/{owner}/{repo}/issues/{number}'
        return self.http.get(path)
    
    def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: Optional[str] = None,
        labels: Optional[List[str]] = None,
        assignees: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a new issue.
        
        Args:
            owner: Repository owner
            repo: Repository name
            title: Issue title
            body: Issue body (markdown)
            labels: List of label names
            assignees: List of usernames to assign to the issue
            
        Returns:
            Created issue data as dictionary
        """
        path = f'/repos/{owner}/{repo}/issues'
        payload = {
            'title': title,
        }
        
        if body:
            payload['body'] = body
        
        if labels:
            payload['labels'] = labels
        
        if assignees:
            payload['assignees'] = assignees
        
        return self.http.post(path, json=payload)
    
    def close_issue(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        """
        Close an issue.
        
        Args:
            owner: Repository owner
            repo: Repository name
            number: Issue number
            
        Returns:
            Updated issue data as dictionary
        """
        path = f'/repos/{owner}/{repo}/issues/{number}'
        payload = {'state': 'closed'}
        return self.http.patch(path, json=payload)
    
    def list_issues(
        self,
        owner: str,
        repo: str,
        state: str = 'all',
        since: Optional[str] = None,
        per_page: int = 30,
        page: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        List issues in a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            state: Filter by state ('open', 'closed', 'all')
            since: Only issues updated after this time (ISO 8601 timestamp)
            per_page: Results per page (max 100)
            page: Page number
            
        Returns:
            List of issue dictionaries
        """
        path = f'/repos/{owner}/{repo}/issues'
        params = {
            'state': state,
            'per_page': min(per_page, 100),
            'page': page,
        }
        
        if since:
            params['since'] = since
        
        return self.http.get(path, params=params)
    
    # Pull Request methods
    
    def get_pr(self, owner: str, repo: str, number: int) -> Dict[str, Any]:
        """
        Get a single pull request.
        
        Args:
            owner: Repository owner
            repo: Repository name
            number: PR number
            
        Returns:
            PR data as dictionary
        """
        path = f'/repos/{owner}/{repo}/pulls/{number}'
        return self.http.get(path)
    
    def list_prs(
        self,
        owner: str,
        repo: str,
        state: str = 'all',
        since: Optional[str] = None,
        per_page: int = 30,
        page: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        List pull requests in a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            state: Filter by state ('open', 'closed', 'all')
            since: Only PRs updated after this time (ISO 8601 timestamp)
            per_page: Results per page (max 100)
            page: Page number
            
        Returns:
            List of PR dictionaries
        """
        path = f'/repos/{owner}/{repo}/pulls'
        params = {
            'state': state,
            'per_page': min(per_page, 100),
            'page': page,
        }
        
        # Note: GitHub API for PRs doesn't support 'since' parameter directly
        # We would need to filter client-side if needed
        
        return self.http.get(path, params=params)
    
    # Timeline/Events methods
    
    def get_issue_timeline(
        self,
        owner: str,
        repo: str,
        number: int,
        per_page: int = 100,
        page: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Get timeline events for an issue.
        
        This includes references to PRs, commits, and other events.
        
        Args:
            owner: Repository owner
            repo: Repository name
            number: Issue number
            per_page: Results per page (max 100)
            page: Page number
            
        Returns:
            List of timeline event dictionaries
        """
        path = f'/repos/{owner}/{repo}/issues/{number}/timeline'
        params = {
            'per_page': min(per_page, 100),
            'page': page,
        }
        
        # Need to use preview API for timeline
        headers = {
            'Accept': 'application/vnd.github.mockingbird-preview+json',
        }
        
        return self.http.get(path, params=params, headers=headers)
    
    # Repository content methods
    
    def get_repository_contents(
        self,
        owner: str,
        repo: str,
        path: str = '',
        ref: Optional[str] = None,
    ) -> Union[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Get contents of a file or directory in a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            path: Path to file or directory (empty string for root)
            ref: Git reference (branch, tag, or commit SHA). Defaults to default branch.
            
        Returns:
            File metadata dict (if path is a file) or list of content dicts (if directory)
        """
        api_path = f'/repos/{owner}/{repo}/contents/{path}'
        params = {}
        
        if ref:
            params['ref'] = ref
        
        return self.http.get(api_path, params=params)
    
    def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: Optional[str] = None,
    ) -> bytes:
        """
        Get raw file content from a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            path: Path to file
            ref: Git reference (branch, tag, or commit SHA)
            
        Returns:
            Raw file content as bytes
        """
        # Get file metadata which includes base64-encoded content
        file_data = self.get_repository_contents(owner, repo, path, ref)
        
        # If it's a file, it will have 'content' field (base64-encoded)
        if isinstance(file_data, dict) and 'content' in file_data:
            # Decode base64 content
            content_b64 = file_data['content'].replace('\n', '')
            return base64.b64decode(content_b64)
        else:
            raise IntegrationError(f"Path {path} is not a file or content not available")
