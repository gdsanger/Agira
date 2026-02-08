"""
WeasyPrint Renderer Implementation

Adapter for rendering HTML to PDF using WeasyPrint engine.
"""

from typing import Optional
import logging

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except ImportError:
    WEASYPRINT_AVAILABLE = False

from .interfaces import IPdfRenderer


logger = logging.getLogger(__name__)


class WeasyPrintRenderer(IPdfRenderer):
    """
    PDF renderer using WeasyPrint engine.
    
    Supports:
    - Static assets via base_url
    - Print CSS with paged media
    - Custom fonts (if configured)
    """
    
    def __init__(self, stylesheets: Optional[list] = None):
        """
        Initialize the renderer.
        
        Args:
            stylesheets: Optional list of CSS file paths to include
        """
        if not WEASYPRINT_AVAILABLE:
            raise ImportError(
                "WeasyPrint is not installed. "
                "Install it with: pip install weasyprint"
            )
        
        self.stylesheets = stylesheets or []
    
    def render_html_to_pdf(self, html: str, base_url: str) -> bytes:
        """
        Render HTML to PDF using WeasyPrint.
        
        Args:
            html: HTML string to render
            base_url: Base URL for resolving relative URLs (e.g., for images, CSS)
            
        Returns:
            PDF content as bytes
            
        Raises:
            Exception: If rendering fails
        """
        try:
            # Create HTML document
            html_doc = HTML(string=html, base_url=base_url)
            
            # Prepare stylesheets
            css_list = [CSS(filename=css) for css in self.stylesheets]
            
            # Render to PDF
            pdf_bytes = html_doc.write_pdf(stylesheets=css_list)
            
            logger.info(f"Successfully rendered PDF: {len(pdf_bytes)} bytes")
            return pdf_bytes
            
        except Exception as e:
            logger.error(f"Failed to render PDF: {e}", exc_info=True)
            raise
