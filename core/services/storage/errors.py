"""
Storage-specific exceptions
"""


class StorageError(Exception):
    """Base exception for storage-related errors"""
    pass


class AttachmentTooLarge(StorageError):
    """Raised when an attachment exceeds the maximum allowed size"""
    pass


class AttachmentNotFound(StorageError):
    """Raised when an attachment file cannot be found"""
    pass


class AttachmentWriteError(StorageError):
    """Raised when an attachment cannot be written to storage"""
    pass
