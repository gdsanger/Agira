"""
Core Report Service

Provides centralized PDF report generation, versioning, and storage.
"""

import hashlib
import json
from io import BytesIO
from typing import Optional

from django.core.files.base import ContentFile
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate

from .registry import get_template


class ReportService:
    """
    Core service for PDF report generation and storage.
    
    This service provides:
    - PDF rendering using ReportLab Platypus
    - Template-based report generation via registry
    - Persistence with context snapshot
    - Repeatable generation (same input → same output)
    """
    
    def render(self, report_key: str, context: dict) -> bytes:
        """
        Render a report to PDF bytes.
        
        Args:
            report_key: Report template identifier (e.g., 'change.v1')
            context: Serializable dict with report data
            
        Returns:
            PDF content as bytes
            
        Raises:
            KeyError: If report_key is not registered
        """
        # Get template from registry
        template = get_template(report_key)
        
        # Create PDF buffer
        buffer = BytesIO()
        
        # Create document with A4 page size
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            rightMargin=2 * 72,  # 2cm in points
            leftMargin=2 * 72,
            topMargin=3 * 72,    # 3cm for header
            bottomMargin=3 * 72  # 3cm for footer
        )
        
        # Build story (content) from template
        story = template.build_story(context)
        
        # Check if template has custom header/footer
        if hasattr(template, 'draw_header_footer'):
            def on_page(canvas, doc_obj):
                template.draw_header_footer(canvas, doc_obj, context)
            
            doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
        else:
            doc.build(story)
        
        # Get PDF bytes
        pdf_bytes = buffer.getvalue()
        buffer.close()
        
        return pdf_bytes
    
    def generate_and_store(
        self,
        report_key: str,
        object_type: str,
        object_id: str | int,
        context: dict,
        created_by=None,
        metadata: Optional[dict] = None
    ):
        """
        Generate a PDF report and store it with context snapshot.
        
        Args:
            report_key: Report template identifier (e.g., 'change.v1')
            object_type: Type of object this report is for (e.g., 'change')
            object_id: ID of the object
            context: Serializable dict with report data
            created_by: User who created the report (optional)
            metadata: Additional metadata to store (optional)
            
        Returns:
            ReportDocument instance
            
        Raises:
            KeyError: If report_key is not registered
        """
        # Import here to avoid circular imports
        from core.models import ReportDocument
        
        # Render PDF
        pdf_bytes = self.render(report_key, context)
        
        # Calculate SHA256 hash for integrity
        pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
        
        # Serialize context to JSON
        context_json = json.dumps(context, indent=2, ensure_ascii=False)
        
        # Create ReportDocument
        report = ReportDocument(
            report_key=report_key,
            object_type=object_type,
            object_id=str(object_id),
            created_at=timezone.now(),
            created_by=created_by,
            context_json=context_json,
            sha256=pdf_hash,
            metadata_json=json.dumps(metadata) if metadata else None
        )
        
        # Save PDF file
        filename = f"{report_key}_{object_type}_{object_id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        report.pdf_file.save(filename, ContentFile(pdf_bytes), save=False)
        
        # Save the report
        report.save()
        
        return report
