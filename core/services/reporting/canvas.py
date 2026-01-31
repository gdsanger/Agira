"""
Canvas Helpers

Provides helper functions for drawing headers, footers, and page numbers.
"""

from reportlab.lib.units import cm
from reportlab.lib import colors


def draw_page_number(canvas, doc):
    """
    Draw page number in the format 'Page X of Y'.
    
    Args:
        canvas: ReportLab canvas object
        doc: ReportLab document object
    """
    page_num = canvas.getPageNumber()
    text = f"Page {page_num}"
    
    # Draw at bottom center
    canvas.saveState()
    canvas.setFont('Helvetica', 8)
    canvas.setFillColor(colors.HexColor('#666666'))
    canvas.drawCentredString(
        doc.pagesize[0] / 2,
        1.5 * cm,
        text
    )
    canvas.restoreState()


def draw_header(canvas, doc, title, subtitle=None):
    """
    Draw a standard header with title and optional subtitle.
    
    Args:
        canvas: ReportLab canvas object
        doc: ReportLab document object
        title: Main title text
        subtitle: Optional subtitle text
    """
    canvas.saveState()
    
    # Draw title
    canvas.setFont('Helvetica-Bold', 12)
    canvas.setFillColor(colors.HexColor('#1a1a1a'))
    canvas.drawString(2 * cm, doc.pagesize[1] - 2 * cm, title)
    
    # Draw subtitle if provided
    if subtitle:
        canvas.setFont('Helvetica', 9)
        canvas.setFillColor(colors.HexColor('#666666'))
        canvas.drawString(2 * cm, doc.pagesize[1] - 2.5 * cm, subtitle)
    
    # Draw horizontal line
    canvas.setStrokeColor(colors.HexColor('#cccccc'))
    canvas.setLineWidth(0.5)
    y_line = doc.pagesize[1] - (3 * cm if subtitle else 2.5 * cm)
    canvas.line(2 * cm, y_line, doc.pagesize[0] - 2 * cm, y_line)
    
    canvas.restoreState()


def draw_footer(canvas, doc, footer_text=None):
    """
    Draw a standard footer with optional text and page number.
    
    Args:
        canvas: ReportLab canvas object
        doc: ReportLab document object
        footer_text: Optional footer text (drawn on left side)
    """
    canvas.saveState()
    
    # Draw horizontal line
    canvas.setStrokeColor(colors.HexColor('#cccccc'))
    canvas.setLineWidth(0.5)
    canvas.line(2 * cm, 2.5 * cm, doc.pagesize[0] - 2 * cm, 2.5 * cm)
    
    # Draw footer text if provided
    if footer_text:
        canvas.setFont('Helvetica', 8)
        canvas.setFillColor(colors.HexColor('#666666'))
        canvas.drawString(2 * cm, 2 * cm, footer_text)
    
    # Draw page number
    draw_page_number(canvas, doc)
    
    canvas.restoreState()


def create_header_footer_function(title, subtitle=None, footer_text=None):
    """
    Create a header/footer function that can be passed to SimpleDocTemplate.
    
    Args:
        title: Main title for header
        subtitle: Optional subtitle for header
        footer_text: Optional text for footer
        
    Returns:
        Function that draws header and footer
    """
    def header_footer(canvas, doc):
        draw_header(canvas, doc, title, subtitle)
        draw_footer(canvas, doc, footer_text)
    
    return header_footer
