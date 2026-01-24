#!/usr/bin/env python
"""
Create test data for Item Detail page testing.
"""
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agira.settings')
os.environ['DB_ENGINE'] = 'django.db.backends.sqlite3'
django.setup()

from django.contrib.auth import get_user_model
from core.models import (
    Organisation, Project, ItemType, Item, ItemComment, 
    ItemStatus, Release, ExternalIssueMapping, ExternalIssueKind
)
from core.services.activity import ActivityService

User = get_user_model()

def create_test_data():
    """Create test data for demonstration."""
    
    # Create user
    user, created = User.objects.get_or_create(
        username='testuser',
        defaults={
            'email': 'test@example.com',
            'name': 'Test User',
            'role': 'Agent',
        }
    )
    if created:
        user.set_password('testpass')
        user.save()
        print(f"✓ Created user: {user.username}")
    else:
        print(f"✓ User exists: {user.username}")
    
    # Create organisation
    org, created = Organisation.objects.get_or_create(
        name='Test Organisation'
    )
    if created:
        print(f"✓ Created organisation: {org.name}")
    else:
        print(f"✓ Organisation exists: {org.name}")
    
    # Link user to organisation
    from core.models import UserOrganisation
    user_org, created = UserOrganisation.objects.get_or_create(
        user=user,
        organisation=org,
        defaults={'is_primary': True}
    )
    if created:
        print(f"✓ Linked user to organisation")
    else:
        print(f"✓ User already linked to organisation")
    
    # Create project
    project, created = Project.objects.get_or_create(
        name='Test Project',
        defaults={
            'description': 'A test project for development',
            'github_owner': 'testowner',
            'github_repo': 'testrepo',
        }
    )
    if created:
        project.clients.add(org)
        print(f"✓ Created project: {project.name}")
    else:
        print(f"✓ Project exists: {project.name}")
    
    # Create item type
    item_type, created = ItemType.objects.get_or_create(
        key='bug',
        defaults={
            'name': 'Bug',
            'is_active': True,
        }
    )
    if created:
        print(f"✓ Created item type: {item_type.name}")
    else:
        print(f"✓ Item type exists: {item_type.name}")
    
    # Create release
    release, created = Release.objects.get_or_create(
        project=project,
        name='Release 1.0',
        defaults={
            'version': '1.0.0',
            'status': 'Planned',
        }
    )
    if created:
        print(f"✓ Created release: {release.version}")
    else:
        print(f"✓ Release exists: {release.version}")
    
    # Create test item
    item, created = Item.objects.get_or_create(
        project=project,
        title='Test Bug Item',
        defaults={
            'description': 'This is a test bug for demonstrating the item detail page.\n\nIt has multiple lines of description text.',
            'solution_description': 'This is the proposed solution for fixing the bug.',
            'type': item_type,
            'organisation': org,
            'requester': user,
            'assigned_to': user,
            'status': ItemStatus.WORKING,
            'solution_release': release,
        }
    )
    if created:
        print(f"✓ Created item: {item.title} (ID: {item.id})")
        
        # Log creation activity
        activity_service = ActivityService()
        activity_service.log_created(
            target=item,
            actor=user,
        )
    else:
        print(f"✓ Item exists: {item.title} (ID: {item.id})")
    
    # Create comments
    comment1, created = ItemComment.objects.get_or_create(
        item=item,
        author=user,
        body='This is the first comment on this item.',
        defaults={
            'visibility': 'Public',
            'kind': 'Comment',
        }
    )
    if created:
        print(f"✓ Created comment 1")
        activity_service = ActivityService()
        activity_service.log(
            verb='comment.added',
            target=item,
            actor=user,
            summary='Added comment',
        )
    
    comment2, created = ItemComment.objects.get_or_create(
        item=item,
        author=user,
        body='This is a second comment with more details about the issue.',
        defaults={
            'visibility': 'Internal',
            'kind': 'Note',
        }
    )
    if created:
        print(f"✓ Created comment 2")
        activity_service = ActivityService()
        activity_service.log(
            verb='comment.added',
            target=item,
            actor=user,
            summary='Added internal note',
        )
    
    # Create GitHub mapping
    mapping, created = ExternalIssueMapping.objects.get_or_create(
        item=item,
        github_id=123456789,
        defaults={
            'number': 42,
            'kind': ExternalIssueKind.ISSUE,
            'state': 'open',
            'html_url': 'https://github.com/testowner/testrepo/issues/42',
        }
    )
    if created:
        print(f"✓ Created GitHub mapping: Issue #{mapping.number}")
    else:
        print(f"✓ GitHub mapping exists: Issue #{mapping.number}")
    
    print(f"\n✅ Test data created successfully!")
    print(f"\nAccess the item detail page at: /items/{item.id}/")
    return item

if __name__ == '__main__':
    item = create_test_data()
