"""
Change Report Template (v1)

Template for generating Change PDF reports.
"""

from datetime import datetime
from reportlab.platypus import Paragraph, Spacer, Table, PageBreak
from reportlab.lib.units import cm

from core.services.reporting.styles import get_report_styles, get_table_style
from core.services.reporting.canvas import draw_header, draw_footer


class ChangeReportV1:
    """Template for Change reports version 1"""
    
    def __init__(self):
        self.styles = get_report_styles()
    
    def build_story(self, context: dict) -> list:
        """
        Build the PDF story from context data.
        
        Expected context structure:
        {
            'title': str,
            'project_name': str,
            'description': str,
            'status': str,
            'risk': str,
            'planned_start': str (ISO format datetime or display string),
            'planned_end': str (ISO format datetime or display string),
            'executed_at': str (ISO format datetime or display string),
            'risk_description': str,
            'mitigation': str,
            'rollback_plan': str,
            'communication_plan': str,
            'created_by': str,
            'created_at': str (ISO format datetime or display string),
            'items': list of dict with 'title' and 'status',
            'approvals': list of dict with 'approver', 'status', 'decision_at'
        }
        """
        story = []
        
        # Title
        title = context.get('title', 'Change Report')
        story.append(Paragraph(title, self.styles['ReportTitle']))
        story.append(Spacer(1, 0.5 * cm))
        
        # Project and metadata
        project = context.get('project_name', 'N/A')
        story.append(Paragraph(f"<b>Project:</b> {project}", self.styles['ReportBody']))
        
        created_by = context.get('created_by', 'N/A')
        created_at = context.get('created_at', 'N/A')
        story.append(Paragraph(f"<b>Created by:</b> {created_by} on {created_at}", self.styles['ReportBody']))
        
        story.append(Spacer(1, 0.5 * cm))
        
        # Status and Risk
        story.append(Paragraph("Status and Risk Assessment", self.styles['ReportHeading']))
        
        status = context.get('status', 'N/A')
        risk = context.get('risk', 'N/A')
        story.append(Paragraph(f"<b>Status:</b> {status}", self.styles['ReportBody']))
        story.append(Paragraph(f"<b>Risk Level:</b> {risk}", self.styles['ReportBody']))
        
        story.append(Spacer(1, 0.3 * cm))
        
        # Timing
        story.append(Paragraph("Timing", self.styles['ReportHeading']))
        
        planned_start = context.get('planned_start', 'N/A')
        planned_end = context.get('planned_end', 'N/A')
        executed_at = context.get('executed_at', 'N/A')
        
        story.append(Paragraph(f"<b>Planned Start:</b> {planned_start}", self.styles['ReportBody']))
        story.append(Paragraph(f"<b>Planned End:</b> {planned_end}", self.styles['ReportBody']))
        story.append(Paragraph(f"<b>Executed At:</b> {executed_at}", self.styles['ReportBody']))
        
        story.append(Spacer(1, 0.5 * cm))
        
        # Description
        description = context.get('description', '')
        if description:
            story.append(Paragraph("Description", self.styles['ReportHeading']))
            # Split into paragraphs to preserve line breaks
            for para in description.split('\n'):
                if para.strip():
                    story.append(Paragraph(para, self.styles['ReportBody']))
            story.append(Spacer(1, 0.3 * cm))
        
        # Risk details
        risk_description = context.get('risk_description', '')
        if risk_description:
            story.append(Paragraph("Risk Description", self.styles['ReportHeading']))
            for para in risk_description.split('\n'):
                if para.strip():
                    story.append(Paragraph(para, self.styles['ReportBody']))
            story.append(Spacer(1, 0.3 * cm))
        
        # Mitigation
        mitigation = context.get('mitigation', '')
        if mitigation:
            story.append(Paragraph("Mitigation Plan", self.styles['ReportHeading']))
            for para in mitigation.split('\n'):
                if para.strip():
                    story.append(Paragraph(para, self.styles['ReportBody']))
            story.append(Spacer(1, 0.3 * cm))
        
        # Rollback plan
        rollback_plan = context.get('rollback_plan', '')
        if rollback_plan:
            story.append(Paragraph("Rollback Plan", self.styles['ReportHeading']))
            for para in rollback_plan.split('\n'):
                if para.strip():
                    story.append(Paragraph(para, self.styles['ReportBody']))
            story.append(Spacer(1, 0.3 * cm))
        
        # Communication plan
        communication_plan = context.get('communication_plan', '')
        if communication_plan:
            story.append(Paragraph("Communication Plan", self.styles['ReportHeading']))
            for para in communication_plan.split('\n'):
                if para.strip():
                    story.append(Paragraph(para, self.styles['ReportBody']))
            story.append(Spacer(1, 0.3 * cm))
        
        # Related Items
        items = context.get('items', [])
        if items:
            story.append(Paragraph("Related Items", self.styles['ReportHeading']))
            
            table_data = [['Title', 'Status']]
            for item in items:
                table_data.append([
                    Paragraph(item.get('title', 'N/A'), self.styles['TableCell']),
                    Paragraph(item.get('status', 'N/A'), self.styles['TableCell'])
                ])
            
            table = Table(table_data, colWidths=[12 * cm, 4 * cm])
            table.setStyle(get_table_style())
            story.append(table)
            story.append(Spacer(1, 0.5 * cm))
        
        # Approvals
        approvals = context.get('approvals', [])
        if approvals:
            story.append(Paragraph("Approvals", self.styles['ReportHeading']))
            
            table_data = [['Approver', 'Status', 'Decision Date']]
            for approval in approvals:
                table_data.append([
                    Paragraph(approval.get('approver', 'N/A'), self.styles['TableCell']),
                    Paragraph(approval.get('status', 'N/A'), self.styles['TableCell']),
                    Paragraph(approval.get('decision_at', 'N/A'), self.styles['TableCell'])
                ])
            
            table = Table(table_data, colWidths=[6 * cm, 5 * cm, 5 * cm])
            table.setStyle(get_table_style())
            story.append(table)
        
        return story
    
    def draw_header_footer(self, canvas, doc, context: dict):
        """Draw header and footer on each page"""
        title = context.get('title', 'Change Report')
        project = context.get('project_name', '')
        subtitle = f"Project: {project}" if project else None
        
        draw_header(canvas, doc, title, subtitle)
        
        footer_text = f"Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        draw_footer(canvas, doc, footer_text)
