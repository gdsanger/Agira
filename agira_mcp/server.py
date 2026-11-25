"""
Agira MCP server.

Exposes Agira projects, items and changes to Claude (Desktop / Code) as MCP tools.
It is a thin wrapper around the existing ``/api/customgpt/*`` REST API:

  Claude  --(per-user token)-->  this MCP server  --(shared x-api-secret
                                                      + x-agira-user-token)-->  Agira

Authentication model (Option B):
  * The shared API secret lives here, server-side (env ``AGIRA_API_SECRET``),
    and is never exposed to Claude.
  * Each user connects with their personal token (Agira ``User.mcp_token``),
    copied from their Agira profile ("Claude MCP Integration").
    - Remote/HTTP: token from the connection URL ``?token=...`` or the
      ``x-agira-user-token`` header.
    - Local/stdio: token from env ``AGIRA_USER_TOKEN``.
  * Agira maps the token to a user and stamps created items' ``responsible``.
  * Soft phase (#1119): a connection without a token is still served (anonymous,
    org-level access as before) and only logs a warning — enforcement follows.

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
import logging
import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .client import AgiraClient, AgiraError

logger = logging.getLogger(__name__)

# Per-request user token (set by the ASGI middleware for HTTP transport).
# The default is a sentinel (not None) so we can tell "no HTTP request context"
# (stdio transport) apart from "HTTP request without a token". Only the former
# may fall back to the AGIRA_USER_TOKEN env var.
_UNSET = object()
_current_user_token: contextvars.ContextVar = contextvars.ContextVar(
    "current_user_token", default=_UNSET
)


def _client() -> AgiraClient:
    base_url = os.environ.get("AGIRA_BASE_URL", "http://localhost:8000")
    api_secret = os.environ.get("AGIRA_API_SECRET", "")
    if not api_secret:
        raise RuntimeError("AGIRA_API_SECRET is not configured for the MCP server.")
    return AgiraClient(base_url=base_url, api_secret=api_secret)


def _user_token() -> str | None:
    """Resolve the acting user's token.

    Under HTTP transport the middleware always sets the context var (to the
    request's token, or None when absent), so we use exactly what the request
    carried and never fall back to the env var. Under stdio transport the
    context var is never set, so we fall back to AGIRA_USER_TOKEN.
    """
    value = _current_user_token.get()
    if value is _UNSET:
        return os.environ.get("AGIRA_USER_TOKEN") or None
    return value or None


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
_INSTRUCTIONS = """\
Agira is a project/issue management system. This server exposes two domains:

ITEMS (issues): list_projects, get_project, list_open_items, get_item,
  get_item_context, create_item, update_item, copy_item, link_github_pr.
  Use copy_item when one problem affects several projects and each project
  needs its own issue (the original is kept and linked as "Related").

CHANGES (ITIL-style change records, e.g. a planned deployment/rollout):
  describe_changes   -> START HERE: explains the model, status workflow,
                        risk levels, field formats and what is NOT allowed.
  list_changes, get_change                      (read)
  create_change, update_change                  (write)
  link_items_to_change                          (attach/detach items)
  list_project_releases, list_organisations     (lookup of ids for a change)

Approvals of a change are read-only for the AI: they are visible in
get_change, but approving/rejecting, adding approvers and deleting a change
are human-only actions and not available here.
"""

mcp = FastMCP(
    "agira",
    instructions=_INSTRUCTIONS,
    **({"transport_security": _security} if _security else {}),
)


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
    """
    List open items (status != Closed). Optionally scoped to one project.

    Each returned item includes ``id`` and ``status`` (the canonical
    ItemStatus value, e.g. "Working", "Review") as top-level fields, so the
    id-to-status mapping never requires a separate lookup.
    """
    client = _client()
    if project_id is not None:
        return client.get_project_open_items(project_id)
    return client.list_open_items()


@mcp.tool()
def get_item(item_id: int) -> dict:
    """
    Get a single Agira item by its numeric id.

    The response includes ``id`` and ``status`` (the canonical ItemStatus
    value) as top-level fields.
    """
    return _client().get_item(item_id)


@mcp.tool()
def get_item_context(item_id: int) -> dict:
    """
    Get RAG context (related knowledge) for an item, useful for answering.

    Each context object (``layer_a``/``layer_b``/``layer_c``/``all_items``)
    includes ``object_id`` (the id of the underlying item/object) and
    ``status`` (its canonical status, when the object type has one, e.g.
    Agira items) as top-level fields.
    """
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
    parent_id: int | None = None,
) -> dict:
    """
    Create a new item (issue) in a project.

    The connecting user is recorded as the item's ``responsible`` (the user
    must have the Agira "Agent" role). ``title`` and ``type_id`` are required.
    Use ``list_projects`` / project details to find valid ``type_id`` values.

    ``parent_id`` optionally sets the parent item (e.g. an Epic) the new item
    belongs to. Leave it unset to create the item without a parent. The
    parent must exist and must not itself be Closed.
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
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return _client().create_item(project_id, payload, user_token=_user_token())


