#!/usr/bin/env python
"""
Demonstration of the Core Printing Framework

This script demonstrates how to use the Core Printing Framework to generate
PDF documents from HTML templates using WeasyPrint.

Note: Requires WeasyPrint system dependencies to be installed.
See PRINTING_FRAMEWORK_DOCUMENTATION.md for installation instructions.
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agira.settings')
django.setup()

from core.printing import PdfRenderService


def check_weasyprint():
    """Check if WeasyPrint is available and working"""
    try:
        from weasyprint import HTML
        # Try to render a simple test
        HTML(string='<h1>Test</h1>').write_pdf()
        return True
    except ImportError:
        print("✗ WeasyPrint is not installed")
        print("  Install with: pip install weasyprint")
        return False
    except (OSError, AttributeError) as e:
        print(f"✗ WeasyPrint system dependencies are not installed: {e}")
        print("  See PRINTING_FRAMEWORK_DOCUMENTATION.md for installation instructions")
        return False


def demo_basic_rendering():
    """Demonstrate basic PDF rendering from template"""
    print("\n=== Demo 1: Basic PDF Rendering ===")
    
    service = PdfRenderService()
    
    # Use the example template
    result = service.render(
        template_name='printing/example.html',
        context={},
        base_url='file://' + os.path.dirname(os.path.abspath(__file__)),
        filename='example.pdf'
    )
    
    print(f"✓ Generated PDF: {result.filename}")
    print(f"  Size: {len(result.pdf_bytes)} bytes")
    print(f"  Content-Type: {result.content_type}")
    
    # Save to file for inspection
    output_path = '/tmp/printing_framework_example.pdf'
    with open(output_path, 'wb') as f:
        f.write(result.pdf_bytes)
    print(f"✓ Saved to: {output_path}")
    
    return result


def demo_custom_context():
    """Demonstrate rendering with custom context data"""
    print("\n=== Demo 2: Custom Context Data ===")
    
    service = PdfRenderService()
    
    # Create a custom template in memory (normally would be in templates/)
    from django.template.loader import render_to_string
    
    context = {
        'document_title': 'Custom Report',
        'company_name': 'ACME Corporation',
        'report_date': '2026-02-08',
        'items': [
            {'name': 'Item A', 'quantity': 10, 'price': 99.99},
            {'name': 'Item B', 'quantity': 5, 'price': 149.99},
            {'name': 'Item C', 'quantity': 3, 'price': 299.99},
        ],
        'total': 10*99.99 + 5*149.99 + 3*299.99,
    }
    
    # For demo purposes, we'll just show the context
    print("Context prepared:")
    print(f"  Title: {context['document_title']}")
    print(f"  Company: {context['company_name']}")
    print(f"  Items: {len(context['items'])}")
    print(f"  Total: ${context['total']:.2f}")
    
    print("\nNote: In a real scenario, you would:")
    print("  1. Create a custom template extending printing/base.html")
    print("  2. Pass this context to service.render()")
    print("  3. Get back a PdfResult with the generated PDF")


def demo_template_features():
    """Demonstrate template features"""
    print("\n=== Demo 3: Template Features ===")
    
    print("\nAvailable template blocks:")
    print("  {% block title %} - Document title")
    print("  {% block header_content %} - Custom header")
    print("  {% block content %} - Main content (required)")
    print("  {% block footer_left %} - Left footer text")
    print("  {% block footer_center %} - Center footer text")
    print("  {% block footer_right %} - Right footer (page numbers)")
    
    print("\nCSS features from print.css:")
    print("  - @page rules for headers/footers")
    print("  - @page :first for different first page")
    print("  - Page counters (Page X of Y)")
    print("  - .keep-together - Avoid page breaks")
    print("  - .page-break-before/after - Force page breaks")
    print("  - Table headers repeat on each page")


def demo_error_handling():
    """Demonstrate error handling"""
    print("\n=== Demo 4: Error Handling ===")
    
    service = PdfRenderService()
    
    try:
        # Try to render a non-existent template
        result = service.render(
            template_name='printing/does_not_exist.html',
            context={},
            base_url='file://',
            filename='test.pdf'
        )
    except Exception as e:
        print(f"✓ Caught expected error: {type(e).__name__}")
        print(f"  Message: {str(e)[:80]}...")
    
    print("\nThe framework provides proper error handling:")
    print("  - Template not found")
    print("  - Rendering failures")
    print("  - Missing system dependencies")


def main():
    """Run all demonstrations"""
    print("=" * 70)
    print("Core Printing Framework - Demonstration")
    print("=" * 70)
    
    # Check WeasyPrint availability
    print("\nChecking WeasyPrint availability...")
    weasyprint_ok = check_weasyprint()
    
    if not weasyprint_ok:
        print("\n✗ Cannot run full demonstrations without WeasyPrint")
        print("  Some demos will be limited to showing the API")
    
    print("\n" + "=" * 70)
    
    try:
        # Run demonstrations
        if weasyprint_ok:
            demo_basic_rendering()
        else:
            print("\n=== Demo 1: Basic PDF Rendering ===")
            print("Skipped - WeasyPrint not available")
        
        demo_custom_context()
        demo_template_features()
        demo_error_handling()
        
        print("\n" + "=" * 70)
        print("✓ Demonstrations completed!")
        print("=" * 70)
        
        if weasyprint_ok:
            print("\nGenerated PDFs:")
            print("  - /tmp/printing_framework_example.pdf")
            print("\nYou can open these files to inspect the generated reports.")
        else:
            print("\nTo generate actual PDFs, install WeasyPrint system dependencies.")
            print("See: PRINTING_FRAMEWORK_DOCUMENTATION.md")
        
    except Exception as e:
        print(f"\n✗ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
