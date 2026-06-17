# Agira MCP Server

Makes Agira **projects** and **items** available to Claude (Desktop, Web, Code)
as MCP tools — reading and creating/updating issues directly from a chat.

It is a thin wrapper around Agira's existing `/api/customgpt/*` REST API. No
business logic is duplicated; every tool calls one endpoint.

## How auth works (Option B)

```
Claude  --(per-user token)-->  MCP server  --(x-api-secret + x-agira-user-token)-->  Agira
```

- The **shared API secret** (`AGIRA_API_SECRET`) lives only in the MCP server.
  Claude never sees it.
- Each user connects with a **personal token** = their Agira `User.mcp_token`
  (generate it in the Django admin: select the user → action *"Generate MCP token"*).
- Agira maps the token to the user and records created items'
  **`responsible`** field. The user must have the Agira **"Agent"** role.

## Tools

| Tool | Endpoint | |
|------|----------|--|
| `list_projects` | `GET /projects` | read |
| `get_project` | `GET /projects/{id}` | read |
| `list_open_items` | `GET /items` or `/projects/{id}/open-items` | read |
| `get_item` | `GET /items/{id}` | read |
| `get_item_context` | `GET /items/{id}/context` (RAG) | read |
| `create_item` | `POST /projects/{id}/items` | write |
| `update_item` | `PATCH /items/{id}` | write |

> Creating **projects** and **deleting** anything is intentionally not exposed
> (mirrors the API). Add later if needed.

## Setup

```bash
cd agira_mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in AGIRA_BASE_URL + AGIRA_API_SECRET
```

### Local test (stdio, acts as one user)

```bash
export $(grep -v '^#' .env | xargs)
export AGIRA_USER_TOKEN=<an-agira-users-mcp_token>
python -m agira_mcp.server --transport stdio
```

In Claude Code, add to `.mcp.json`:

```json
{
  "mcpServers": {
    "agira": {
      "command": "python",
      "args": ["-m", "agira_mcp.server", "--transport", "stdio"],
      "env": {
        "AGIRA_BASE_URL": "http://localhost:8000",
        "AGIRA_API_SECRET": "dev-secret",
        "AGIRA_USER_TOKEN": "<your-mcp_token>"
      }
    }
  }
}
```

### Remote (HTTP, for Claude Desktop custom connector)

```bash
export $(grep -v '^#' .env | xargs)
python -m agira_mcp.server --transport http --host 0.0.0.0 --port 8765
```

Put it behind TLS (e.g. nginx) at `https://agira.example.com/mcp`, then in
**Claude Desktop → Settings → Connectors → Add custom connector**, each user
enters their personal URL:

```
https://agira.example.com/mcp?token=<their-mcp_token>
```

> ⚠️ With the shared-secret model the MCP endpoint itself is the trust boundary.
> Keep it behind VPN / IP-allowlist, and only hand out per-user `?token=` URLs.
> User attribution comes from that token; revoke access via the admin action
> *"Clear MCP token"*.
