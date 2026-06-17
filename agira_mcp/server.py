"""
Agira MCP server.

Exposes Agira projects and items to Claude (Desktop / Code) as MCP tools.
It is a thin wrapper around the existing ``/api/customgpt/*`` REST API:

  Claude  --(per-user token)-->  this MCP server  --(shared x-api-secret
                                                      + x-agira-user-token)-->  Agira

Authentication model (Option B):
  * The shared API secret lives here, server-side (env ``AGIRA_API_SECRET``),
    and is never exposed to Claude.
  * Each user connects with their personal token (Agira ``User.mcp_token``).
    - Remote/HTTP: token from the connection URL ``?token=...`` or the
      ``x-agira-user-token`` header.
    - Local/stdio: token from env ``AGIRA_USER_TOKEN``.
  * Agira maps the token to a user and stamps created items' ``responsible``.

Run locally against a dev instance (stdio):
    AGIRA_BASE_URL=http://localhost:8000 \\
    AGIRA_API_SECRET=dev-secret \\
    AGIRA_USER_TOKEN=<a-users-mcp_token> \\
    python -m agira_mcp.server --transport stdio

Run as a remote connector (HTTP):
    AGIRA_BASE_URL=https://agira.example.com \\
    AGIRA_API_SECRET=... \\
    python -m agira_mcp.server --transport http --host 0.0.0.0 --port 8765
"""
from __future__ import annotations

import argparse
import contextvars
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .client import AgiraClient, AgiraError

# Per-request user token (set by the ASGI middleware for HTTP transport).
_current_user_token: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_user_token", default=None
)


def _client() -> AgiraClient:
    base_url = os.environ.get("AGIRA_BASE_URL", "http://localhost:8000")
    api_secret = os.environ.get("AGIRA_API_SECRET", "")
    if not api_secret:
        raise RuntimeError("AGIRA_API_SECRET is not configured for the MCP server.")
    return AgiraClient(base_url=base_url, api_secret=api_secret)


def _user_token() -> str | None:
    """Resolve the acting user's token: per-request (HTTP) or env (stdio)."""
    return _current_user_token.get() or os.environ.get("AGIRA_USER_TOKEN") or None


# Default SDK hosts/origins (localhost only) — kept so stdio and local HTTP
# keep working. The MCP SDK enables DNS-rebinding protection and answers 421
# for any Host header not on this allowlist.
_DEFAULT_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
_DEFAULT_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def _transport_security() -> TransportSecuritySettings | None:
    """Build transport-security settings from env.

    When the server runs behind a reverse proxy, nginx forwards the public
    Host header (e.g. ``agiramcp.example.com``), which is not on the SDK's
    localhost-only allowlist and would be rejected with 421. Set
    ``AGIRA_MCP_ALLOWED_HOSTS`` (comma-separated, no scheme) to the public
    host(s) to allow them. Returns None to keep the SDK defaults (local only).
    """
    hosts = [h.strip() for h in os.environ.get("AGIRA_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if not hosts:
        return None
    origins = [o.strip() for o in os.environ.get("AGIRA_MCP_ALLOWED_ORIGINS", "").split(",") if o.strip()]
    # Default origins to https://<host> for each configured host if none given.
    if not origins:
        origins = [f"https://{h}" for h in hosts]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_DEFAULT_HOSTS + hosts,
        allowed_origins=_DEFAULT_ORIGINS + origins,
    )


_security = _transport_security()
mcp = FastMCP("agira", **({"transport_security": _security} if _security else {}))


# --------------------------------------------------------------------------
# Read tools
# --------------------------------------------------------------------------
@mcp.tool()
def list_projects() -> list:
    """List all Agira projects (id, name, status, ...)."""
    return _client().list_projects()


@mcp.tool()
def get_project(project_id: int) -> dict:
    """Get a single Agira project by its numeric id."""
    return _client().get_project(project_id)


@mcp.tool()
def list_open_items(project_id: int | None = None) -> list:
    """List open items (status != Closed). Optionally scoped to one project."""
    client = _client()
    if project_id is not None:
        return client.get_project_open_items(project_id)
    return client.list_open_items()


@mcp.tool()
def get_item(item_id: int) -> dict:
    """Get a single Agira item by its numeric id."""
    return _client().get_item(item_id)


@mcp.tool()
def get_item_context(item_id: int) -> dict:
    """Get RAG context (related knowledge) for an item, useful for answering."""
    return _client().get_item_context(item_id)


# --------------------------------------------------------------------------
# Write tools
# --------------------------------------------------------------------------
@mcp.tool()
def create_item(
    project_id: int,
    title: str,
    type_id: int,
    description: str = "",
    user_input: str = "",
    solution_description: str = "",
    status: str | None = None,
    intern: bool = False,
) -> dict:
    """
    Create a new item (issue) in a project.

    The connecting user is recorded as the item's ``responsible`` (the user
    must have the Agira "Agent" role). ``title`` and ``type_id`` are required.
    Use ``list_projects`` / project details to find valid ``type_id`` values.
    """
    payload: dict = {
        "title": title,
        "type_id": type_id,
        "description": description,
        "user_input": user_input,
        "solution_description": solution_description,
        "intern": intern,
    }
    if status is not None:
        payload["status"] = status
    return _client().create_item(project_id, payload, user_token=_user_token())


@mcp.tool()
def update_item(
    item_id: int,
    title: str | None = None,
    description: str | None = None,
    solution_description: str | None = None,
    status: str | None = None,
    intern: bool | None = None,
) -> dict:
    """Update fields of an existing item (partial update). Only set what changes."""
    payload = {
        k: v
        for k, v in {
            "title": title,
            "description": description,
            "solution_description": solution_description,
            "status": status,
            "intern": intern,
        }.items()
        if v is not None
    }
    return _client().update_item(item_id, payload, user_token=_user_token())


# --------------------------------------------------------------------------
# HTTP transport: capture the per-user token from the connection
# --------------------------------------------------------------------------
def _build_http_app():
    """Wrap the streamable-HTTP ASGI app to extract the per-user token."""
    from urllib.parse import parse_qs

    inner = mcp.streamable_http_app()

    async def app(scope, receive, send):
        if scope["type"] == "http":
            token = None
            qs = parse_qs(scope.get("query_string", b"").decode())
            if qs.get("token"):
                token = qs["token"][0]
            if not token:
                for name, value in scope.get("headers", []):
                    if name == b"x-agira-user-token":
                        token = value.decode()
                        break
            reset = _current_user_token.set(token)
            try:
                await inner(scope, receive, send)
            finally:
                _current_user_token.reset(reset)
        else:
            await inner(scope, receive, send)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Agira MCP server")
    parser.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        import uvicorn

        uvicorn.run(_build_http_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
