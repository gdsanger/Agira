"""
Tests for Attachment Storage Service
"""

import os
import tempfile
from pathlib import Path
from io import BytesIO
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import (
    Project, Item, ItemComment, ItemType, Attachment, AttachmentLink,
    ProjectStatus, ItemStatus, CommentKind, AttachmentRole
)
from core.services.storage import (
    AttachmentStorageService,
    StorageError,
    AttachmentTooLarge,
    AttachmentNotFound,
    AttachmentWriteError,
)
from core.services.storage.paths import sanitize_filename, build_attachment_path

User = get_user_model()


class SanitizeFilenameTestCase(TestCase):
    """Test filename sanitization."""
    
    def test_basic_sanitization(self):
        """Test basic filename sanitization."""
        self.assertEqual(sanitize_filename('test.txt'), 'test.txt')
        self.assertEqual(sanitize_filename('Test File.pdf'), 'Test_File.pdf')
        self.assertEqual(sanitize_filename('file@#$%.doc'), 'file.doc')
    
    def test_directory_traversal_prevention(self):
        """Test that directory traversal attempts are prevented."""
        self.assertEqual(sanitize_filename('../../../etc/passwd'), 'passwd')
        self.assertEqual(sanitize_filename('../../file.txt'), 'file.txt')
    
    def test_multiple_extensions(self):
        """Test files with multiple extensions."""
        self.assertEqual(sanitize_filename('archive.tar.gz'), 'archive_tar.gz')
    
    def test_no_extension(self):
        """Test files without extensions."""
        self.assertEqual(sanitize_filename('README'), 'README')
    
    def test_empty_name(self):
        """Test that empty names get a default."""
        self.assertEqual(sanitize_filename(''), 'file')
        self.assertEqual(sanitize_filename('...'), 'file.')
    
    def test_long_filename(self):
        """Test that long filenames are truncated."""
        long_name = 'a' * 200 + '.txt'
        result = sanitize_filename(long_name)
        self.assertLessEqual(len(result), 105)  # 100 + ".txt"
        self.assertTrue(result.endswith('.txt'))


