# Printing Framework - Technical Documentation

## Overview

The Core Printing Framework provides centralized, modular PDF generation from HTML templates using WeasyPrint. It supports paged media features including:

- **Running headers and footers** on each page
- **Different layout for first page** (e.g., letterhead)
- **Page numbers** (Page X of Y)
- **Print-optimized CSS** with `@page` rules
- **Template inheritance** via Django templates

## Architecture

### Components

1. **Interfaces** (`core/printing/interfaces.py`)
   - `IPdfRenderer`: Abstract interface for PDF rendering engines
   - `IContextBuilder`: Placeholder for future context builders (optional)

2. **Renderer** (`core/printing/weasyprint_renderer.py`)
   - `WeasyPrintRenderer`: Implementation of `IPdfRenderer` using WeasyPrint
   - Supports static assets via `base_url`
   - Can include custom CSS files

3. **Service** (`core/printing/service.py`)
   - `PdfRenderService`: Core rendering pipeline
   - Loads Django templates
   - Converts HTML to PDF
   - Returns structured `PdfResult`

4. **DTO** (`core/printing/dto.py`)
   - `PdfResult`: Data transfer object with `pdf_bytes`, `filename`, and `content_type`

5. **Sanitizer** (`core/printing/sanitizer.py`) - Optional
   - `sanitize_html()`: Defense-in-depth HTML sanitization
   - Note: Quill HTML is already sanitized on save

6. **Templates** (`core/templates/printing/`)
   - `base.html`: Base template with header/footer blocks

7. **CSS** (`core/static/printing/`)
   - `print.css`: Paged media CSS with `@page` rules, counters, and print styles

## Usage

### Basic Usage

```python
from core.printing import PdfRenderService

# Initialize service
service = PdfRenderService()

# Render a PDF from template
result = service.render(
    template_name='printing/invoice.html',
    context={
        'invoice_number': 'INV-001',
        'customer': 'ACME Corp',
        'items': [...],
    },
    base_url='http://example.com',  # For static assets
    filename='invoice_001.pdf'
)

# Use the result
pdf_bytes = result.pdf_bytes
filename = result.filename
content_type = result.content_type  # 'application/pdf'
```

### Creating a Custom Template

Templates should extend `printing/base.html`:

```html
{% extends "printing/base.html" %}

{% block title %}Invoice {{ invoice_number }}{% endblock %}

{% block header_content %}
<div style="display: flex; justify-content: space-between;">
    <div>
        <strong>Your Company Name</strong><br>
        Address Line 1<br>
        City, Country
    </div>
    <div>
        <strong>Invoice</strong><br>
        {{ invoice_number }}
    </div>
</div>
{% endblock %}

{% block content %}
<h1>Invoice</h1>

<div class="section">
    <h2>Customer Information</h2>
    <p><strong>{{ customer.name }}</strong></p>
    <p>{{ customer.address }}</p>
</div>

<table>
    <thead>
        <tr>
            <th>Item</th>
            <th>Quantity</th>
            <th>Price</th>
            <th>Total</th>
        </tr>
    </thead>
    <tbody>
        {% for item in items %}
        <tr>
            <td>{{ item.description }}</td>
            <td>{{ item.quantity }}</td>
            <td>{{ item.price }}</td>
            <td>{{ item.total }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
{% endblock %}

{% block footer_left %}
Your Company • www.example.com
{% endblock %}
```

### Template Blocks

The base template provides these blocks:

- `{% block title %}` - Document title
- `{% block header %}` - Full header (override completely)
- `{% block header_content %}` - Header content (keeps default structure)
- `{% block content %}` - Main content area (**required**)
- `{% block footer %}` - Full footer (override completely)
- `{% block footer_left %}` - Left footer content
- `{% block footer_center %}` - Center footer content
- `{% block footer_right %}` - Right footer content (page numbers by default)
- `{% block extra_css %}` - Additional CSS files
- `{% block inline_styles %}` - Inline CSS

### Page Breaks and Print Helpers

The print.css provides utility classes:

```html
<!-- Keep element together on one page -->
<div class="keep-together">
    <h2>Important Section</h2>
    <p>This section won't be split across pages.</p>
</div>

<!-- Force page break before element -->
<div class="page-break-before">
    <h1>New Chapter</h1>
</div>

<!-- Force page break after element -->
<div class="page-break-after">
    <p>End of section</p>
</div>

<!-- Avoid page break before/after -->
<h2 class="avoid-break-after">Section Title</h2>
<p>Content that should stay with title...</p>
```

### Custom Page Layout

For a custom first page (e.g., letterhead):

```html
{% extends "printing/base.html" %}

{% block inline_styles %}
@page :first {
    margin-top: 5cm; /* Space for letterhead */
}
{% endblock %}

{% block header_content %}
<!-- Only shown on first page -->
<div class="header-first">
    <img src="{{ logo_url }}" alt="Company Logo" style="height: 2cm;">
</div>
{% endblock %}
```

## WeasyPrint Installation

### Python Package

```bash
pip install weasyprint>=62.0
```

### System Dependencies

