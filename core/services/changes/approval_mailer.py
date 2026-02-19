"""
Change Approval Email Service

Sends approval request emails to Change approvers with approve/reject links
and Change PDF as attachment.
"""

import logging
from typing import Optional
from io import BytesIO

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from core.models import MailTemplate, Attachment, Change, ChangeApproval
from core.services.graph.mail_service import send_email, GraphSendResult
from core.services.exceptions import ServiceError
from core.printing.service import PdfRenderService
from core.printing.dto import PdfResult

logger = logging.getLogger(__name__)


def build_decision_url(change_id: int, token: str, decision: str) -> str:
    """
    Build the decision URL for approve/reject links.
    
    Args:
        change_id: ID of the Change
        token: Decision token
        decision: 'approve' or 'reject'
        
    Returns:
        Full URL with token and decision parameters
    """
    path = reverse("change_approval_decision")
    return f"{settings.APP_BASE_URL}{path}?token={token}&change_id={change_id}&decision={decision}"


def generate_change_pdf_bytes(change: Change, request_base_url: str) -> bytes:
    """
    Generate PDF for a Change as bytes.
    
    Args:
        change: Change instance
        request_base_url: Base URL for resolving static assets
        
    Returns:
        PDF content as bytes
        
    Raises:
        ServiceError: If PDF generation fails or PDF exceeds size limit
    """
    from datetime import datetime
    from core.models import SystemSetting
    
    # Get associated items
    items = change.get_associated_items()
    
    # Get approvals
    approvals = change.approvals.select_related('approver').all()
    
    # Get organisations
    organisations = change.organisations.all()
    
    # Get system settings for header/footer
    system_setting = SystemSetting.get_instance()
    
    # Generate change reference: YYYYMMDD-ID
    change_reference = f"{change.created_at.strftime('%Y%m%d')}-{change.id}"
    
    # Prepare context for template
    context = {
        'change': change,
        'items': items,
        'approvals': approvals,
        'organisations': organisations,
        'now': datetime.now(),
        'system_setting': system_setting,
        'change_reference': change_reference,
    }
    
    # Render PDF using Weasyprint
    service = PdfRenderService()
    result: PdfResult = service.render(
        template_name='printing/change_report.html',
        context=context,
        base_url=request_base_url,
        filename=f"change-{change.id}.pdf"
    )
    
    # Check size limit (3 MB as per GraphAPI limit)
    max_size = 3 * 1024 * 1024  # 3 MB
    if len(result) > max_size:
        raise ServiceError(
            f"Change PDF is too large ({len(result) / (1024*1024):.1f} MB). "
            f"Maximum size for email attachment is {max_size / (1024*1024):.0f} MB"
        )
    
    return result.pdf_bytes


def render_template(template: MailTemplate, change: Change, approve_url: str, reject_url: str, recipient_name: str = '') -> dict:
    """
    Render email template with variables replaced.
    
    Args:
        template: MailTemplate instance
        change: Change instance
        approve_url: Full URL for approve action
        reject_url: Full URL for reject action
        recipient_name: Name of the recipient approver
        
    Returns:
        Dict with 'subject' and 'message' keys
    """
    from datetime import timedelta

    # Calculate deadline: planned_start minus 2 days (date only)
    deadline_str = ''
    if change.planned_start:
        deadline_str = (change.planned_start - timedelta(days=2)).strftime('%Y-%m-%d')

    variables = {
        '{{ change_id }}': str(change.id),
        '{{ change_title }}': change.title,
        '{{ approve_url }}': approve_url,
        '{{ reject_url }}': reject_url,
        '{{ description }}': change.description or '',
        '{{ name }}': recipient_name,
        '{{ deadline }}': deadline_str,
    }
    
    subject = template.subject
    message = template.message
    
    for var, value in variables.items():
        subject = subject.replace(var, value)
        message = message.replace(var, value)
    
    return {
        'subject': subject,
        'message': message
    }


def create_attachment_from_bytes(pdf_bytes: bytes, filename: str, change: Change) -> Attachment:
    """
    Create an Attachment instance from PDF bytes.
    
    Args:
        pdf_bytes: PDF content as bytes
        filename: Filename for the attachment
        change: Change instance (for project association)
        
    Returns:
        Attachment instance (saved to database and storage)
    """
    from io import BytesIO
    from core.services.storage.service import AttachmentStorageService
    from core.models import AttachmentRole

    file_obj = BytesIO(pdf_bytes)
    service = AttachmentStorageService()
    return service.store_attachment(
        file=file_obj,
        target=change.project,
        role=AttachmentRole.APPROVER_ATTACHMENT,
        original_name=filename,
        content_type='application/pdf',
    )


