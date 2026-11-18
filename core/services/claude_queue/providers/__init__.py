"""Agent providers behind the queue worker (see ``base.AgentProvider``)."""

from core.services.claude_queue.providers.base import AgentProvider
from core.services.claude_queue.providers.claude import ClaudeProvider

DEFAULT_PROVIDER = 'claude'

PROVIDERS = {
    ClaudeProvider.name: ClaudeProvider,
}


def get_provider(name=DEFAULT_PROVIDER):
    """Return a provider instance for ``name``; unknown names raise ``ValueError``."""
    try:
        return PROVIDERS[name or DEFAULT_PROVIDER]()
    except KeyError:
        raise ValueError(f"Unbekannter Provider {name!r}") from None


__all__ = ['AgentProvider', 'ClaudeProvider', 'DEFAULT_PROVIDER', 'PROVIDERS', 'get_provider']