@mcp.tool()
def update_item(
    item_id: int,
    title: str | None = None,
    description: str | None = None,
    solution_description: str | None = None,
    pr_description: str | None = None,
    status: str | None = None,
    intern: bool | None = None,
    parent_id: int | None = None,
    clear_parent: bool = False,
    implementation_provider: str | None = None,
    review_provider: str | None = None,
    suggested_model: str | None = None,
) -> dict:
    """
    Update fields of an existing item (partial update). Only set what changes.
    Fails with a clear error if ``item_id`` does not refer to an existing item.

    ``solution_description`` sets the item's "Solution" field.

    ``pr_description`` sets the item's "PR-Description" field (normally the
    final GitHub pull request body, captured automatically on merge — set it
    explicitly here to record or correct it directly).

    ``parent_id`` sets or changes the item's parent (e.g. an Epic). Leave it
    unset to leave the current parent unchanged. To remove an existing parent
    relationship, pass ``clear_parent=True`` (``parent_id`` is ignored in that
    case). The parent must exist, must not be Closed, and cannot be the item
    itself.

    ``implementation_provider`` (``claude`` | ``openai``) selects the coding
    agent of the Agent Queue that implements the item. ``review_provider``
    (``claude`` | ``openai``, or an empty string for "automatic" = the other
    provider than the implementation) selects the reviewer. ``suggested_model``
    is the model slug and must fit the provider (e.g. ``sonnet``, ``opus-5-5``
    for Claude; ``gpt-6.2-sol``, ``gpt-6.2-astra`` for OpenAI).
    """
    payload = {
        k: v
        for k, v in {
            "title": title,
            "description": description,
            "solution_description": solution_description,
            "pr_description": pr_description,
            "status": status,
            "intern": intern,
            "implementation_provider": implementation_provider,
            "review_provider": review_provider,
            "suggested_model": suggested_model,
        }.items()
        if v is not None
    }
    if clear_parent:
        payload["parent_id"] = None
    elif parent_id is not None:
        payload["parent_id"] = parent_id
    return _client().update_item(item_id, payload, user_token=_user_token())


@mcp.tool()
def copy_item(item_id: int, target_project_ids: list[int]) -> dict:
    """
    Copy an item into one or more OTHER projects (one new item per project).

    Use this when a reported problem affects several projects and each project
    needs its own issue. The original item is NOT changed; every copy is linked
    to the original with a "Related" relation, so the connection stays visible.

    Copied: title, description, user_input, type, intern flag, requester,
    organisation (only if it is a client of the target project) and the agent
    settings (providers/model). NOT copied: status (the copy starts in
    ``Inbox``), assignee/responsible, parent/epic order, solution and PR
    description, release, nodes, changes, comments, attachments and GitHub
    issue/PR mappings.

    ``target_project_ids`` must not contain the original item's own project.
    Find project ids with ``list_projects``. All copies are created together
    or not at all.

    Returns ``{"original_id": ..., "copies": [item, ...]}`` where each copy is
    a full item dict (``id``, ``project_id``, ``status`` ...).
    """
    return _client().copy_item(
        item_id, {"target_project_ids": target_project_ids}, user_token=_user_token()
    )


