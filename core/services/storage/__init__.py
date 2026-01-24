"""
Attachment Storage Service

Provides local filesystem storage for attachments linked to Projects, Items, and ItemComments.
"""

from .service import AttachmentStorageService
from .errors import (
    StorageError,
    AttachmentTooLarge,
    AttachmentNotFound,
    AttachmentWriteError,
)

__all__ = [
    'AttachmentStorageService',
    'StorageError',
    'AttachmentTooLarge',
    'AttachmentNotFound',
    'AttachmentWriteError',
]
