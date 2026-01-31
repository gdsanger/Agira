# Core Report Service – Implementation Summary

## Overview

This document describes the implementation of the **Core Report Service**, a centralized PDF report generation system with versioning, audit trail, and extensibility for the Agira project.

## Purpose

The Core Report Service provides:
- **Generic PDF report generation** using ReportLab Platypus
- **Template-based architecture** for different report types
- **Versioning** of report templates (e.g., `change.v1`, `invoice.v1`)
- **Context snapshot persistence** for ISO-compliant audit trails
- **Repeatable generation** (same input → same output)
- **Extensibility** for future report types (invoices, offers, etc.)

## Architecture

### Components

1. **`core/services/reporting/service.py`** - Main `ReportService` class
2. **`core/services/reporting/registry.py`** - Template registry for resolving report types
3. **`core/services/reporting/styles.py`** - Standard PDF styles and table formatting
4. **`core/services/reporting/canvas.py`** - Header/footer helpers and page numbers
5. **`reports/templates/change_v1.py`** - First report template (Change Report v1)
6. **`core/models.py`** - `ReportDocument` model for persistence

### Data Flow

```
User Request
    ↓
ReportService.render(report_key, context)
    ↓
Registry.get_template(report_key)
    ↓
Template.build_story(context) → Platypus Story
    ↓
ReportLab PDF Generation
    ↓
PDF Bytes
```

For persistence:
```
ReportService.generate_and_store(...)
    ↓
render() → PDF bytes
    ↓
Calculate SHA256 hash
    ↓
Serialize context to JSON
    ↓
Create ReportDocument
    ↓
Save PDF file + context snapshot
```

## Core Service Interface

### `ReportService`

```python
from core.services.reporting import ReportService

service = ReportService()

# Render PDF to bytes (no persistence)
pdf_bytes = service.render(
    report_key='change.v1',
    context={...}
)

# Generate and store with audit trail
report = service.generate_and_store(
    report_key='change.v1',
    object_type='change',
    object_id=change.id,
    context={...},
    created_by=user,
    metadata={'version': '1.0'}  # optional
)
```

### Template Registry

```python
from core.services.reporting.registry import (
    register_template,
    get_template,
    list_templates,
    is_registered
)

# Register a new template
register_template('invoice.v1', InvoiceTemplateV1)

# Check registration
if is_registered('change.v1'):
    template = get_template('change.v1')

# List all templates
templates = list_templates()  # ['change.v1', ...]
```

## Report Template Structure

Each report template must implement:

```python
class MyReportTemplate:
    def build_story(self, context: dict) -> list[Flowable]:
        """Build the PDF content from context"""
        story = []
        # Add paragraphs, tables, etc.
        return story
    
    def draw_header_footer(self, canvas, doc, context: dict):
        """Optional: Draw custom header/footer"""
        # Use canvas drawing commands
        pass
```

## Database Model

### `ReportDocument`

Stores generated reports with full audit trail:

```python
class ReportDocument(models.Model):
    report_key = CharField(...)        # 'change.v1'
    object_type = CharField(...)       # 'change'
    object_id = CharField(...)         # '123'
    created_at = DateTimeField(...)
    created_by = ForeignKey(User, ...)
    context_json = TextField(...)      # Snapshot of context
    pdf_file = FileField(...)          # Stored PDF
    sha256 = CharField(...)            # Hash for integrity
    metadata_json = TextField(...)     # Optional metadata
```

**Key features:**
- Context snapshot preserves exact data used for generation
- SHA256 hash ensures PDF integrity
- Indexed by (report_key, object_type, object_id)
- Ordered by creation date (newest first)

## First Template: Change Report v1

The `change.v1` template generates comprehensive change documentation:

### Features
- Multi-page support with automatic page breaks
- Header with project name on every page
- Footer with generation timestamp and page numbers
- Sections: Status, Timing, Description, Risk, Mitigation, Rollback, Communication
- Tables for related items and approvals
- Automatic table styling with alternating row colors

### Expected Context

```python
context = {
    'title': str,
    'project_name': str,
    'description': str,
    'status': str,
    'risk': str,
    'planned_start': str,
    'planned_end': str,
    'executed_at': str,
    'risk_description': str,
    'mitigation': str,
    'rollback_plan': str,
    'communication_plan': str,
    'created_by': str,
    'created_at': str,
    'items': [
        {'title': str, 'status': str},
        ...
    ],
    'approvals': [
        {'approver': str, 'status': str, 'decision_at': str},
        ...
    ]
}
```

## Testing