@mcp.tool()
def link_github_pr(item_id: int, pr_number: int) -> dict:
    """
    Link a GitHub pull request to an Agira item via an ExternalIssueMapping
    (kind="PR"). This is the write path used to record which PR resolves an
    item; use it once a PR has been opened for the item's work.

    Only ``pr_number`` (the GitHub PR number, e.g. 42 for ".../pull/42") is
    needed — the owner/repo come from the item's project configuration, and
    the rest of the PR reference (GitHub id, state, html_url) is resolved
    from the GitHub API automatically, same as the existing "Link GitHub
    Issue/PR" UI action.

    Idempotent: calling this again for the same item/PR updates the existing
    mapping in place (matched by GitHub id, then by item+PR number) instead
    of creating a duplicate.

    Returns a dict with:
      - ``item_id``: the affected item
      - ``created``: True if a new mapping was created, False if an existing
        one was updated
      - ``mapping``: the resolved mapping — ``id``, ``kind``, ``number``,
        ``github_id``, ``state``, ``html_url``

    Fails with a clear error if ``item_id`` does not exist, ``pr_number`` is
    missing/invalid, the item's project has no GitHub repo configured, or the
    PR number cannot be resolved on GitHub.
    """
    return _client().link_github_pr(item_id, {"pr_number": pr_number}, user_token=_user_token())


# --------------------------------------------------------------------------
# Change tools
# --------------------------------------------------------------------------
_CHANGE_STATUSES = ["Draft", "Planned", "InProgress", "Deployed", "RolledBack", "Canceled"]
_RISK_LEVELS = ["Low", "Normal", "High", "VeryHigh"]


@mcp.tool()
def describe_changes() -> dict:
    """
    Explain how Changes work in Agira — call this first before creating or
    editing a change. No network call; returns the static reference below.

    A Change is a planned modification of a system (deployment, migration,
    configuration change ...) with risk assessment, mitigation, rollback and
    communication plan. It belongs to exactly one project, may be attached to
    a release of that project, can have affected organisations and can be
    linked to items (issues) that it implements.
    """
    return {
        "purpose": "A Change documents a planned modification incl. risk, mitigation, "
                   "rollback and communication. It belongs to one project.",
        "tools": {
            "list_changes": "Overview, filterable by project/status/release.",
            "get_change": "Everything about one change incl. linked items and approvals.",
            "create_change": "New change in a project (starts as Draft unless set).",
            "update_change": "Partial update; only send fields that change.",
            "link_items_to_change": "Attach/detach items (issues) to a change.",
            "list_project_releases": "Find release_id values for a project.",
            "list_organisations": "Find organisation_ids.",
        },
        "status_values": _CHANGE_STATUSES,
        "status_meaning": {
            "Draft": "Being written, not yet proposed (default).",
            "Planned": "Ready for approval/scheduling.",
            "InProgress": "Is being executed right now.",
            "Deployed": "Successfully executed (set executed_at).",
            "RolledBack": "Executed, then reverted.",
            "Canceled": "Will not happen.",
        },
        "risk_values": _RISK_LEVELS,
        "fields": {
            "title": "required, short summary",
            "description": "Markdown",
            "risk_description": "Markdown — what can go wrong",
            "mitigation": "Markdown — how the risk is reduced",
            "rollback_plan": "Markdown — how to undo",
            "communication_plan": "Markdown — who is informed when",
            "planned_start / planned_end / executed_at": "ISO 8601 datetime, "
                                                         "e.g. 2026-12-01T09:00:00+01:00; null clears",
            "planned_date": "ISO date, e.g. 2026-12-01; null clears",
            "release_id": "Release of the SAME project; null removes it",
            "organisation_ids": "List of affected organisation ids; replaces the whole list",
            "is_safety_relevant": "bool",
        },
        "rules": [
            "The project of an existing change cannot be changed.",
            "A release must belong to the change's project.",
            "Approvers are assigned automatically from the change policy after "
            "create/update (same as in the web UI).",
            "Approvals are read-only here: approving/rejecting, adding/removing "
            "approvers and deleting a change are human-only.",
            "update_change is a partial update: omitted fields stay unchanged.",
        ],
        "typical_flow": [
            "get_project / list_projects -> project_id",
            "optional: list_project_releases, list_organisations",
            "create_change(project_id, title, description, risk, risk_description, "
            "mitigation, rollback_plan, communication_plan, planned_start ...)",
            "link_items_to_change(change_id, add_item_ids=[...])",
            "update_change(change_id, status='Planned')",
        ],
    }


