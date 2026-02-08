"""
Tests for Core Printing Framework

Tests the printing framework components:
- PDF rendering service
- WeasyPrint renderer
- Base templates
- Print CSS integration
"""

from django.test import TestCase
from django.template.loader import render_to_string
from django.conf import settings
from pathlib import Path
import os

from core.printing import PdfRenderService, PdfResult
from core.printing.weasyprint_renderer import WeasyPrintRenderer, WEASYPRINT_AVAILABLE
from core.printing.interfaces import IPdfRenderer
from core.printing.sanitizer import sanitize_html


class PdfRenderServiceTestCase(TestCase):
    """Test cases for PdfRenderService"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.service = PdfRenderService()
        self.base_url = 'file://' + str(settings.STATIC_ROOT)
    
    def test_service_initialization(self):
        """Test that service initializes with default renderer"""
        self.assertIsNotNone(self.service.renderer)
        self.assertIsInstance(self.service.renderer, IPdfRenderer)
    
    def test_service_with_custom_renderer(self):
        """Test service with custom renderer"""
        if WEASYPRINT_AVAILABLE:
            custom_renderer = WeasyPrintRenderer()
            service = PdfRenderService(renderer=custom_renderer)
            self.assertEqual(service.renderer, custom_renderer)
    
    def test_render_returns_pdf_result(self):
        """Test that render returns a PdfResult object"""
        if not WEASYPRINT_AVAILABLE:
            self.skipTest("WeasyPrint not available")
        
        # Create a simple test template
        template_path = 'printing/test_simple.html'
        
        # Create the test template if it doesn't exist
        self._create_test_template(template_path, """
            {% extends "printing/base.html" %}
            {% block content %}
            <h1>Test Document</h1>
            <p>This is a test document for the printing framework.</p>
            {% endblock %}
        """)
        
        context = {'title': 'Test'}
        
        result = self.service.render(
            template_name=template_path,
            context=context,
            base_url=self.base_url,
            filename='test.pdf'
        )
        
        self.assertIsInstance(result, PdfResult)
        self.assertEqual(result.filename, 'test.pdf')
        self.assertEqual(result.content_type, 'application/pdf')
        self.assertIsInstance(result.pdf_bytes, bytes)
        self.assertGreater(len(result.pdf_bytes), 0)
    
    def test_render_with_default_filename(self):
        """Test that default filename is used if not provided"""
        if not WEASYPRINT_AVAILABLE:
            self.skipTest("WeasyPrint not available")
        
        template_path = 'printing/test_simple.html'
        self._create_test_template(template_path, """
            {% extends "printing/base.html" %}
            {% block content %}<p>Test</p>{% endblock %}
        """)
        
        result = self.service.render(
            template_name=template_path,
            context={},
            base_url=self.base_url
        )
        
        self.assertEqual(result.filename, 'document.pdf')
    
    def _create_test_template(self, template_path, content):
        """Helper to create a test template"""
        # Find the template directory
        template_dir = settings.BASE_DIR / 'core' / 'templates'
        template_file = template_dir / template_path
        
        # Create directory if it doesn't exist
        template_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Write template content
        with open(template_file, 'w') as f:
            f.write(content)


class WeasyPrintRendererTestCase(TestCase):
    """Test cases for WeasyPrint renderer"""
    
    def test_renderer_initialization(self):
        """Test renderer can be initialized"""
        if not WEASYPRINT_AVAILABLE:
            self.skipTest("WeasyPrint not available")
        
        renderer = WeasyPrintRenderer()
        self.assertIsInstance(renderer, WeasyPrintRenderer)
        self.assertIsInstance(renderer, IPdfRenderer)
    
    def test_render_simple_html(self):
        """Test rendering simple HTML to PDF"""
        if not WEASYPRINT_AVAILABLE:
            self.skipTest("WeasyPrint not available")
        
        renderer = WeasyPrintRenderer()
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Test</title></head>
        <body>
            <h1>Test Document</h1>
            <p>This is a test paragraph.</p>
        </body>
        </html>
        """
        
        pdf_bytes = renderer.render_html_to_pdf(html, base_url='')
        
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 0)
        # PDF files start with %PDF
        self.assertTrue(pdf_bytes.startswith(b'%PDF'))
    
    def test_render_with_css(self):
        """Test rendering HTML with CSS"""
        if not WEASYPRINT_AVAILABLE:
            self.skipTest("WeasyPrint not available")
        
        renderer = WeasyPrintRenderer()
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Test with CSS</title>
            <style>
                body { font-family: Arial; }
                h1 { color: #333; }
            </style>
        </head>
        <body>
            <h1>Styled Document</h1>
            <p>This document has CSS styling.</p>
        </body>
        </html>
        """
        
        pdf_bytes = renderer.render_html_to_pdf(html, base_url='')
        
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 0)


class PdfResultTestCase(TestCase):
    """Test cases for PdfResult DTO"""
    
    def test_pdf_result_creation(self):
        """Test creating a PdfResult"""
        pdf_bytes = b'%PDF-1.4...'
        result = PdfResult(
            pdf_bytes=pdf_bytes,
            filename='test.pdf'
        )
        
        self.assertEqual(result.pdf_bytes, pdf_bytes)
        self.assertEqual(result.filename, 'test.pdf')
        self.assertEqual(result.content_type, 'application/pdf')
    
    def test_pdf_result_length(self):
        """Test __len__ returns byte count"""
        pdf_bytes = b'%PDF-1.4...'
        result = PdfResult(
            pdf_bytes=pdf_bytes,
            filename='test.pdf'
        )
        
        self.assertEqual(len(result), len(pdf_bytes))


class HtmlSanitizerTestCase(TestCase):
    """Test cases for HTML sanitizer"""
    
    def test_sanitize_allows_safe_tags(self):
        """Test that safe tags are allowed"""
        html = '<p>Safe <strong>content</strong></p>'
        sanitized = sanitize_html(html)
        
        self.assertIn('<p>', sanitized)
        self.assertIn('<strong>', sanitized)
    
    def test_sanitize_removes_script_tags(self):
        """Test that script tags are removed"""
        html = '<p>Safe</p><script>alert("xss")</script>'
        sanitized = sanitize_html(html)
        
        self.assertIn('<p>', sanitized)
        self.assertNotIn('<script>', sanitized)
        self.assertNotIn('alert', sanitized)
    
    def test_sanitize_strict_mode(self):
        """Test strict mode removes inline styles"""
        html = '<p style="color: red;">Styled text</p>'
        sanitized = sanitize_html(html, strict=True)
        
        # In strict mode, style attribute should be removed
        self.assertNotIn('style=', sanitized)


class PrintingFrameworkSmokeTestCase(TestCase):
    """
    Smoke tests for the complete printing framework.
    
    These tests verify that the framework can generate actual PDFs
    from templates with the expected features.
    """
    
    def test_smoke_simple_document(self):
        """Smoke test: Generate a simple PDF document"""
        if not WEASYPRINT_AVAILABLE:
            self.skipTest("WeasyPrint not available")
        
        service = PdfRenderService()
        
        # Create a test template
        template_path = 'printing/test_smoke.html'
        template_content = """
        {% extends "printing/base.html" %}
        
        {% block title %}Smoke Test Document{% endblock %}
        
        {% block content %}
        <h1>Printing Framework Smoke Test</h1>
        
        <div class="section">
            <h2>Overview</h2>
            <p>This is a smoke test document to verify that the printing framework works correctly.</p>
        </div>
        
        <div class="section">
            <h2>Features Tested</h2>
            <ul>
                <li>HTML to PDF conversion</li>
                <li>Template inheritance</li>
                <li>CSS styling</li>
                <li>Page headers and footers</li>
                <li>Page numbers</li>
            </ul>
        </div>
        
        <table>
            <thead>
                <tr>
                    <th>Item</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td>Framework setup</td>
                    <td>✓ Complete</td>
                </tr>
                <tr>
                    <td>Template rendering</td>
                    <td>✓ Working</td>
                </tr>
            </tbody>
        </table>
        {% endblock %}
        """
        
        # Create the test template
        template_dir = settings.BASE_DIR / 'core' / 'templates'
        template_file = template_dir / template_path
        template_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(template_file, 'w') as f:
            f.write(template_content)
        
        # Render PDF
        base_url = 'file://' + str(settings.BASE_DIR)
        result = service.render(
            template_name=template_path,
            context={'test': True},
            base_url=base_url,
            filename='smoke_test.pdf'
        )
        
        # Verify result
        self.assertIsInstance(result, PdfResult)
        self.assertEqual(result.filename, 'smoke_test.pdf')
        self.assertGreater(len(result.pdf_bytes), 0)
        self.assertTrue(result.pdf_bytes.startswith(b'%PDF'))
        
        # Save to file for manual inspection if needed
        output_path = '/tmp/smoke_test.pdf'
        with open(output_path, 'wb') as f:
            f.write(result.pdf_bytes)
        
        # Verify file was created
        self.assertTrue(os.path.exists(output_path))
        
        # Clean up test template
        if template_file.exists():
            template_file.unlink()
    
    def test_smoke_multi_page_document(self):
        """Smoke test: Generate a multi-page PDF with headers/footers"""
        if not WEASYPRINT_AVAILABLE:
            self.skipTest("WeasyPrint not available")
        
        service = PdfRenderService()
        
        # Create a test template with enough content for multiple pages
        template_path = 'printing/test_multipage.html'
        template_content = """
        {% extends "printing/base.html" %}
        
        {% block title %}Multi-Page Test{% endblock %}
        
        {% block footer_left %}
        Printing Framework Test
        {% endblock %}
        
        {% block content %}
        <h1>Multi-Page Document Test</h1>
        
        {% for i in items %}
        <div class="section keep-together">
            <h2>Section {{ i }}</h2>
            <p>This is section {{ i }} of the multi-page document. It contains enough content to test pagination, headers, and footers across multiple pages.</p>
            <p>Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.</p>
            <ul>
                <li>Item 1 for section {{ i }}</li>
                <li>Item 2 for section {{ i }}</li>
                <li>Item 3 for section {{ i }}</li>
            </ul>
        </div>
        {% endfor %}
        {% endblock %}
        """
        
        # Create the test template
        template_dir = settings.BASE_DIR / 'core' / 'templates'
        template_file = template_dir / template_path
        template_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(template_file, 'w') as f:
            f.write(template_content)
        
        # Render PDF with many sections to force multiple pages
        base_url = 'file://' + str(settings.BASE_DIR)
        result = service.render(
            template_name=template_path,
            context={'items': range(1, 20)},  # 19 sections should create multiple pages
            base_url=base_url,
            filename='multipage_test.pdf'
        )
        
        # Verify result
        self.assertIsInstance(result, PdfResult)
        self.assertGreater(len(result.pdf_bytes), 0)
        self.assertTrue(result.pdf_bytes.startswith(b'%PDF'))
        
        # Save to file
        output_path = '/tmp/multipage_test.pdf'
        with open(output_path, 'wb') as f:
            f.write(result.pdf_bytes)
        
        self.assertTrue(os.path.exists(output_path))
        
        # Clean up
        if template_file.exists():
            template_file.unlink()
