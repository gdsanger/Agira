"""Per-user Claude credentials for queue jobs (#1083).

Generalises the single-account setup of #1078 to a team: every user stores
their own Claude credentials in their profile (subscription OAuth token and/or
pay-per-use API key), each issue carries the auth mode to run in, and the
worker injects exactly the matching credential of exactly one user into the
child environment of each run.

Two questions are answered here, and only here:

1. **Whose credential does a job use?** — :func:`resolve_credential_user`.
2. **Which secret goes into the child env, and where did it come from?** —
   :func:`resolve_claude_credential`.

Both answers are deliberately mode-strict: a subscription run never reaches for
an API key. The CLI prefers ``ANTHROPIC_API_KEY`` whenever it sees one, so a
silent cross-mode fallback would turn a "free" subscription run into a billed
one without anybody deciding that.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from django.conf import settings

from core.models import ClaudeCredentialSource, ClaudeQueueJobAuthMode, User

# Environment variable the CLI reads per auth mode. Auth is env-based, not
# flag-based — which is also the safer channel: argv is world-readable via `ps`.
AUTH_MODE_ENV_VARS = {
    ClaudeQueueJobAuthMode.OAUTH: 'CLAUDE_CODE_OAUTH_TOKEN',
    ClaudeQueueJobAuthMode.API_KEY: 'ANTHROPIC_API_KEY',
}

# Both auth-carrying variables. Stripped from every child environment before
# the matching one is set, so nothing inherited can decide the auth for us.
ALL_AUTH_ENV_VARS = tuple(AUTH_MODE_ENV_VARS.values())

AUTH_MODE_LABELS = {
    ClaudeQueueJobAuthMode.OAUTH: 'ABO (Claude-Abo / OAuth)',
    ClaudeQueueJobAuthMode.API_KEY: 'API (Anthropic API-Key)',
}


class MissingClaudeCredential(RuntimeError):
    """No usable credential for the requested auth mode.

    A ``RuntimeError`` subclass so the worker's existing "any launch failure is
    a job failure" handling still applies if this ever escapes a narrower
    ``except``. The message is user-facing: it names the user, the mode and the
    way out.
    """


@dataclass(frozen=True)
class ClaudeCredential:
    """The resolved credential for one run."""

    auth_mode: str
    env_var: str
    #: Secret to place in the child env. Empty means "no explicit secret" —
    #: only valid for OAuth, where the CLI then uses the host's ``claude login``.
    value: str
    source: str
    user: Optional[User] = None

    @property
    def is_personal(self) -> bool:
        return self.source == ClaudeCredentialSource.USER


def require_user_credentials() -> bool:
    """Whether a job must run on the personal credential of its user.

    Off by default so the single-account setup of #1078 (one host-wide token)
    keeps working unchanged. Teams that bill per user turn it on: a job whose
    user has no credential for the chosen mode then fails loudly instead of
    quietly drawing on somebody else's quota.
    """
    return bool(getattr(settings, 'CLAUDE_REQUIRE_USER_CREDENTIALS', False))


def _shared_secret(auth_mode) -> str:
    """Host-wide credential for ``auth_mode`` from settings, else the env."""
    name = AUTH_MODE_ENV_VARS[auth_mode]
    return (getattr(settings, name, '') or os.environ.get(name, '') or '').strip()


def resolve_credential_user(item, actor=None) -> Optional[User]:
    """Return the user whose Claude account a run for ``item`` is billed to.

    The order is fixed and independent of who happens to have a credential
    stored — an attribution that changed depending on which profiles are filled
    in would be impossible to reason about, and the failure mode ("job ran on
    the wrong subscription") is silent.

    1. **``actor``** — whoever triggered the run. They pressed the button and
       they picked ABO/API for the issue, so it is their quota that is spent.
    2. ``item.responsible`` — for runs started without an interactive actor
       (automation, MCP, follow-up jobs), the item's owner.
    3. ``item.assigned_to``, then 4. ``item.requester`` as last resorts.

    ``None`` when the item carries no user at all; the caller then falls back to
    the host-wide credential (or fails, see :func:`require_user_credentials`).
    """
    for candidate in (
        actor,
        getattr(item, 'responsible', None),
        getattr(item, 'assigned_to', None),
        getattr(item, 'requester', None),
    ):
        if candidate is not None and getattr(candidate, 'pk', None):
            return candidate
    return None


def _missing_personal_credential_error(user, auth_mode) -> MissingClaudeCredential:
    what = (
        'Anthropic-API-Key' if auth_mode == ClaudeQueueJobAuthMode.API_KEY
        else 'Claude-OAuth-Token'
    )
    other = (
        'ABO' if auth_mode == ClaudeQueueJobAuthMode.API_KEY else 'API'
    )
    return MissingClaudeCredential(
        f"Kein persönlicher {what} für {user.name} ({user.username}) hinterlegt – "
        f"der Auth-Modus des Issues ist {AUTH_MODE_LABELS[auth_mode]}. "
        f"Das Credential unter „User Settings“ hinterlegen oder das Issue auf "
        f"„{other}“ umstellen."
    )


def resolve_claude_credential(user, auth_mode) -> ClaudeCredential:
    """Resolve the credential for one run of ``user`` in ``auth_mode``.

    Precedence: the user's personal credential, then — unless
    :func:`require_user_credentials` forbids it — the host-wide one. Never the
    credential of the *other* mode.

    Raises :class:`MissingClaudeCredential` when the requested mode cannot be
    served: an API-key run with no key anywhere would otherwise start and be
    rejected by the API, and a personal-credentials-only deployment must not
    quietly spend the shared quota.
    """
    auth_mode = (
        ClaudeQueueJobAuthMode.API_KEY
        if auth_mode == ClaudeQueueJobAuthMode.API_KEY
        else ClaudeQueueJobAuthMode.OAUTH
    )
    env_var = AUTH_MODE_ENV_VARS[auth_mode]

    personal = user.claude_credential_for(auth_mode) if user is not None else ''
    if personal:
        return ClaudeCredential(
            auth_mode=auth_mode, env_var=env_var, value=personal,
            source=ClaudeCredentialSource.USER, user=user,
        )

    if user is not None and require_user_credentials():
        raise _missing_personal_credential_error(user, auth_mode)

    shared = _shared_secret(auth_mode)
    if shared:
        return ClaudeCredential(
            auth_mode=auth_mode, env_var=env_var, value=shared,
            source=ClaudeCredentialSource.SHARED, user=user,
        )

    if auth_mode == ClaudeQueueJobAuthMode.API_KEY:
        # No key at all: an API run cannot be served. Failing here is the point
        # — the alternative would be an OAuth run nobody asked for.
        raise MissingClaudeCredential(
            'Auth-Modus API gewählt, aber weder ein persönlicher Anthropic-API-Key '
            'noch ANTHROPIC_API_KEY auf dem Host konfiguriert.'
        )

    # Subscription run without an explicit token: the CLI uses the credential
    # that `claude login` left in ~/.claude on the worker host (#1078).
    return ClaudeCredential(
        auth_mode=auth_mode, env_var=env_var, value='',
        source=ClaudeCredentialSource.HOST_LOGIN, user=user,
    )
