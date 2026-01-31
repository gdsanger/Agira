#!/usr/bin/env python
"""
Demonstration of the Core Report Service

This script demonstrates how to use the Core Report Service to generate
PDF reports with versioning and context snapshots.
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agira.settings')
django.setup()

# Import reports to register templates
import reports

from core.services.reporting import ReportService
from core.models import Project, Change, ChangeStatus, RiskLevel, User, ReportDocument
from datetime import datetime


def demo_basic_rendering():
    """Demonstrate basic PDF rendering without persistence"""
    print("\n=== Demo 1: Basic PDF Rendering ===")
    
    service = ReportService()
    
    # Create context data
    context = {
        'title': 'Demo Change: Database Migration',
        'project_name': 'Demo Project',
        'description': 'Migrate database from MySQL to PostgreSQL',
        'status': 'Planned',
        'risk': 'High',
        'planned_start': '2024-02-01 10:00:00',
        'planned_end': '2024-02-01 18:00:00',
        'executed_at': 'N/A',
        'risk_description': 'Database migration requires downtime and data validation',
        'mitigation': 'Complete backup before migration, test in staging environment',
        'rollback_plan': 'Restore from backup if migration fails',
        'communication_plan': 'Notify all users 24 hours in advance',
        'created_by': 'Demo User',
        'created_at': '2024-01-15 14:30:00',
        'items': [
            {'title': 'Backup current database', 'status': 'Completed'},
            {'title': 'Set up PostgreSQL server', 'status': 'Completed'},
            {'title': 'Run migration scripts', 'status': 'Pending'},
            {'title': 'Validate data integrity', 'status': 'Pending'},
            {'title': 'Update application config', 'status': 'Pending'},
        ],
        'approvals': [
            {'approver': 'Tech Lead', 'status': 'Approved', 'decision_at': '2024-01-20'},
            {'approver': 'CTO', 'status': 'Pending', 'decision_at': 'N/A'},
        ]
    }
    
    # Render PDF
    pdf_bytes = service.render('change.v1', context)
    
    print(f"✓ Generated PDF: {len(pdf_bytes)} bytes")
    print(f"  PDF starts with: {pdf_bytes[:10]}")
    
    # Save to file for inspection
    output_path = '/tmp/demo_change_report.pdf'
    with open(output_path, 'wb') as f:
        f.write(pdf_bytes)
    print(f"✓ Saved to: {output_path}")
    
    return pdf_bytes


def demo_generate_and_store():
    """Demonstrate generating and storing a report with database models"""
    print("\n=== Demo 2: Generate and Store with Database ===")
    
    service = ReportService()
    
    # Note: This demo shows the API but won't actually save without a database
    # In a real scenario, you would have actual Change and User objects
    
    context = {
        'title': 'Security Patch Deployment',
        'project_name': 'Production Infrastructure',
        'description': 'Deploy critical security patches to all production servers',
        'status': 'In Progress',
        'risk': 'Normal',
        'planned_start': '2024-02-05 02:00:00',
        'planned_end': '2024-02-05 04:00:00',
        'created_by': 'DevOps Team',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    
    print("Context prepared:")
    print(f"  Title: {context['title']}")
    print(f"  Status: {context['status']}")
    print(f"  Risk: {context['risk']}")
    
    print("\nNote: Would call service.generate_and_store() with:")
    print("  - report_key='change.v1'")
    print("  - object_type='change'")
    print("  - object_id=<change_id>")
    print("  - context=<context>")
    print("  - created_by=<user>")
    
    # Would return a ReportDocument instance with:
    # - PDF file saved to storage
    # - Context snapshot in JSON
    # - SHA256 hash for integrity
    
    return context


def demo_multi_page_report():
    """Demonstrate multi-page report generation"""
    print("\n=== Demo 3: Multi-Page Report ===")
    
    service = ReportService()
    
    # Create context with many items to trigger multiple pages
    context = {
        'title': 'Major System Upgrade',
        'project_name': 'Enterprise System',
        'description': 'Comprehensive system upgrade affecting all modules',
        'status': 'Planned',
        'risk': 'Very High',
        'created_by': 'Project Manager',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'items': [
            {'title': f'Upgrade task #{i}', 'status': 'Pending'} 
            for i in range(1, 51)
        ]
    }
    
    pdf_bytes = service.render('change.v1', context)
    
    print(f"✓ Generated multi-page PDF: {len(pdf_bytes)} bytes")
    print(f"  With {len(context['items'])} items")
    
    # Save to file
    output_path = '/tmp/demo_multipage_report.pdf'
    with open(output_path, 'wb') as f:
        f.write(pdf_bytes)
    print(f"✓ Saved to: {output_path}")
    
    return pdf_bytes


def demo_template_registry():
    """Demonstrate template registry functionality"""
    print("\n=== Demo 4: Template Registry ===")
    
    from core.services.reporting.registry import list_templates, is_registered
    
    # List all registered templates
    templates = list_templates()
    print(f"✓ Registered templates: {templates}")
    
    # Check if a template is registered
    print(f"✓ 'change.v1' registered: {is_registered('change.v1')}")
    print(f"✓ 'invoice.v1' registered: {is_registered('invoice.v1')}")
    
    print("\nTemplate registry allows easy extension:")
    print("  - Register new report types")
    print("  - Version templates independently")
    print("  - No if/else logic in service")


def main():
    """Run all demonstrations"""
    print("=" * 60)
    print("Core Report Service - Demonstration")
    print("=" * 60)
    
    try:
        # Run demonstrations
        demo_basic_rendering()
        demo_generate_and_store()
        demo_multi_page_report()
        demo_template_registry()
        
        print("\n" + "=" * 60)
        print("✓ All demonstrations completed successfully!")
        print("=" * 60)
        print("\nGenerated PDFs:")
        print("  - /tmp/demo_change_report.pdf")
        print("  - /tmp/demo_multipage_report.pdf")
        print("\nYou can open these files to inspect the generated reports.")
        
    except Exception as e:
        print(f"\n✗ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
