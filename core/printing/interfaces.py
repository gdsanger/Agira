"""
Interfaces for the Printing Framework

Defines core interfaces that can be implemented by different rendering engines
and context builders.
"""

from abc import ABC, abstractmethod
from typing import Any


class IPdfRenderer(ABC):
    """
    Interface for PDF rendering engines.
    
    Implementations convert HTML to PDF bytes using their specific engine.
    """
    
    @abstractmethod
    def render_html_to_pdf(self, html: str, base_url: str) -> bytes:
        """
        Render HTML to PDF.
        
        Args:
            html: HTML string to render
            base_url: Base URL for resolving relative URLs (static assets, etc.)
            
        Returns:
            PDF content as bytes
            
        Raises:
            Exception: If rendering fails
        """
        pass


class IContextBuilder(ABC):
    """
    Interface for building template contexts from objects.
    
    This is a placeholder for future module-specific context builders
    (e.g., for invoices, quotes, reports).
    """
    
    @abstractmethod
    def build_context(self, obj: Any, *, company: Any = None) -> dict:
        """
        Build template context from an object.
        
        Args:
            obj: The object to build context from
            company: Optional company/organization context
            
        Returns:
            Dictionary with template context
        """
        pass
    
    def get_template_name(self, obj: Any) -> str:
        """
        Get template name for an object (optional).
        
        Args:
            obj: The object to get template for
            
        Returns:
            Template name/path
        """
        raise NotImplementedError("Subclass must implement get_template_name if needed")
