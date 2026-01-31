"""
Report Template Registry

Central registry for resolving report types to their template implementations.
"""

from typing import Protocol, Callable, Any
from reportlab.platypus import Flowable


class ReportTemplate(Protocol):
    """Protocol defining the interface for report templates"""
    
    def build_story(self, context: dict) -> list[Flowable]:
        """Build the report story (content) from context data"""
        ...
    
    def draw_header_footer(self, canvas: Any, doc: Any, context: dict) -> None:
        """Optional: Draw header and footer on each page"""
        ...


class ReportRegistry:
    """Registry for report templates"""
    
    def __init__(self):
        self._templates: dict[str, Callable[[], ReportTemplate]] = {}
    
    def register(self, report_key: str, template_factory: Callable[[], ReportTemplate]) -> None:
        """
        Register a report template.
        
        Args:
            report_key: Unique identifier for the report type (e.g., 'change.v1')
            template_factory: Factory function that returns a template instance
        """
        if report_key in self._templates:
            raise ValueError(f"Report template '{report_key}' is already registered")
        self._templates[report_key] = template_factory
    
    def get_template(self, report_key: str) -> ReportTemplate:
        """
        Get a report template by its key.
        
        Args:
            report_key: The report key to look up
            
        Returns:
            The template instance
            
        Raises:
            KeyError: If the report key is not registered
        """
        if report_key not in self._templates:
            raise KeyError(f"Report template '{report_key}' not found")
        return self._templates[report_key]()
    
    def is_registered(self, report_key: str) -> bool:
        """Check if a report key is registered"""
        return report_key in self._templates
    
    def list_templates(self) -> list[str]:
        """List all registered report keys"""
        return list(self._templates.keys())


# Global registry instance
_registry = ReportRegistry()


def register_template(report_key: str, template_factory: Callable[[], ReportTemplate]) -> None:
    """Register a report template in the global registry"""
    _registry.register(report_key, template_factory)


def get_template(report_key: str) -> ReportTemplate:
    """Get a report template from the global registry"""
    return _registry.get_template(report_key)


def is_registered(report_key: str) -> bool:
    """Check if a report key is registered"""
    return _registry.is_registered(report_key)


def list_templates() -> list[str]:
    """List all registered report keys"""
    return _registry.list_templates()
