"""
Reports package

Contains report templates for PDF generation.
"""

from core.services.reporting.registry import register_template
from .templates.change_v1 import ChangeReportV1


def register_all_templates():
    """Register all available report templates"""
    register_template('change.v1', ChangeReportV1)


# Auto-register templates when module is imported
register_all_templates()
