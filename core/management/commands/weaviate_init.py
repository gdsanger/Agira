"""
Django management command to initialize Weaviate schema.

This command ensures the AgiraObject collection exists in Weaviate
with the correct schema for v1.
"""

from django.core.management.base import BaseCommand, CommandError

from core.services.exceptions import ServiceDisabled, ServiceNotConfigured
from core.services.weaviate import ensure_schema, is_available


class Command(BaseCommand):
    help = 'Initialize Weaviate schema (create AgiraObject collection)'

    def handle(self, *args, **options):
        """Execute the command."""
        self.stdout.write("Initializing Weaviate schema...")
        
        # Check if Weaviate is available
        if not is_available():
            raise CommandError(
                "Weaviate is not configured or not enabled. "
                "Please configure Weaviate in Django admin first."
            )
        
        try:
            # Ensure schema exists
            ensure_schema()
            
            self.stdout.write(
                self.style.SUCCESS(
                    "✓ Weaviate schema initialized successfully. "
                    "AgiraObject collection is ready."
                )
            )
            
        except ServiceDisabled as e:
            raise CommandError(f"Weaviate service is disabled: {e}")
        except ServiceNotConfigured as e:
            raise CommandError(f"Weaviate service is not properly configured: {e}")
        except Exception as e:
            raise CommandError(f"Failed to initialize Weaviate schema: {e}")
