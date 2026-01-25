from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    
    def ready(self):
        """Import signal handlers when the app is ready."""
        # Import Weaviate signals to register them
        try:
            import core.services.weaviate.signals  # noqa: F401
        except Exception:
            # Ignore errors during import (e.g., during migrations)
            pass