@mcp.tool()
def list_changes(
    project_id: int | None = None,
    status: str | None = None,
    release_id: int | None = None,
    open_only: bool = False,
) -> list:
    """
    List changes (newest first, max. 200), optionally filtered.

    ``status`` is one of Draft, Planned, InProgress, Deployed, RolledBack,
    Canceled. ``open_only=True`` hides finished changes (Deployed, RolledBack,
    Canceled). Each entry is a summary (id, title, project_id, status, risk,
    release_id, planned dates ...); use ``get_change`` for texts, items and
    approvals.
    """
    return _client().list_changes({
        "project_id": project_id,
        "status": status,
        "release_id": release_id,
        "open_only": "true" if open_only else None,
    })


@mcp.tool()
def get_change(change_id: int) -> dict:
    """
    Get one change in full: all texts (description, risk_description,
    mitigation, rollback_plan, communication_plan), dates, ``organisation_ids``,
    ``item_ids`` (items linked directly), ``associated_item_ids`` (linked items
    plus items of the change's release) and ``approvals`` (read-only: approver,
    role, is_required, status Pending/Accept/Reject/Abstained/Info, comment).
    """
    return _client().get_change(change_id)


@mcp.tool()
def create_change(
    project_id: int,
    title: str,
    description: str = "",
    status: str | None = None,
    risk: str | None = None,
    risk_description: str = "",
    mitigation: str = "",
    rollback_plan: str = "",
    communication_plan: str = "",
    planned_start: str | None = None,
    planned_end: str | None = None,
    planned_date: str | None = None,
    release_id: int | None = None,
    organisation_ids: list[int] | None = None,
    is_safety_relevant: bool = False,
    item_ids: list[int] | None = None,
) -> dict:
    """
    Create a change in a project. Call ``describe_changes`` first for the
    reference. Only ``project_id`` and ``title`` are required.

    ``status``: Draft (default) | Planned | InProgress | Deployed | RolledBack
    | Canceled. ``risk``: Low | Normal (default) | High | VeryHigh.
    Text fields accept Markdown. ``planned_start``/``planned_end`` are ISO 8601
    datetimes (e.g. ``2026-12-01T09:00:00+01:00``), ``planned_date`` an ISO date.
    ``release_id`` must belong to the same project (see
    ``list_project_releases``); ``organisation_ids`` come from
    ``list_organisations``; ``item_ids`` links existing items right away.

    The connecting user is recorded as creator. Approvers are assigned
    automatically from the change policy; approving is human-only.
    Returns the created change (same shape as ``get_change``).
    """
    payload = {
        k: v for k, v in {
            "title": title, "description": description, "status": status, "risk": risk,
            "risk_description": risk_description, "mitigation": mitigation,
            "rollback_plan": rollback_plan, "communication_plan": communication_plan,
            "planned_start": planned_start, "planned_end": planned_end,
            "planned_date": planned_date, "release_id": release_id,
            "organisation_ids": organisation_ids, "is_safety_relevant": is_safety_relevant,
            "item_ids": item_ids,
        }.items() if v is not None
    }
    return _client().create_change(project_id, payload, user_token=_user_token())


