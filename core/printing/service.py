"""
Core PDF Render Service

Central service for rendering HTML templates to PDF.
"""

from typing import Optional
import logging

from django.template.loader import render_to_string
from django.conf import settings

from .interfaces import IPdfRenderer
from .dto import PdfResult
from .weasyprint_renderer import WeasyPrintRenderer


logger = logging.getLogger(__name__)


class PdfRenderService:
    """
    Core service for PDF rendering pipeline.
    
    Responsibilities:
    1. Load and render Django templates to HTML
    2. Delegate PDF rendering to IPdfRenderer implementation
    3. Return structured PdfResult
    
    Usage:
        service = PdfRenderService()
        result = service.render(
            template_name='printing/invoice.html',
            context={'invoice': invoice_data},
            base_url='http://example.com',
            filename='invoice_001.pdf'
        )
    """
    
    def __init__(self, renderer: Optional[IPdfRenderer] = None):
        """
        Initialize the service.
        
        Args:
            renderer: PDF renderer implementation. If None, uses default WeasyPrint renderer.
        """
        self.renderer = renderer or self._get_default_renderer()
    
    def render(
        self,
        template_name: str,
        context: dict,
        *,
        base_url: str,
        filename: Optional[str] = None
    ) -> PdfResult:
        """
        Render a template to PDF.
        
        Args:
            template_name: Django template path (e.g., 'printing/invoice.html')
            context: Template context dictionary
            base_url: Base URL for resolving static assets
            filename: Optional filename for the PDF (defaults to 'document.pdf')
            
        Returns:
            PdfResult with PDF bytes and metadata
            
        Raises:
            Exception: If template rendering or PDF generation fails
        """
        try:
            # Step 1: Render HTML from template
            logger.debug(f"Rendering template: {template_name}")
            html = render_to_string(template_name, context)
            
            # Step 2: Convert HTML to PDF
            logger.debug(f"Converting HTML to PDF with base_url: {base_url}")
            pdf_bytes = self.renderer.render_html_to_pdf(html, base_url)
            
            # Step 3: Create result
            result = PdfResult(
                pdf_bytes=pdf_bytes,
                filename=filename or 'document.pdf',
                content_type='application/pdf'
            )
            
            logger.info(
                f"Successfully generated PDF: {result.filename} "
                f"({len(result.pdf_bytes)} bytes)"
            )
            
            return result
            
        except Exception as e:
            logger.error(
                f"Failed to render PDF for template {template_name}: {e}",
                exc_info=True
            )
            raise
    
    def _get_default_renderer(self) -> IPdfRenderer:
        """
        Get the default PDF renderer.
        
        Returns:
            Default IPdfRenderer implementation (WeasyPrint)
        """
        # In future, this could read from settings.PDF_RENDERER
        # and use a factory/registry pattern
        return WeasyPrintRenderer()
