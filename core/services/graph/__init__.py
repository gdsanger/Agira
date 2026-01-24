"""
Microsoft Graph API services for Agira.

This package provides integration with Microsoft Graph API, including:
- Graph API client with token management
- Email sending service (v1 - send only)
- Support for attachments
- Email logging via ItemComment
"""

from .mail_service import send_email, GraphSendResult

__all__ = ['send_email', 'GraphSendResult']
