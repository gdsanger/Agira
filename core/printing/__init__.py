"""
Core Printing Framework

Provides centralized PDF generation from HTML templates using WeasyPrint.
Supports paged media with headers, footers, and page numbers.
"""

from .service import PdfRenderService
from .dto import PdfResult
from .interfaces import IPdfRenderer, IContextBuilder

__all__ = [
    'PdfRenderService',
    'PdfResult',
    'IPdfRenderer',
    'IContextBuilder',
]
