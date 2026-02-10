#!/usr/bin/env python
"""
Create additional test data for Kanban view testing.
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agira.settings')
os.environ['DB_ENGINE'] = 'django.db.backends.sqlite3'
django.setup()

from django.contrib.auth import get_user_model
from core.models import (
    Organisation, Project, ItemType, Item, ItemStatus, 
    Release, ExternalIssueMapping, ExternalIssueKind, UserOrganisation
)

User = get_user_model()

def create_kanban_test_data():
    """Create test data for Kanban board demonstration."""
    
    # Get existing user and org
    user = User.objects.get(username='testuser')
    org = Organisation.objects.first()
    project = Project.objects.first()
    item_type = ItemType.objects.first()
    release = Release.objects.first()
    
    # Create a second release
    release2, _ = Release.objects.get_or_create(
        project=project,
        version='2.0.0',
        defaults={
            'name': '2.0.0',
            'planned_date': '2025-03-31'
        }
    )
    
    # Create items in different statuses
    statuses_to_create = [
        (ItemStatus.INBOX, 'New feature request from customer', None),
        (ItemStatus.INBOX, 'Bug in login form', 'https://github.com/test/repo/issues/100'),
        (ItemStatus.BACKLOG, 'Implement user dashboard', None),
        (ItemStatus.BACKLOG, 'Add email notifications', None),
        (ItemStatus.PLANING, 'Design new reporting module', None),
        (ItemStatus.SPECIFICATION, 'API documentation update', None),
        (ItemStatus.WORKING, 'Fix database connection issue', 'https://github.com/test/repo/issues/101'),
        (ItemStatus.WORKING, 'Implement search functionality', None),
        (ItemStatus.WORKING, 'Update user profile page', None),
        (ItemStatus.TESTING, 'New authentication flow', None),
        (ItemStatus.TESTING, 'Export to PDF feature', None),
        (ItemStatus.READY_FOR_RELEASE, 'Performance improvements', None),
        (ItemStatus.READY_FOR_RELEASE, 'Security updates', 'https://github.com/test/repo/issues/102'),
        (ItemStatus.CLOSED, 'Old feature request', None),  # Should not appear in Kanban
    ]
    
    items_created = 0
    for idx, (status, title, github_url) in enumerate(statuses_to_create, start=2):
        # Alternate between releases
        item_release = release if idx % 2 == 0 else release2
        
        # Don't set release for closed items
        if status == ItemStatus.CLOSED:
            item_release = None
        
        item, created = Item.objects.get_or_create(
            project=project,
            title=title,
            defaults={
                'description': f'This is a test item for {status.label} status.',
                'type': item_type,
                'status': status,
                'organisation': org,
                'requester': user,
                'assigned_to': user if status in [ItemStatus.WORKING, ItemStatus.TESTING] else None,
                'solution_release': item_release,
            }
        )
        
        if created:
            items_created += 1
            print(f"✓ Created item: {title} ({status.label})")
            
            # Add GitHub mapping if URL provided
            if github_url and created:
                issue_number = int(github_url.split('/')[-1])
                ExternalIssueMapping.objects.create(
                    item=item,
                    github_id=10000 + issue_number,
                    number=issue_number,
                    kind=ExternalIssueKind.ISSUE,
                    state='open',
                    html_url=github_url
                )
                print(f"  ✓ Added GitHub mapping: Issue #{issue_number}")
    
    print(f"\n✅ Created {items_created} additional items for Kanban board!")
    print(f"Access the Kanban board at: /items/kanban/")

if __name__ == '__main__':
    create_kanban_test_data()
