#!/usr/bin/env python
"""
Manual validation script for email ingestion functionality.

This script demonstrates the email ingestion system by showing:
1. Configuration validation
2. Service initialization
3. Sample email processing
"""

import os
import sys
import django

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'agira.settings')
django.setup()

from core.models import GraphAPIConfiguration, Organisation, Project, ItemType
from core.services.graph.email_ingestion_service import EmailIngestionService
from core.services.exceptions import ServiceDisabled, ServiceNotConfigured


def check_configuration():
    """Check if Graph API is properly configured."""
    print("=" * 60)
    print("1. Configuration Check")
    print("=" * 60)
    
    try:
        config = GraphAPIConfiguration.objects.get(pk=1)
        print(f"✓ Graph API Configuration found")
        print(f"  - Enabled: {config.enabled}")
        print(f"  - Tenant ID: {'***' if config.tenant_id else 'NOT SET'}")
        print(f"  - Client ID: {'***' if config.client_id else 'NOT SET'}")
        print(f"  - Client Secret: {'***' if config.client_secret else 'NOT SET'}")
        print(f"  - Default Mail Sender: {config.default_mail_sender or 'NOT SET'}")
        
        if not config.enabled:
            print("\n⚠ Graph API is not enabled!")
            return False
            
        if not config.default_mail_sender:
            print("\n⚠ Default mail sender is not configured!")
            return False
            
        print("\n✓ Configuration is valid")
        return True
        
    except GraphAPIConfiguration.DoesNotExist:
        print("✗ Graph API Configuration not found")
        return False


def check_organizations():
    """Check configured organizations."""
    print("\n" + "=" * 60)
    print("2. Organization Check")
    print("=" * 60)
    
    orgs = Organisation.objects.all()
    print(f"Found {orgs.count()} organization(s):")
    
    for org in orgs:
        domains = org.get_mail_domains_list()
        print(f"\n  {org.name}")
        if domains:
            print(f"    Domains: {', '.join(domains)}")
        else:
            print(f"    Domains: (none configured)")
    
    return orgs.count() > 0


def check_projects():
    """Check available projects."""
    print("\n" + "=" * 60)
    print("3. Project Check")
    print("=" * 60)
    
    projects = Project.objects.all()
    print(f"Found {projects.count()} project(s):")
    
    for project in projects:
        print(f"  - {project.name}")
    
    # Check for Incoming project
    incoming = Project.objects.filter(name="Incoming").first()
    if incoming:
        print(f"\n✓ Fallback project 'Incoming' exists")
    else:
        print(f"\n⚠ Fallback project 'Incoming' will be created automatically")
    
    return True


def check_item_types():
    """Check available item types."""
    print("\n" + "=" * 60)
    print("4. Item Type Check")
    print("=" * 60)
    
    types = ItemType.objects.filter(is_active=True)
    print(f"Found {types.count()} active item type(s):")
    
    for item_type in types:
        print(f"  - {item_type.key}: {item_type.name}")
    
    # Check for required types
    required = ['task', 'bug', 'feature', 'idea']
    missing = []
    for key in required:
        if not types.filter(key=key).exists():
            missing.append(key)
    
    if missing:
        print(f"\n⚠ Missing item types (will be auto-created): {', '.join(missing)}")
    else:
        print(f"\n✓ All required item types exist")
    
    return True


def test_service_initialization():
    """Test service initialization."""
    print("\n" + "=" * 60)
    print("5. Service Initialization Test")
    print("=" * 60)
    
    try:
        service = EmailIngestionService()
        print(f"✓ EmailIngestionService initialized successfully")
        print(f"  - Mailbox: {service.mailbox}")
        print(f"  - Processed category: {service.PROCESSED_CATEGORY}")
        print(f"  - Fallback project: {service.FALLBACK_PROJECT_NAME}")
        return True
        
    except ServiceDisabled as e:
        print(f"✗ Service is disabled: {e}")
        return False
        
    except ServiceNotConfigured as e:
        print(f"✗ Service is not configured: {e}")
        return False
        
    except Exception as e:
        print(f"✗ Unexpected error: {e}")
        return False


def main():
    """Run validation checks."""
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 10 + "Email Ingestion System Validation" + " " * 14 + "║")
    print("╚" + "=" * 58 + "╝")
    
    checks = [
        ("Configuration", check_configuration),
        ("Organizations", check_organizations),
        ("Projects", check_projects),
        ("Item Types", check_item_types),
        ("Service", test_service_initialization),
    ]
    
    results = {}
    for name, check_func in checks:
        try:
            results[name] = check_func()
        except Exception as e:
            print(f"\n✗ Error in {name} check: {e}")
            results[name] = False
    
    # Summary
    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    
    passed = sum(1 for r in results.values() if r)
    total = len(results)
    
    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{name:20s}: {status}")
    
    print(f"\nTotal: {passed}/{total} checks passed")
    
    if passed == total:
        print("\n✓ All checks passed! System is ready to process emails.")
        print("\nTo process emails, run:")
        print("  python manage.py email_ingestion_worker")
    else:
        print("\n⚠ Some checks failed. Please review the configuration.")
    
    print()


if __name__ == '__main__':
    main()
