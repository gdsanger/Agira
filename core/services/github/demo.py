#!/usr/bin/env python
"""
GitHub Service Demo

Demonstrates usage of the GitHub service for Agira.
This is a reference implementation showing how to use the service.
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agira.settings')
django.setup()

from core.services.github import GitHubService
from core.models import Item, GitHubConfiguration


def demo_configuration():
    """Demonstrate configuration checking."""
    print("=== GitHub Service Configuration ===\n")
    
    github = GitHubService()
    
    print(f"✓ Service enabled: {github.is_enabled()}")
    print(f"✓ Service configured: {github.is_configured()}")
    
    config = GitHubConfiguration.load()
    print(f"✓ API Base URL: {config.github_api_base_url}")
    print(f"✓ Default Owner: {config.default_github_owner or '(not set)'}")
    print()


def demo_create_issue():
    """Demonstrate creating a GitHub issue from an Agira item."""
    print("=== Create GitHub Issue ===\n")
    
    # This would create a real issue if configured
    print("Example code to create an issue:\n")
    print("""
    from core.services.github import GitHubService
    from core.models import Item
    
    github = GitHubService()
    item = Item.objects.get(id=123)
    
    # Create issue with default title/body
    mapping = github.create_issue_for_item(
        item=item,
        labels=['bug', 'priority:high'],
        actor=request.user,
    )
    
    print(f"Created: {mapping.html_url}")
    print(f"Issue number: #{mapping.number}")
    print(f"State: {mapping.state}")
    """)


def demo_sync():
    """Demonstrate syncing mappings."""
    print("=== Sync GitHub Mappings ===\n")
    
    print("Example code to sync a mapping:\n")
    print("""
    from core.services.github import GitHubService
    from core.models import ExternalIssueMapping
    
    github = GitHubService()
    
    # Sync single mapping
    mapping = ExternalIssueMapping.objects.get(id=1)
    updated = github.sync_mapping(mapping)
    print(f"State: {updated.state}")
    print(f"Last synced: {updated.last_synced_at}")
    
    # Sync all mappings for an item
    item = mapping.item
    count = github.sync_item(item)
    print(f"Synced {count} mappings")
    """)


def demo_upsert():
    """Demonstrate mapping existing GitHub issues."""
    print("=== Map Existing GitHub Issues/PRs ===\n")
    
    print("Example code to map existing GitHub issue:\n")
    print("""
    from core.services.github import GitHubService
    from core.models import Item
    
    github = GitHubService()
    item = Item.objects.get(id=123)
    
    # Map existing GitHub issue #42
    mapping = github.upsert_mapping_from_github(
        item=item,
        number=42,
        kind='issue',
    )
    print(f"Mapped issue #{mapping.number}")
    
    # Map existing GitHub PR #15
    pr_mapping = github.upsert_mapping_from_github(
        item=item,
        number=15,
        kind='pr',
    )
    print(f"Mapped PR #{pr_mapping.number}")
    print(f"State: {pr_mapping.state}")  # Could be 'merged'
    """)


def demo_error_handling():
    """Demonstrate error handling."""
    print("=== Error Handling ===\n")
    
    print("Example code for error handling:\n")
    print("""
    from core.services.github import GitHubService
    from core.services.integrations.base import (
        IntegrationDisabled,
        IntegrationNotConfigured,
        IntegrationAuthError,
        IntegrationRateLimitError,
    )
    
    github = GitHubService()
    
    try:
        mapping = github.create_issue_for_item(item)
    except IntegrationDisabled:
        print("GitHub is disabled in configuration")
    except IntegrationNotConfigured:
        print("GitHub token not configured")
    except IntegrationAuthError:
        print("GitHub authentication failed - check token")
    except IntegrationRateLimitError as e:
        print(f"Rate limit exceeded. Retry after {e.retry_after}s")
    except ValueError as e:
        print(f"Configuration error: {e}")
    """)


def main():
    """Run all demos."""
    print("\n" + "="*60)
    print("GitHub Service Demo for Agira")
    print("="*60 + "\n")
    
    try:
        demo_configuration()
        demo_create_issue()
        demo_sync()
        demo_upsert()
        demo_error_handling()
        
        print("="*60)
        print("\nFor complete documentation, see docs/services/github.md")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\n❌ Error running demo: {e}")
        print("\nNote: This demo requires Django to be configured.")
        print("See docs/services/github.md for usage examples.\n")


if __name__ == '__main__':
    main()
