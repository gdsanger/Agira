"""
PDF Styling

Provides standard styles for PDF reports.
"""

from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib import colors
from reportlab.lib.units import cm


def get_report_styles():
    """
    Get standard report styles.
    
    Returns:
        Dictionary of ParagraphStyle objects
    """
    styles = getSampleStyleSheet()
    
    # Custom styles for reports
    custom_styles = {
        'ReportTitle': ParagraphStyle(
            'ReportTitle',
            parent=styles['Heading1'],
            fontSize=18,
            textColor=colors.HexColor('#1a1a1a'),
            spaceAfter=20,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        ),
        'ReportHeading': ParagraphStyle(
            'ReportHeading',
            parent=styles['Heading2'],
            fontSize=14,
            textColor=colors.HexColor('#333333'),
            spaceAfter=12,
            spaceBefore=12,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        ),
        'ReportSubheading': ParagraphStyle(
            'ReportSubheading',
            parent=styles['Heading3'],
            fontSize=12,
            textColor=colors.HexColor('#555555'),
            spaceAfter=8,
            spaceBefore=8,
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        ),
        'ReportBody': ParagraphStyle(
            'ReportBody',
            parent=styles['BodyText'],
            fontSize=10,
            textColor=colors.HexColor('#000000'),
            spaceAfter=6,
            alignment=TA_LEFT,
            fontName='Helvetica'
        ),
        'ReportFooter': ParagraphStyle(
            'ReportFooter',
            parent=styles['Normal'],
            fontSize=8,
            textColor=colors.HexColor('#666666'),
            alignment=TA_CENTER,
            fontName='Helvetica'
        ),
        'TableHeader': ParagraphStyle(
            'TableHeader',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#ffffff'),
            alignment=TA_LEFT,
            fontName='Helvetica-Bold'
        ),
        'TableCell': ParagraphStyle(
            'TableCell',
            parent=styles['Normal'],
            fontSize=9,
            textColor=colors.HexColor('#000000'),
            alignment=TA_LEFT,
            fontName='Helvetica'
        ),
    }
    
    return custom_styles


def get_table_style():
    """
    Get standard table style for reports.
    
    Returns:
        TableStyle with standard formatting
    """
    from reportlab.platypus import TableStyle
    
    return TableStyle([
        # Header row styling
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4a5568')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('TOPPADDING', (0, 0), (-1, 0), 12),
        
        # Data rows styling
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 8),
        
        # Grid
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        
        # Alternating row colors
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f7fafc')]),
    ])
