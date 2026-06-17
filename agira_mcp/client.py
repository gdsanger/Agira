"""
Thin HTTP client around the Agira CustomGPT REST API.

The MCP server holds the shared ``x-api-secret`` (server-side, never exposed to
Claude) and forwards the connecting user's personal token as
``x-agira-user-token`` so Agira can attribute created items (set ``responsible``).
"""
from __future__ import annotations

import httpx


class AgiraError(Exception):
    """Raised when the Agira API returns a non-2xx response."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Agira API error {status_code}: {message}")


class AgiraClient:
    """Wraps the ``/api/customgpt/*`` endpoints of an Agira instance."""

    def __init__(self, base_url: str, api_secret: str, timeout: float = 30.0):
        # e.g. https://agira.example.com  (no trailing slash, no /api/customgpt)
        self.base_url = base_url.rstrip("/")
        self.api_secret = api_secret
        self.timeout = timeout

    def _headers(self, user_token: str | None) -> dict[str, str]:
        headers = {
            "x-api-secret": self.api_secret,
            "Content-Type": "application/json",
        }
        if user_token:
            headers["x-agira-user-token"] = user_token
        return headers

    def _request(self, method: str, path: str, *, user_token: str | None = None,
                 json: dict | None = None) -> dict | list:
        url = f"{self.base_url}/api/customgpt/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.request(method, url, headers=self._headers(user_token), json=json)
        except httpx.RequestError as exc:
            raise AgiraError(0, f"Could not reach Agira at {url}: {exc}") from exc

        if resp.status_code >= 400:
            # Surface the API's error message when available.
            try:
                detail = resp.json().get("error", resp.text)
            except Exception:
                detail = resp.text
            raise AgiraError(resp.status_code, str(detail))

        if not resp.content:
            return {}
        return resp.json()

    # ----- Projects -------------------------------------------------------
    def list_projects(self) -> list:
        return self._request("GET", "projects")

    def get_project(self, project_id: int) -> dict:
        return self._request("GET", f"projects/{project_id}")

    def get_project_open_items(self, project_id: int) -> list:
        return self._request("GET", f"projects/{project_id}/open-items")

    # ----- Items ----------------------------------------------------------
    def list_open_items(self) -> list:
        return self._request("GET", "items")

    def get_item(self, item_id: int) -> dict:
        return self._request("GET", f"items/{item_id}")

    def get_item_context(self, item_id: int) -> dict:
        return self._request("GET", f"items/{item_id}/context")

    def create_item(self, project_id: int, payload: dict, *, user_token: str | None) -> dict:
        return self._request("POST", f"projects/{project_id}/items",
                             json=payload, user_token=user_token)

    def update_item(self, item_id: int, payload: dict, *, user_token: str | None) -> dict:
        return self._request("PATCH", f"items/{item_id}",
                             json=payload, user_token=user_token)
