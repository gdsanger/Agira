#!/usr/bin/env python3
"""
Example usage of the Attachment Storage Service.

This script demonstrates how to use the service to store, retrieve,
link, and delete attachments.
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agira.settings')
django.setup()

from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
from core.models import Project, Item, ItemComment, ItemType, ProjectStatus, ItemStatus, CommentKind, User
from core.services.storage import AttachmentStorageService


def demo_attachment_storage():
    """Demonstrate the attachment storage service."""
    
    print("=" * 60)
    print("Attachment Storage Service Demo")
    print("=" * 60)
    
    # Initialize service
    service = AttachmentStorageService()
    print(f"\n1. Service initialized with:")
    print(f"   - Data directory: {service.data_dir}")
    print(f"   - Max size: {service.max_size_bytes / (1024*1024):.1f} MB")
    
    # Get or create test user
    user, _ = User.objects.get_or_create(
        username='demo_user',
        defaults={
            'email': 'demo@example.com',
            'name': 'Demo User'
        }
    )
    if not user.password:
        user.set_password('demo123')
        user.save()
    
    # Get or create test project
    project, _ = Project.objects.get_or_create(
        name='Demo Project',
        defaults={'status': ProjectStatus.NEW}
    )
    
    print(f"\n2. Using project: {project.name} (ID: {project.id})")
    
    # Create a test file
    file_content = b'This is a demo file for testing the storage service.\nIt contains multiple lines.\n'
    test_file = SimpleUploadedFile(
        'demo_document.txt',
        file_content,
        content_type='text/plain'
    )
    
    print(f"\n3. Storing attachment to project...")
    attachment = service.store_attachment(
        file=test_file,
        target=project,
        created_by=user,
        compute_hash=True
    )
    
    print(f"   ✓ Attachment created:")
    print(f"     - ID: {attachment.id}")
    print(f"     - Name: {attachment.original_name}")
    print(f"     - Size: {attachment.size_bytes} bytes")
    print(f"     - SHA256: {attachment.sha256[:16]}...")
    print(f"     - Path: {attachment.storage_path}")
    
    # Get file path
    file_path = service.get_file_path(attachment)
    print(f"\n4. File stored at: {file_path}")
    print(f"   File exists: {file_path.exists()}")
    
    # Read content back
    with open(file_path, 'rb') as f:
        stored_content = f.read()
    
    print(f"\n5. Content verification:")
    print(f"   Original size: {len(file_content)} bytes")
    print(f"   Stored size: {len(stored_content)} bytes")
    print(f"   Content matches: {file_content == stored_content}")
    
    # Create an item and link the same attachment
    item_type, _ = ItemType.objects.get_or_create(
        key='demo',
        defaults={'name': 'Demo Type'}
    )
    
    item, _ = Item.objects.get_or_create(
        project=project,
        title='Demo Item',
        defaults={
            'type': item_type,
            'status': ItemStatus.INBOX
        }
    )
    
    print(f"\n6. Linking attachment to item: {item.title}")
    link = service.link_attachment(attachment, item)
    print(f"   ✓ Link created:")
    print(f"     - Link ID: {link.id}")
    print(f"     - Role: {link.role}")
    print(f"     - Target: {link.target}")
    
    # Show all links for this attachment
    all_links = attachment.links.all()
    print(f"\n7. All links for this attachment ({all_links.count()}):")
    for idx, link in enumerate(all_links, 1):
        print(f"   {idx}. {link.target} ({link.role})")
    
    # Demonstrate soft delete
    print(f"\n8. Soft delete demonstration:")
    print(f"   Before: is_deleted={attachment.is_deleted}")
    service.delete_attachment(attachment, hard=False)
    attachment.refresh_from_db()
    print(f"   After soft delete: is_deleted={attachment.is_deleted}")
    print(f"   File still exists: {file_path.exists()}")
    
    # Clean up
    print(f"\n9. Cleanup (hard delete)...")
    service.delete_attachment(attachment, hard=True)
    print(f"   ✓ Attachment deleted")
    print(f"   File removed: {not file_path.exists()}")
    
    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print("=" * 60)


if __name__ == '__main__':
    demo_attachment_storage()