class BuildAttachmentPathTestCase(TestCase):
    """Test attachment path building."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        self.project = Project.objects.create(
            name='Test Project',
            status=ProjectStatus.NEW,
        )
        
        self.item_type = ItemType.objects.create(
            key='task',
            name='Task'
        )
        
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
        
        self.comment = ItemComment.objects.create(
            item=self.item,
            author=self.user,
            body='Test comment',
            kind=CommentKind.COMMENT,
        )
    
    def test_project_attachment_path(self):
        """Test path generation for project attachments."""
        path = build_attachment_path(self.project, 123, 'document.pdf')
        expected = os.path.join('projects', str(self.project.id), 'project', '123__document.pdf')
        self.assertEqual(path, expected)
    
    def test_item_attachment_path(self):
        """Test path generation for item attachments."""
        path = build_attachment_path(self.item, 456, 'screenshot.png')
        expected = os.path.join(
            'projects', str(self.project.id),
            'items', str(self.item.id),
            'item', '456__screenshot.png'
        )
        self.assertEqual(path, expected)
    
    def test_comment_attachment_path(self):
        """Test path generation for comment attachments."""
        path = build_attachment_path(self.comment, 789, 'log.txt')
        expected = os.path.join(
            'projects', str(self.project.id),
            'items', str(self.item.id),
            'comments', str(self.comment.id),
            'comment', '789__log.txt'
        )
        self.assertEqual(path, expected)


class AttachmentStorageServiceTestCase(TestCase):
    """Test AttachmentStorageService."""
    
    def setUp(self):
        """Set up test data and temporary storage."""
        # Create temporary directory for test storage
        self.temp_dir = tempfile.mkdtemp()
        self.service = AttachmentStorageService(data_dir=self.temp_dir, max_size_mb=1)
        
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123',
            name='Test User'
        )
        
        # Create test project
        self.project = Project.objects.create(
            name='Test Project',
            status=ProjectStatus.NEW,
        )
        
        # Create item type
        self.item_type = ItemType.objects.create(
            key='task',
            name='Task'
        )
        
        # Create test item
        self.item = Item.objects.create(
            project=self.project,
            title='Test Item',
            type=self.item_type,
            status=ItemStatus.INBOX,
        )
        
        # Create test comment
        self.comment = ItemComment.objects.create(
            item=self.item,
            author=self.user,
            body='Test comment',
            kind=CommentKind.COMMENT,
        )
    
    def tearDown(self):
        """Clean up temporary storage."""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)
    
    def test_store_attachment_to_project(self):
        """Test storing an attachment to a project."""
        file_content = b'Test file content'
        file = SimpleUploadedFile('test.txt', file_content, content_type='text/plain')
        
        attachment = self.service.store_attachment(
            file=file,
            target=self.project,
            created_by=self.user,
        )
        
        # Verify attachment record
        self.assertEqual(attachment.original_name, 'test.txt')
        self.assertEqual(attachment.content_type, 'text/plain')
        self.assertEqual(attachment.size_bytes, len(file_content))
        self.assertEqual(attachment.created_by, self.user)
        self.assertFalse(attachment.is_deleted)
        self.assertTrue(attachment.sha256)  # Hash should be computed
        self.assertTrue(attachment.storage_path)
        
        # Verify file was written
        file_path = self.service.get_file_path(attachment)
        self.assertTrue(file_path.exists())
        with open(file_path, 'rb') as f:
            self.assertEqual(f.read(), file_content)
        
        # Verify link was created
        link = AttachmentLink.objects.get(attachment=attachment)
        self.assertEqual(link.target, self.project)
        self.assertEqual(link.role, AttachmentRole.PROJECT_FILE)
    
    def test_store_attachment_to_item(self):
        """Test storing an attachment to an item."""
        file_content = b'Item attachment'
        file = SimpleUploadedFile('item.pdf', file_content, content_type='application/pdf')
        
        attachment = self.service.store_attachment(
            file=file,
            target=self.item,
            created_by=self.user,
        )
        
        link = AttachmentLink.objects.get(attachment=attachment)
        self.assertEqual(link.target, self.item)
        self.assertEqual(link.role, AttachmentRole.ITEM_FILE)
    
    def test_store_attachment_to_comment(self):
        """Test storing an attachment to a comment."""
        file_content = b'Comment attachment'
        file = SimpleUploadedFile('comment.jpg', file_content, content_type='image/jpeg')
        
        attachment = self.service.store_attachment(
            file=file,
            target=self.comment,
            created_by=self.user,
        )
        
        link = AttachmentLink.objects.get(attachment=attachment)
        self.assertEqual(link.target, self.comment)
        self.assertEqual(link.role, AttachmentRole.COMMENT_ATTACHMENT)
    
    def test_attachment_too_large(self):
        """Test that oversized files are rejected."""
        # Create a file larger than 1MB (our test limit)
        large_content = b'x' * (2 * 1024 * 1024)  # 2MB
        file = SimpleUploadedFile('large.bin', large_content)
        
        with self.assertRaises(AttachmentTooLarge):
            self.service.store_attachment(
                file=file,
                target=self.project,
                created_by=self.user,
            )
        
        # Verify no attachment was created
        self.assertEqual(Attachment.objects.count(), 0)
    
    def test_compute_hash_optional(self):
        """Test that hash computation can be disabled."""
        file_content = b'No hash'
        file = SimpleUploadedFile('nohash.txt', file_content)
        
        attachment = self.service.store_attachment(
            file=file,
            target=self.project,
            created_by=self.user,
            compute_hash=False,
        )
        
        self.assertEqual(attachment.sha256, '')
    
    def test_link_attachment(self):
        """Test linking an existing attachment to a new target."""
        file_content = b'Shared file'
        file = SimpleUploadedFile('shared.txt', file_content)
        
        # Create attachment on project
        attachment = self.service.store_attachment(
            file=file,
            target=self.project,
            created_by=self.user,
        )
        
        # Link same attachment to item
        link = self.service.link_attachment(
            attachment=attachment,
            target=self.item,
        )
        
        self.assertEqual(link.attachment, attachment)
        self.assertEqual(link.target, self.item)
        self.assertEqual(link.role, AttachmentRole.ITEM_FILE)
        
        # Verify both links exist
        self.assertEqual(AttachmentLink.objects.filter(attachment=attachment).count(), 2)
    
    def test_get_file_path(self):
        """Test getting absolute file path."""
        file_content = b'Path test'
        file = SimpleUploadedFile('pathtest.txt', file_content)
        
        attachment = self.service.store_attachment(
            file=file,
            target=self.project,
            created_by=self.user,
        )
        
        path = self.service.get_file_path(attachment)
        self.assertIsInstance(path, Path)
        self.assertTrue(path.is_absolute())
        self.assertTrue(path.exists())
        self.assertTrue(str(path).startswith(self.temp_dir))
    
    def test_get_file_path_not_found(self):
        """Test that missing files raise AttachmentNotFound."""
        file_content = b'Delete me'
        file = SimpleUploadedFile('delete.txt', file_content)
        
        attachment = self.service.store_attachment(
            file=file,
            target=self.project,
            created_by=self.user,
        )
        
        # Delete the physical file
        file_path = self.service.get_file_path(attachment)
        file_path.unlink()
        
        # Now getting path should raise exception
        with self.assertRaises(AttachmentNotFound):
            self.service.get_file_path(attachment)
    
    def test_soft_delete(self):
        """Test soft delete of attachment."""
        file_content = b'Soft delete'
        file = SimpleUploadedFile('soft.txt', file_content)
        
        attachment = self.service.store_attachment(
            file=file,
            target=self.project,
            created_by=self.user,
        )
        
        file_path = self.service.get_file_path(attachment)
        
        # Soft delete
        self.service.delete_attachment(attachment, hard=False)
        
        # Verify attachment is marked as deleted
        attachment.refresh_from_db()
        self.assertTrue(attachment.is_deleted)
        
        # Verify file still exists
        self.assertTrue(file_path.exists())
    
    def test_hard_delete(self):
        """Test hard delete of attachment."""
        file_content = b'Hard delete'
        file = SimpleUploadedFile('hard.txt', file_content)
        
        attachment = self.service.store_attachment(
            file=file,
            target=self.project,
            created_by=self.user,
        )
        
        file_path = self.service.get_file_path(attachment)
        attachment_id = attachment.id
        
        # Hard delete
        self.service.delete_attachment(attachment, hard=True)
        
        # Verify attachment is deleted from DB
        self.assertFalse(Attachment.objects.filter(id=attachment_id).exists())
        
        # Verify file is deleted
        self.assertFalse(file_path.exists())
    
    def test_custom_role(self):
        """Test using custom role."""
        file_content = b'Custom role'
        file = SimpleUploadedFile('custom.txt', file_content)
        
        # Use a different role than default
        attachment = self.service.store_attachment(
            file=file,
            target=self.item,
            created_by=self.user,
            role=AttachmentRole.COMMENT_ATTACHMENT,  # Different from default for Item
        )
        
        link = AttachmentLink.objects.get(attachment=attachment)
        self.assertEqual(link.role, AttachmentRole.COMMENT_ATTACHMENT)
