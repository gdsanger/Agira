"""
Mail services for Agira.

This package contains mail-related services including template processing
and mail trigger handling.
"""

from .template_processor import process_template
from .mail_trigger_service import check_mail_trigger, prepare_mail_preview, get_notification_recipients_for_item

__all__ = [
    'process_template',
    'check_mail_trigger',
    'prepare_mail_preview',
    'get_notification_recipients_for_item',
]
