"""
Change PDF Report Module

Generates ISO-27001 compliant PDF reports for Change objects with all
audit-relevant information structured in a professional format.
"""

from datetime import datetime
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT

from core.services.reporting.styles import get_report_styles

# Constants
MAX_COMMENT_LENGTH = 50  # Maximum length for approval comments in table


def build_change_pdf(change, output):
    """
    Build a PDF report for a Change object.
    
    Args:
        change: Change model instance with all related data
        output: File-like object (e.g., BytesIO) to write PDF bytes to
    
    Returns:
        None (writes to output)
    """
    # Define A4 page with specified margins (20mm left/right, 18mm top/bottom)
    doc = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )
    
    # Get standard styles
    styles = get_report_styles()
    
    # Build the story (content)
    story = []
    
    # --- 1. HEADER SECTION ---
    story.append(Paragraph("Change Report", styles['ReportTitle']))
    story.append(Spacer(1, 5 * mm))
    
    # Document metadata
    story.append(Paragraph(f"<b>Change ID:</b> {change.id}", styles['ReportBody']))
    story.append(Paragraph(
        f"<b>Report Generated:</b> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        styles['ReportBody']
    ))
    story.append(Spacer(1, 8 * mm))
    
    # --- 2. CHANGE OVERVIEW SECTION ---
    story.append(Paragraph("Change Overview", styles['ReportHeading']))
    story.append(Spacer(1, 3 * mm))
    
    overview_data = [
        ['Field', 'Value'],
        ['Title', change.title or '—'],
        ['Project', change.project.name if change.project else '—'],
        ['Status', change.get_status_display() or '—'],
        ['Risk Level', change.get_risk_display() or '—'],
        ['Safety Relevant', 'Yes' if change.is_safety_relevant else 'No'],
        ['Release', f"{change.release.version} ({change.release.get_type_display()})" if change.release else '—'],
        ['Created By', change.created_by.name if change.created_by else '—'],
        ['Created At', change.created_at.strftime('%Y-%m-%d %H:%M:%S') if change.created_at else '—'],
        ['Updated At', change.updated_at.strftime('%Y-%m-%d %H:%M:%S') if change.updated_at else '—'],
    ]
    
    overview_table = Table(overview_data, colWidths=[60 * mm, 110 * mm])
    overview_table.setStyle(_get_key_value_table_style())
    story.append(overview_table)
    story.append(Spacer(1, 8 * mm))
    
    # --- 3. DESCRIPTION & JUSTIFICATION SECTION ---
    story.append(Paragraph("Description & Justification", styles['ReportHeading']))
    story.append(Spacer(1, 3 * mm))
    
    # Description
    description = change.description if change.description else 'Not provided'
    story.append(Paragraph("<b>Description:</b>", styles['ReportBody']))
    # Handle multi-line descriptions
    for line in description.split('\n'):
        line_text = line.strip() if line.strip() else '—'
        story.append(Paragraph(line_text, styles['ReportBody']))
    story.append(Spacer(1, 5 * mm))
    
    # Risk Description
    risk_description = change.risk_description if change.risk_description else 'Not provided'
    story.append(Paragraph("<b>Risk Description:</b>", styles['ReportBody']))
    for line in risk_description.split('\n'):
        line_text = line.strip() if line.strip() else '—'
        story.append(Paragraph(line_text, styles['ReportBody']))
    story.append(Spacer(1, 8 * mm))
    
    # --- 4. IMPLEMENTATION / PLAN SECTION ---
    story.append(Paragraph("Implementation & Planning", styles['ReportHeading']))
    story.append(Spacer(1, 3 * mm))
    
    plan_data = [
        ['Planning Item', 'Details'],
        ['Planned Start', change.planned_start.strftime('%Y-%m-%d %H:%M:%S') if change.planned_start else 'Not scheduled'],
        ['Planned End', change.planned_end.strftime('%Y-%m-%d %H:%M:%S') if change.planned_end else 'Not scheduled'],
        ['Executed At', change.executed_at.strftime('%Y-%m-%d %H:%M:%S') if change.executed_at else 'Not executed yet'],
    ]
    
    plan_table = Table(plan_data, colWidths=[60 * mm, 110 * mm])
    plan_table.setStyle(_get_key_value_table_style())
    story.append(plan_table)
    story.append(Spacer(1, 5 * mm))
    
    # Mitigation Plan
    mitigation = change.mitigation if change.mitigation else 'Not provided'
    story.append(Paragraph("<b>Mitigation Plan:</b>", styles['ReportBody']))
    for line in mitigation.split('\n'):
        line_text = line.strip() if line.strip() else '—'
        story.append(Paragraph(line_text, styles['ReportBody']))
    story.append(Spacer(1, 5 * mm))
    
    # Rollback Plan
    rollback_plan = change.rollback_plan if change.rollback_plan else 'Not provided'
    story.append(Paragraph("<b>Rollback Plan:</b>", styles['ReportBody']))
    for line in rollback_plan.split('\n'):
        line_text = line.strip() if line.strip() else '—'
        story.append(Paragraph(line_text, styles['ReportBody']))
    story.append(Spacer(1, 5 * mm))
    
    # Communication Plan
    communication_plan = change.communication_plan if change.communication_plan else 'Not provided'
    story.append(Paragraph("<b>Communication Plan:</b>", styles['ReportBody']))
    for line in communication_plan.split('\n'):
        line_text = line.strip() if line.strip() else '—'
        story.append(Paragraph(line_text, styles['ReportBody']))
    story.append(Spacer(1, 8 * mm))
    
    # --- 5. APPROVALS / REVIEW / AUDIT TRAIL SECTION ---
    story.append(Paragraph("Approvals & Review", styles['ReportHeading']))
    story.append(Spacer(1, 3 * mm))
    
    approvals = change.approvals.select_related('approver').all()
    if approvals:
        approval_data = [['Approver', 'Status', 'Required', 'Approved At', 'Comment']]
        for approval in approvals:
            approver_name = approval.approver.name if approval.approver else '—'
            status = approval.get_status_display() or '—'
            is_required = 'Yes' if approval.is_required else 'No'
            approved_at = approval.approved_at.strftime('%Y-%m-%d %H:%M') if approval.approved_at else '—'
            comment = approval.comment[:MAX_COMMENT_LENGTH] + '...' if approval.comment and len(approval.comment) > MAX_COMMENT_LENGTH else (approval.comment or '—')
            
            approval_data.append([
                approver_name,
                status,
                is_required,
                approved_at,
                comment
            ])
        
        approval_table = Table(approval_data, colWidths=[40 * mm, 30 * mm, 25 * mm, 35 * mm, 40 * mm])
        approval_table.setStyle(_get_data_table_style())
        story.append(approval_table)
    else:
        story.append(Paragraph("No approvers assigned", styles['ReportBody']))
    
    story.append(Spacer(1, 8 * mm))
    
    # --- 6. ORGANISATIONS SECTION ---
    organisations = change.organisations.all()
    if organisations:
        story.append(Paragraph("Assigned Organisations", styles['ReportHeading']))
        story.append(Spacer(1, 3 * mm))
        
        org_data = [['Organisation Name']]
        for org in organisations:
            org_data.append([org.name])
        
        org_table = Table(org_data, colWidths=[170 * mm])
        org_table.setStyle(_get_data_table_style())
        story.append(org_table)
        story.append(Spacer(1, 8 * mm))
    
    # --- 7. ATTACHMENTS / REFERENCES SECTION ---
    # Note: We only list metadata, not embed binary data
    story.append(Paragraph("Attachments & References", styles['ReportHeading']))
    story.append(Spacer(1, 3 * mm))
    
    # Get attachments via generic relation if available
    # For now, we'll note that attachments would be listed here
    story.append(Paragraph("Attachment listing would appear here (metadata only)", styles['ReportBody']))
    story.append(Paragraph("Note: Binary data is not embedded in this report for compliance reasons", styles['ReportBody']))
    
    # Build the PDF
    doc.build(story)


def _get_key_value_table_style():
    """Get table style for key-value tables"""
    return TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a5568')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        
        # Data rows
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        
        # First column (keys) in bold
        ('FONTNAME', (0, 1), (0, -1), 'Helvetica-Bold'),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        
        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7fafc')]),
    ])


def _get_data_table_style():
    """Get table style for data tables"""
    return TableStyle([
        # Header row
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a5568')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('TOPPADDING', (0, 0), (-1, 0), 8),
        
        # Data rows
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        
        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7fafc')]),
    ])