@mcp.tool()
def update_change(
    change_id: int,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    risk: str | None = None,
    risk_description: str | None = None,
    mitigation: str | None = None,
    rollback_plan: str | None = None,
    communication_plan: str | None = None,
    planned_start: str | None = None,
    planned_end: str | None = None,
    planned_date: str | None = None,
    executed_at: str | None = None,
    release_id: int | None = None,
    organisation_ids: list[int] | None = None,
    is_safety_relevant: bool | None = None,
    clear_release: bool = False,
    clear_dates: list[str] | None = None,
) -> dict:
    """
    Partial update of a change — only set what changes; unset (None) fields
    stay as they are. Values/formats as in ``create_change``; additionally
    ``executed_at`` (ISO 8601 datetime, when it was actually executed).

    ``organisation_ids`` REPLACES the whole list (pass the complete set).
    ``clear_release=True`` removes the release. ``clear_dates`` is a list of
    date field names to empty (``planned_start``, ``planned_end``,
    ``planned_date``, ``executed_at``). The project of a change cannot be
    changed, and deleting a change or deciding approvals is not possible here.
    Use ``link_items_to_change`` for items. Returns the updated change.
    """
    payload = {
        k: v for k, v in {
            "title": title, "description": description, "status": status, "risk": risk,
            "risk_description": risk_description, "mitigation": mitigation,
            "rollback_plan": rollback_plan, "communication_plan": communication_plan,
            "planned_start": planned_start, "planned_end": planned_end,
            "planned_date": planned_date, "executed_at": executed_at,
            "release_id": release_id, "organisation_ids": organisation_ids,
            "is_safety_relevant": is_safety_relevant,
        }.items() if v is not None
    }
    if clear_release:
        payload["release_id"] = None
    for name in clear_dates or []:
        if name not in ("planned_start", "planned_end", "planned_date", "executed_at"):
            raise ValueError(f"clear_dates: unknown field {name!r}")
        payload[name] = None
    return _client().update_change(change_id, payload, user_token=_user_token())


@mcp.tool()
def link_items_to_change(
    change_id: int,
    add_item_ids: list[int] | None = None,
    remove_item_ids: list[int] | None = None,
) -> dict:
    """
    Attach and/or detach items (issues) to a change. Idempotent: adding an
    already linked item or removing a non-linked one is a no-op. Unknown ids
    in ``add_item_ids`` are rejected. Returns the updated change
    (see ``item_ids`` / ``associated_item_ids``).
    """
    return _client().update_change_items(
        change_id,
        {"add_item_ids": add_item_ids or [], "remove_item_ids": remove_item_ids or []},
        user_token=_user_token(),
    )


@mcp.tool()
def list_project_releases(project_id: int) -> list:
    """List the releases of a project (id, name, version, status, planned_date) — gives valid ``release_id`` values for a change."""
    return _client().list_project_releases(project_id)


@mcp.tool()
def list_organisations() -> list:
    """List all organisations (id, name) — gives valid ``organisation_ids`` for a change."""
    return _client().list_organisations()


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
            if not token:
                # Soft phase (#1119): connections without a personal token stay
                # allowed and act anonymously in Agira. Logged so we can see who
                # still uses the old org-wide URL before enforcement lands.
                logger.warning(
                    "MCP connection without a per-user token (%s) — acting anonymously. "
                    "Use the personal connector URL from the Agira profile "
                    "(…/mcp/?token=<your-token>).",
                    scope.get("path", "/"),
                )
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
