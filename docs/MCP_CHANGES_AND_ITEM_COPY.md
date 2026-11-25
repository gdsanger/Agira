# MCP: Changes und Item-Kopie

## Item in andere Projekte kopieren

- UI: Item-Detail → Menü „Workflow“ → **Kopie in anderes Projekt** (Mehrfachauswahl der Zielprojekte).
- MCP-Tool: `copy_item(item_id, target_project_ids)`; REST: `POST /api/customgpt/items/{id}/copy`.
- Service: `core/services/item_copy.py` (`copy_item_to_project`).
- Das Original bleibt unverändert; jede Kopie ist mit ihm als **Related** verknüpft.
- Kopiert: Titel, Beschreibung, Original-Text, Typ, Intern, Requester, Organisation (nur wenn Client des Zielprojekts), Agent-Einstellungen.
- Nicht kopiert: Status (Kopie startet in `Inbox`), Zuständige, Parent/Epic-Reihenfolge, Solution/PR-Description, Release, Nodes, Changes, Kommentare, Anhänge, GitHub-Verknüpfungen.
- Alle Kopien eines Aufrufs entstehen gemeinsam oder gar nicht.

## Changes über die MCP-Schnittstelle

Einstieg für die KI: Tool `describe_changes` (Modell, Status, Risiko, Feldformate, Regeln, typischer Ablauf). Die Server-Instructions verweisen darauf.

| Tool | REST (`/api/customgpt/…`) | Zweck |
|---|---|---|
| `describe_changes` | – | statische Referenz |
| `list_changes` | `GET changes?project_id&status&release_id&open_only` | Übersicht (max. 200) |
| `get_change` | `GET changes/{id}` | Details inkl. Items, Approvals (read-only) |
| `create_change` | `POST projects/{id}/changes` | anlegen |
| `update_change` | `PATCH changes/{id}` | Teil-Update |
| `link_items_to_change` | `POST changes/{id}/items` | Items zu-/abordnen |
| `list_project_releases` | `GET projects/{id}/releases` | `release_id` finden |
| `list_organisations` | `GET organisations` | `organisation_ids` finden |

Bewusst **nicht** verfügbar: Change löschen, Projekt eines Changes ändern, Approvals entscheiden/hinzufügen/entfernen, Approval-Mails. Approver werden nach Anlegen/Ändern wie in der Web-UI automatisch aus der ChangePolicy gesetzt. Der verbindende Nutzer (MCP-Token) wird als `created_by` bzw. Actor im Activity-Log geführt.

Code: `core/views_api_changes.py`, `core/urls_api.py`, `agira_mcp/server.py`, `agira_mcp/client.py`. Tests: `core/test_item_copy_and_change_api.py`.