**IMPORTANT**: WeasyPrint requires system libraries to be installed. Without these, PDF generation will fail with errors like `'super' object has no attribute 'transform'` or similar.

**Ubuntu/Debian:**
```bash
sudo apt-get update
sudo apt-get install -y \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation
```

**Alpine Linux (for Docker):**
```bash
apk add --no-cache \
    cairo \
    pango \
    gdk-pixbuf \
    libffi-dev \
    shared-mime-info \
    ttf-liberation
```

**macOS:**
```bash
brew install cairo pango gdk-pixbuf libffi
```

**Docker Example:**
```dockerfile
FROM python:3.12-slim

# Install WeasyPrint system dependencies
RUN apt-get update && apt-get install -y \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
```

**Verification:**

Test that WeasyPrint works correctly:

```bash
python -c "from weasyprint import HTML; HTML(string='<h1>Test</h1>').write_pdf('/tmp/test.pdf'); print('✓ WeasyPrint working')"
```

If you see errors about missing libraries, the system dependencies are not properly installed.

## Configuration

Future enhancement - configure renderer in settings:

```python
# settings.py
PDF_RENDERER = 'weasyprint'  # or 'reportlab', 'custom'
```

## Extending the Framework

### Custom Renderer

Implement `IPdfRenderer`:

```python
from core.printing.interfaces import IPdfRenderer

class CustomPdfRenderer(IPdfRenderer):
    def render_html_to_pdf(self, html: str, base_url: str) -> bytes:
        # Your implementation
        return pdf_bytes

# Use it
from core.printing import PdfRenderService

service = PdfRenderService(renderer=CustomPdfRenderer())
```

### Context Builder

For module-specific templates:

```python
from core.printing.interfaces import IContextBuilder

class InvoiceContextBuilder(IContextBuilder):
    def build_context(self, invoice, *, company=None):
        return {
            'invoice_number': invoice.number,
            'customer': invoice.customer,
            'items': invoice.items.all(),
            'company': company,
        }
    
    def get_template_name(self, invoice):
        return 'printing/invoice.html'

# Use it
builder = InvoiceContextBuilder()
context = builder.build_context(invoice, company=my_company)
template = builder.get_template_name(invoice)

result = service.render(
    template_name=template,
    context=context,
    base_url='...',
    filename=f'invoice_{invoice.number}.pdf'
)
```

## Testing

Run the smoke tests:

```bash
python manage.py test core.test_printing_framework
```

The smoke tests generate actual PDFs in `/tmp/` for manual inspection:
- `/tmp/smoke_test.pdf` - Basic single-page document
- `/tmp/multipage_test.pdf` - Multi-page document with headers/footers

## Security

### HTML Sanitization

The framework provides optional HTML sanitization via `sanitizer.py`:

```python
from core.printing.sanitizer import sanitize_html

clean_html = sanitize_html(user_html)
clean_html_strict = sanitize_html(user_html, strict=True)
```

**Note**: Quill HTML fields are already sanitized on save. The sanitizer provides defense-in-depth.

### Best Practices

1. **Never trust user input** - Always sanitize HTML from user input
2. **Use base_url carefully** - Ensure it points to trusted static files
3. **Validate file sizes** - Large HTML can produce large PDFs
4. **Resource limits** - Consider timeouts for PDF generation

## Examples

### Django View Example

```python
from django.http import HttpResponse
from core.printing import PdfRenderService

def invoice_pdf_view(request, invoice_id):
    invoice = get_object_or_404(Invoice, pk=invoice_id)
    
    service = PdfRenderService()
    result = service.render(
        template_name='printing/invoice.html',
        context={'invoice': invoice},
        base_url=request.build_absolute_uri('/'),
        filename=f'invoice_{invoice.number}.pdf'
    )
    
    response = HttpResponse(
        result.pdf_bytes,
        content_type=result.content_type
    )
    response['Content-Disposition'] = f'inline; filename="{result.filename}"'
    
    return response
```

### Async/Background Example

```python
from celery import shared_task
from core.printing import PdfRenderService

@shared_task
def generate_invoice_pdf(invoice_id):
    invoice = Invoice.objects.get(pk=invoice_id)
    
    service = PdfRenderService()
    result = service.render(
        template_name='printing/invoice.html',
        context={'invoice': invoice},
        base_url='http://example.com',
        filename=f'invoice_{invoice.number}.pdf'
    )
    
    # Save to storage
    invoice.pdf_file.save(
        result.filename,
        ContentFile(result.pdf_bytes),
        save=True
    )
```

## Future Enhancements

Possible future improvements:

1. **Renderer Factory** - Registry pattern for multiple renderers
2. **Template Registry** - Similar to existing report service
3. **Attachment Integration** - Auto-save PDFs as attachments
4. **Watermarks** - Support for draft/confidential watermarks
5. **Digital Signatures** - PDF signing support
6. **Batch Generation** - Optimize for bulk PDF creation
7. **Font Management** - Custom font loading
8. **Localization** - Multi-language support in templates

## Support

For issues or questions:
- Check the test suite for examples
- Review WeasyPrint documentation: https://weasyprint.org/
- See Django template documentation for template inheritance
