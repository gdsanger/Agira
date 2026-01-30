"""
Attachment Storage Service

Provides local filesystem storage for attachments.
"""

import hashlib
import os
from pathlib import Path
from typing import Optional, Union, BinaryIO
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.contrib.contenttypes.models import ContentType

from core.models import Attachment, AttachmentLink, Project, Item, ItemComment, User, AttachmentRole
from .errors import AttachmentTooLarge, AttachmentNotFound, AttachmentWriteError
from .paths import build_attachment_path, get_absolute_path, sanitize_filename


# Configuration constants
FILE_CHUNK_SIZE = 8192  # Size in bytes for reading/writing file chunks


class AttachmentStorageService:
    """
    Service for managing attachment storage and linking.
    """
    
    def __init__(self, data_dir: Optional[Union[str, Path]] = None, max_size_mb: Optional[int] = None):
        """
        Initialize the storage service.
        
        Args:
            data_dir: Base directory for attachment storage (defaults to AGIRA_DATA_DIR setting)
            max_size_mb: Maximum file size in MB (defaults to AGIRA_MAX_ATTACHMENT_SIZE_MB setting)
        """
        self.data_dir = Path(data_dir or getattr(settings, 'AGIRA_DATA_DIR', settings.BASE_DIR / 'data'))
        self.max_size_bytes = (max_size_mb or getattr(settings, 'AGIRA_MAX_ATTACHMENT_SIZE_MB', 25)) * 1024 * 1024
        
        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
    
    def _compute_hash(self, file_obj: BinaryIO) -> str:
        """
        Compute SHA256 hash of a file.
        
        Args:
            file_obj: File-like object
            
        Returns:
            Hexadecimal SHA256 hash
        """
        file_obj.seek(0)
        file_hash = hashlib.sha256()
        
        # Read in chunks to handle large files
        while chunk := file_obj.read(FILE_CHUNK_SIZE):
            file_hash.update(chunk)
        
        file_obj.seek(0)
        return file_hash.hexdigest()
    
    def _get_file_size(self, file_obj: BinaryIO) -> int:
        """
        Get file size in bytes.
        
        Args:
            file_obj: File-like object
            
        Returns:
            File size in bytes
        """
        file_obj.seek(0, os.SEEK_END)
        size = file_obj.tell()
        file_obj.seek(0)
        return size
    
    def _determine_role(self, target) -> str:
        """
        Determine the appropriate AttachmentRole based on target type.
        
        Args:
            target: Target object (Project, Item, or ItemComment)
            
        Returns:
            AttachmentRole value
        """
        if isinstance(target, Project):
            return AttachmentRole.PROJECT_FILE
        elif isinstance(target, Item):
            return AttachmentRole.ITEM_FILE
        elif isinstance(target, ItemComment):
            return AttachmentRole.COMMENT_ATTACHMENT
        else:
            raise ValueError(f"Unsupported target type: {type(target).__name__}")
    
    @transaction.atomic
    def store_attachment(
        self,
        file: Union[UploadedFile, BinaryIO],
        target: Union[Project, Item, ItemComment],
        role: Optional[str] = None,
        created_by: Optional[User] = None,
        compute_hash: bool = True,
        original_name: Optional[str] = None,
        content_type: Optional[str] = None,
        content_id: Optional[str] = None
    ) -> Attachment:
        """
        Store an attachment file and create database records.
        
        Args:
            file: File to store (UploadedFile or file-like object)
            target: Target object to attach to (Project, Item, or ItemComment)
            role: AttachmentRole value (auto-determined if not provided)
            created_by: User who created the attachment
            compute_hash: Whether to compute SHA256 hash
            original_name: Original filename (extracted from file if not provided)
            content_type: MIME type (extracted from file if not provided)
            content_id: Content-ID for inline email attachments (optional)
            
        Returns:
            Created Attachment instance
            
        Raises:
            AttachmentTooLarge: If file exceeds size limit
            AttachmentWriteError: If file cannot be written
        """
        # Get file metadata
        if hasattr(file, 'name') and not original_name:
            original_name = file.name
        original_name = original_name or 'unnamed_file'
        
        if hasattr(file, 'content_type') and not content_type:
            content_type = file.content_type
        content_type = content_type or ''
        
        # Check file size
        size_bytes = self._get_file_size(file)
        if size_bytes > self.max_size_bytes:
            max_size_mb = self.max_size_bytes / (1024 * 1024)
            actual_size_mb = size_bytes / (1024 * 1024)
            raise AttachmentTooLarge(
                f"File size ({actual_size_mb:.2f}MB) exceeds maximum allowed size ({max_size_mb:.2f}MB)"
            )
        
        # Compute hash if requested
        sha256 = ''
        if compute_hash:
            sha256 = self._compute_hash(file)
        
        # Determine role if not provided
        if role is None:
            role = self._determine_role(target)
        
        # Create Attachment record first to get ID
        attachment = Attachment.objects.create(
            created_by=created_by,
            original_name=sanitize_filename(original_name),
            content_type=content_type,
            size_bytes=size_bytes,
            sha256=sha256,
            storage_path='',  # Will be updated after we know the ID
            is_deleted=False,
            content_id=content_id or ''
        )
        
        # Build storage path using the attachment ID
        relative_path = build_attachment_path(target, attachment.id, original_name)
        absolute_path = get_absolute_path(self.data_dir, relative_path)
        
        # Ensure parent directory exists
        absolute_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file to storage
        try:
            with open(absolute_path, 'wb') as dest:
                file.seek(0)
                # Write in chunks
                while chunk := file.read(FILE_CHUNK_SIZE):
                    dest.write(chunk)
        except Exception as e:
            # Clean up attachment record if write fails
            attachment.delete()
            raise AttachmentWriteError(f"Failed to write attachment: {str(e)}") from e
        
        # Update attachment with storage path
        attachment.storage_path = relative_path
        attachment.save(update_fields=['storage_path'])
        
        # Create AttachmentLink
        content_type_obj = ContentType.objects.get_for_model(target)
        AttachmentLink.objects.create(
            attachment=attachment,
            target_content_type=content_type_obj,
            target_object_id=target.id,
            role=role
        )
        
        return attachment
    
    def link_attachment(
        self,
        attachment: Attachment,
        target: Union[Project, Item, ItemComment],
        role: Optional[str] = None
    ) -> AttachmentLink:
        """
        Link an existing attachment to a new target.
        
        Args:
            attachment: Existing Attachment instance
            target: Target object to link to
            role: AttachmentRole value (auto-determined if not provided)
            
        Returns:
            Created AttachmentLink instance
        """
        if role is None:
            role = self._determine_role(target)
        
        content_type = ContentType.objects.get_for_model(target)
        
        link, created = AttachmentLink.objects.get_or_create(
            attachment=attachment,
            target_content_type=content_type,
            target_object_id=target.id,
            defaults={'role': role}
        )
        
        return link
    
    def get_file_path(self, attachment: Attachment) -> Path:
        """
        Get the absolute filesystem path for an attachment.
        
        Args:
            attachment: Attachment instance
            
        Returns:
            Absolute Path to the file
            
        Raises:
            AttachmentNotFound: If file doesn't exist
        """
        if not attachment.storage_path:
            raise AttachmentNotFound(f"Attachment {attachment.id} has no storage path")
        
        absolute_path = get_absolute_path(self.data_dir, attachment.storage_path)
        
        if not absolute_path.exists():
            raise AttachmentNotFound(f"Attachment file not found: {absolute_path}")
        
        return absolute_path
    
    def read_attachment(self, attachment: Attachment) -> bytes:
        """
        Read the content of an attachment file.
        
        Args:
            attachment: Attachment instance
            
        Returns:
            File content as bytes
            
        Raises:
            AttachmentNotFound: If file doesn't exist or cannot be read
        """
        file_path = self.get_file_path(attachment)
        
        try:
            with open(file_path, 'rb') as f:
                return f.read()
        except (PermissionError, OSError) as e:
            raise AttachmentNotFound(f"Cannot read attachment file: {str(e)}") from e
    
    def delete_attachment(self, attachment: Attachment, hard: bool = False):
        """
        Delete an attachment (soft or hard delete).
        
        Args:
            attachment: Attachment to delete
            hard: If True, delete file and DB record; if False, just mark as deleted
        """
        if hard:
            # Delete physical file if it exists
            try:
                file_path = self.get_file_path(attachment)
                if file_path.exists():
                    file_path.unlink()
            except AttachmentNotFound:
                pass  # File already gone
            
            # Delete DB record
            attachment.delete()
        else:
            # Soft delete
            attachment.is_deleted = True
            attachment.save(update_fields=['is_deleted'])