def send_change_approval_request_emails(change: Change, request_base_url: str) -> dict:
    """
    Send approval request emails to all approvers for a Change.
    
    Args:
        change: Change instance
        request_base_url: Base URL for building absolute URLs and PDF generation
        
    Returns:
        Dict with 'success' (bool), 'sent_count' (int), 'failed_count' (int),
        'errors' (list of error messages)
        
    Raises:
        ServiceError: If template not found or PDF generation fails
    """
    # Load template
    try:
        template = MailTemplate.objects.get(key="change-approval-request", is_active=True)
    except MailTemplate.DoesNotExist:
        raise ServiceError(
            "MailTemplate with key 'change-approval-request' not found or not active. "
            "Please create and activate this template in the admin interface."
        )
    
    # Generate PDF
    try:
        pdf_bytes = generate_change_pdf_bytes(change, request_base_url)
        pdf_filename = f"change-{change.id}.pdf"
    except Exception as e:
        logger.error(f"Failed to generate PDF for Change {change.id}: {str(e)}")
        raise ServiceError(f"Failed to generate Change PDF: {str(e)}")
    
    # Create attachment from PDF bytes
    try:
        pdf_attachment = create_attachment_from_bytes(pdf_bytes, pdf_filename, change)
    except Exception as e:
        logger.error(f"Failed to create attachment for Change {change.id}: {str(e)}")
        raise ServiceError(f"Failed to create PDF attachment: {str(e)}")
    
    # Track results
    sent_count = 0
    failed_count = 0
    errors = []
    
    # Send email to each approver
    approvals = change.get_approvals()
    for approval in approvals:
        try:
            # Ensure token exists
            had_token = bool(approval.decision_token)
            approval.ensure_token()
            if not had_token:
                # Token was just generated, save it
                approval.save(update_fields=['decision_token'])
            
            # Build approve/reject URLs
            approve_url = build_decision_url(change.id, approval.decision_token, 'approve')
            reject_url = build_decision_url(change.id, approval.decision_token, 'reject')
            
            # Render template
            rendered = render_template(template, change, approve_url, reject_url, recipient_name=approval.approver.name)
            
            # Send email
            result: GraphSendResult = send_email(
                subject=rendered['subject'],
                body=rendered['message'],
                to=[approval.approver.email],
                body_is_html=True,
                attachments=[pdf_attachment],
            )
            
            if result.success:
                sent_count += 1
                logger.info(
                    f"Sent approval request email to {approval.approver.email} "
                    f"for Change {change.id}"
                )
            else:
                failed_count += 1
                error_msg = f"{approval.approver.email}: {result.error}"
                errors.append(error_msg)
                logger.error(
                    f"Failed to send approval request email to {approval.approver.email} "
                    f"for Change {change.id}: {result.error}"
                )
        
        except Exception as e:
            failed_count += 1
            error_msg = f"{approval.approver.email}: {str(e)}"
            errors.append(error_msg)
            logger.error(
                f"Exception sending approval request email to {approval.approver.email} "
                f"for Change {change.id}: {str(e)}"
            )
    
    return {
        'success': failed_count == 0,
        'sent_count': sent_count,
        'failed_count': failed_count,
        'errors': errors,
    }


def send_change_approval_reminder_emails(change: Change, request_base_url: str) -> dict:
    """
    Send reminder emails to all PENDING approvers for a Change.

    Args:
        change: Change instance
        request_base_url: Base URL for building absolute URLs and PDF generation

    Returns:
        Dict with 'success' (bool), 'sent_count' (int), 'failed_count' (int),
        'errors' (list of error messages)

    Raises:
        ServiceError: If template not found or PDF generation fails
    """
    # Load reminder template
    try:
        template = MailTemplate.objects.get(key="change-approval-reminder", is_active=True)
    except MailTemplate.DoesNotExist:
        raise ServiceError(
            "MailTemplate with key 'change-approval-reminder' not found or not active. "
            "Please create and activate this template in the admin interface."
        )

    # Generate PDF
    try:
        pdf_bytes = generate_change_pdf_bytes(change, request_base_url)
        pdf_filename = f"change-{change.id}.pdf"
    except Exception as e:
        logger.error(f"Failed to generate PDF for Change {change.id}: {str(e)}")
        raise ServiceError(f"Failed to generate Change PDF: {str(e)}")

    # Create attachment from PDF bytes
    try:
        pdf_attachment = create_attachment_from_bytes(pdf_bytes, pdf_filename, change)
    except Exception as e:
        logger.error(f"Failed to create attachment for Change {change.id}: {str(e)}")
        raise ServiceError(f"Failed to create PDF attachment: {str(e)}")

    # Track results
    sent_count = 0
    failed_count = 0
    errors = []

    # Send reminder only to PENDING approvers
    pending_approvals = change.approvals.select_related('approver').filter(
        status=ApprovalStatus.PENDING
    )
    for approval in pending_approvals:
        try:
            # Ensure token exists
            had_token = bool(approval.decision_token)
            approval.ensure_token()
            if not had_token:
                approval.save(update_fields=['decision_token'])

            # Build approve/reject URLs
            approve_url = build_decision_url(change.id, approval.decision_token, 'approve')
            reject_url = build_decision_url(change.id, approval.decision_token, 'reject')

            # Render template
            rendered = render_template(template, change, approve_url, reject_url, recipient_name=approval.approver.name)

            # Send email
            result: GraphSendResult = send_email(
                subject=rendered['subject'],
                body=rendered['message'],
                to=[approval.approver.email],
                body_is_html=True,
                attachments=[pdf_attachment],
            )

            if result.success:
                sent_count += 1
                logger.info(
                    f"Sent approval reminder email to {approval.approver.email} "
                    f"for Change {change.id}"
                )
            else:
                failed_count += 1
                error_msg = f"{approval.approver.email}: {result.error}"
                errors.append(error_msg)
                logger.error(
                    f"Failed to send approval reminder email to {approval.approver.email} "
                    f"for Change {change.id}: {result.error}"
                )

        except Exception as e:
            failed_count += 1
            error_msg = f"{approval.approver.email}: {str(e)}"
            errors.append(error_msg)
            logger.error(
                f"Exception sending approval reminder email to {approval.approver.email} "
                f"for Change {change.id}: {str(e)}"
            )

    return {
        'success': failed_count == 0,
        'sent_count': sent_count,
        'failed_count': failed_count,
        'errors': errors,
    }