Comprehensive test suite with 18 tests covering:

### Test Coverage
- ✅ Template registry functionality
- ✅ PDF rendering (basic and multi-page)
- ✅ Report generation and storage
- ✅ Context snapshot persistence
- ✅ Metadata handling
- ✅ Header/footer rendering
- ✅ Model creation and ordering
- ✅ Error handling for invalid templates

### Running Tests

```bash
python manage.py test core.services.reporting.test_reporting
```

All 18 tests pass successfully.

## Demonstration

A demonstration script is provided: `demo_report_service.py`

```bash
python demo_report_service.py
```

This generates sample PDFs showing:
1. Basic change report (3 pages)
2. Multi-page report with 50 items (5 pages)
3. Template registry functionality

## Usage Examples

### Example 1: Generate Change Report

```python
from core.services.reporting import ReportService
from core.models import Change

service = ReportService()
change = Change.objects.get(id=123)

context = {
    'title': change.title,
    'project_name': change.project.name,
    'description': change.description,
    'status': change.get_status_display(),
    'risk': change.get_risk_display(),
    'created_by': change.created_by.name,
    'created_at': change.created_at.strftime('%Y-%m-%d %H:%M:%S'),
    # ... more fields
}

# Generate and store
report = service.generate_and_store(
    report_key='change.v1',
    object_type='change',
    object_id=change.id,
    context=context,
    created_by=request.user
)

# Access the PDF
pdf_url = report.pdf_file.url
```

### Example 2: Create New Report Template

```python
# 1. Create template class in reports/templates/invoice_v1.py
class InvoiceReportV1:
    def __init__(self):
        self.styles = get_report_styles()
    
    def build_story(self, context):
        story = []
        # Add invoice content
        return story
    
    def draw_header_footer(self, canvas, doc, context):
        # Custom header/footer
        pass

# 2. Register template in reports/__init__.py
from .templates.invoice_v1 import InvoiceReportV1

def register_all_templates():
    register_template('change.v1', ChangeReportV1)
    register_template('invoice.v1', InvoiceReportV1)  # Add this

# 3. Use it
service = ReportService()
pdf_bytes = service.render('invoice.v1', context)
```

## Project Structure

```
core/
  services/
    reporting/
      __init__.py         # Exports ReportService
      service.py          # Main service implementation
      registry.py         # Template registry
      styles.py           # PDF styles and table formatting
      canvas.py           # Header/footer helpers
      test_reporting.py   # Comprehensive tests

reports/
  __init__.py             # Auto-registers templates
  templates/
    __init__.py
    change_v1.py          # Change report template v1

core/models.py            # Contains ReportDocument model
```

## Dependencies

Added to `requirements.txt`:
```
reportlab>=4.0,<5.0
```

## Migrations

- `0026_alter_mailtemplate_message_and_more.py` - Created ReportDocument model
- `0027_alter_reportdocument_metadata_json.py` - Made metadata_json nullable

## Design Principles

### 1. Separation of Concerns
- **Service**: PDF rendering and storage logic
- **Registry**: Template resolution (no if/else)
- **Templates**: Business-specific report content

### 2. Extensibility
- Easy to add new report types
- Version templates independently
- No modification to core service needed

### 3. Audit Trail
- Context snapshot for reproducibility
- SHA256 hash for integrity verification
- Created by and timestamp tracking

### 4. Simplicity
- Synchronous operations (no queue complexity)
- Serializable contexts (no ORM dependencies)
- Clear interfaces and contracts

## Not in Scope

Following features are intentionally excluded:
- ❌ WYSIWYG editor
- ❌ HTML rendering
- ❌ Async/queue processing
- ❌ UI components
- ❌ Business logic (invoicing, VAT calculation, etc.)

## Future Extensions

The architecture supports easy extension to:
- Invoice reports (`invoice.v1`)
- Offer reports (`offer.v1`)
- Protocol reports (`protocol.v1`)
- Custom project reports

Simply create a new template class and register it.

## Acceptance Criteria

✅ Core Report Service is implemented  
✅ First report type (`change.v1`) generates PDFs  
✅ Multi-page reports work correctly  
✅ PDF contains header, footer, and page numbers  
✅ Context snapshot is persisted  
✅ Architecture is extensible  
✅ Comprehensive tests (18/18 passing)  
✅ Documentation provided  

## Summary

The Core Report Service provides a robust, extensible foundation for PDF report generation in Agira. It separates technical infrastructure from business logic, ensures audit compliance through context snapshots, and allows easy addition of new report types through a clean template registry pattern.
