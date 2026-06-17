# Agira MCP-Connector — Einrichtung & Betrieb

Diese Anleitung beschreibt, wie der Agira-MCP-Server aufgesetzt, hinter TLS
betrieben und in Claude (Desktop/Web) eingebunden wird. Sie ist die
ausführliche Ops-Variante zur knappen [README](README.md).

> **Was ist das?** Ein dünner MCP-Server (`agira_mcp/`), der Agiras vorhandene
> REST-API (`/api/customgpt/*`) für Claude zugänglich macht — Projekte & Items
> lesen sowie Items anlegen/ändern, direkt aus dem Chat.

---

## 1. Architektur

```
Claude (Desktop/Web)
      │  HTTPS, URL mit ?token=<persönlicher Token>
      ▼
nginx (TLS-Terminierung, Reverse-Proxy)
      │  http://127.0.0.1:8765
      ▼
agira-mcp.service  (uvicorn / FastMCP)
      │  HTTP, Header: x-api-secret (shared) + x-agira-user-token (pro User)
      ▼
Agira REST-API  /api/customgpt/*   →   Django / PostgreSQL
```

**Auth-Modell (Option B):**
- Das **geteilte Secret** (`AGIRA_API_SECRET` = Djangos `CUSTOMGPT_API_SECRET`)
  liegt nur im MCP-Server, serverseitig. Claude sieht es nie.
- Jeder Nutzer verbindet sich mit seinem **persönlichen Token**
  (`User.mcp_token`), übergeben in der Connector-URL als `?token=…`.
- Agira löst den Token zum User auf und setzt beim Anlegen das Feld
  **`responsible`**. Voraussetzung: der User hat die Rolle **„Agent"**.

---

## 2. Voraussetzungen

- Server mit Zugriff auf die Agira-Instanz (gleiche Maschine oder erreichbar
  über `AGIRA_BASE_URL`).
- **Python ≥ 3.10** (das MCP-SDK erfordert das; ein System-Python 3.9 reicht
  nicht — ggf. pyenv o.ä. nutzen).
- nginx + ein TLS-Zertifikat (z.B. certbot/Let's Encrypt).
- In Agira gesetzt: `CUSTOMGPT_API_SECRET` (sonst liefert die API 500).

---

## 3. MCP-Server installieren

Eigenes, getrenntes venv (nicht das Django-venv):

```bash
cd /opt/Agira/agira_mcp
python3.13 -m venv venv          # Python ≥3.10
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Konfiguration (Env-Datei)

Lege z.B. `/opt/Agira/agira_mcp/.env` an:

```ini
AGIRA_BASE_URL=http://localhost:8000
AGIRA_API_SECRET=<derselbe Wert wie CUSTOMGPT_API_SECRET in Agira>

# WICHTIG hinter Reverse-Proxy: der öffentliche Host muss erlaubt werden,
# sonst antwortet das MCP-SDK mit 421 (DNS-Rebinding-Schutz).
AGIRA_MCP_ALLOWED_HOSTS=agiramcp.isarlabs.de
# optional, default = https://<host>:
# AGIRA_MCP_ALLOWED_ORIGINS=https://agiramcp.isarlabs.de
```

> **Hinweis:** Der Server lädt `.env` **nicht** automatisch. Entweder die
> Variablen exportieren oder (empfohlen) per systemd `EnvironmentFile` laden.

### Manueller Start zum Testen

```bash
cd /opt/Agira
export $(grep -v '^#' agira_mcp/.env | xargs)
python -m agira_mcp.server --transport http --host 127.0.0.1 --port 8765
```

> `-m agira_mcp.server` muss aus `/opt/Agira` (dem Elternverzeichnis) laufen,
> sonst: `No module named 'agira_mcp'`.

---

## 4. Als Dienst (systemd)

`/etc/systemd/system/agira-mcp.service`:

```ini
[Unit]
Description=Agira MCP server
After=network.target

[Service]
User=anger
WorkingDirectory=/opt/Agira
EnvironmentFile=/opt/Agira/agira_mcp/.env
ExecStart=/opt/Agira/agira_mcp/venv/bin/python -m agira_mcp.server --transport http --host 127.0.0.1 --port 8765
Restart=always
RestartSec=2

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now agira-mcp.service
sudo systemctl status agira-mcp.service     # active (running)?
```

> Hinter nginx an **`127.0.0.1`** binden (nicht `0.0.0.0`), damit der Dienst
> nicht offen im Netz hängt.

---

## 5. TLS / nginx

Zertifikat holen (ohne dass certbot die Proxy-Config umschreibt):

```bash
sudo certbot certonly --nginx -d agiramcp.isarlabs.de
```

`/etc/nginx/sites-available/agiramcp`:

```nginx
server {
    listen 80;
    server_name agiramcp.isarlabs.de;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name agiramcp.isarlabs.de;

    ssl_certificate     /etc/letsencrypt/live/agiramcp.isarlabs.de/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/agiramcp.isarlabs.de/privkey.pem;

    location /mcp {
        proxy_pass http://127.0.0.1:8765;

        # Streamable HTTP / SSE: kein Buffering, lange Verbindung
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/agiramcp /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 6. Per-User-Tokens vergeben

Im **Django-Admin**:
1. User auswählen (muss Rolle **„Agent"** haben, damit `responsible` greift).
2. Aktion **„Generate MCP token"** ausführen → Token wird in `User.mcp_token`
   gespeichert.
3. Dem User seine persönliche Connector-URL geben:
   `https://agiramcp.isarlabs.de/mcp?token=<sein-token>`

Widerruf: Aktion **„Clear MCP token"**.

> Tokens sind Zugangsdaten — wie ein Passwort behandeln, nicht im Klartext
> teilen, bei Verdacht neu generieren.

---

## 7. In Claude Desktop einbinden

Settings → **Connectors** → **Add custom connector** →
URL: `https://agiramcp.isarlabs.de/mcp?token=<token>`

Danach im Chat testen:
- *„Liste meine Agira-Projekte"*
- *„Lege in Projekt … ein Test-Item an"* → `responsible` sollte auf den
  Token-User zeigen.

### Team / Enterprise: Org-Einstellungen
- Ein Org-Admin muss ggf. erlauben, dass **Mitglieder eigene Custom Connectors
  hinzufügen**.
- **Keinen** einzelnen zentralen Org-Connector mit fester URL hinterlegen — die
  URL (und damit der `?token=`) wäre für alle gleich → jede Issue bekäme
  denselben `responsible`. Stattdessen trägt **jeder Nutzer seine eigene
  `?token=`-URL** ein.
- Echte zentrale Identität pro Nutzer bräuchte OAuth statt des
  Shared-Secret-Modells (derzeit nicht implementiert).

---

## 8. Tests / Smoke-Checks

```bash
# 1. REST-API + Secret (auf dem Agira-Host)
curl -s -o /dev/null -w "%{http_code}\n" \
  http://localhost:8000/api/customgpt/projects -H "x-api-secret: $AGIRA_API_SECRET"
# erwartet: 200

# 2. MCP-Server lauscht (lokal)
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8765/mcp
# erwartet: 406  (nackter GET ohne MCP-Header → "Not Acceptable" = lebt)

# 3. Über HTTPS / nginx
curl -sI "https://agiramcp.isarlabs.de/mcp"
# erwartet: 405 Method Not Allowed (HEAD nicht erlaubt) MIT Header
#           "allow: GET, POST, DELETE" und "mcp-session-id" → Endpoint ok
```

Echter Protokoll-Test (irgendein Rechner mit `pip install "mcp[cli]"`):

```python
import asyncio, json
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "https://agiramcp.isarlabs.de/mcp?token=<TOKEN>"

async def main():
    async with streamablehttp_client(URL) as (read, write, _):
        async with ClientSession(read, write) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("Tools:", [t.name for t in tools.tools])
            r = await s.call_tool("list_projects", {})
            projects = (r.structuredContent or {}).get("result") \
                       or [json.loads(c.text) for c in r.content]
            print("Projekte:", len(projects))

asyncio.run(main())
```

> Achtung beim eigenen Parsen: Listen-Tools liefern **pro Element einen
> Content-Block**. `r.content[0]` ist nur das erste Projekt — für die volle
> Liste `r.structuredContent["result"]` nutzen (siehe oben).

---

## 9. Verfügbare Tools

| Tool | Endpoint | |
|------|----------|--|
| `list_projects` | `GET /projects` | lesen |
| `get_project` | `GET /projects/{id}` | lesen |
| `list_open_items` | `GET /items` bzw. `/projects/{id}/open-items` | lesen |
| `get_item` | `GET /items/{id}` | lesen |
| `get_item_context` | `GET /items/{id}/context` (RAG) | lesen |
| `create_item` | `POST /projects/{id}/items` | schreiben |
| `update_item` | `PATCH /items/{id}` | schreiben |

> Projekte anlegen und Löschen sind bewusst **nicht** exponiert (spiegelt die
> API). Bei Bedarf nachrüstbar.

---

## 10. Troubleshooting

| Symptom | Ursache | Lösung |
|---------|---------|--------|
| **421 Misdirected Request** (auch lokal via `--resolve …:127.0.0.1`) | MCP-SDK DNS-Rebinding-Schutz lehnt fremden `Host` ab | `AGIRA_MCP_ALLOWED_HOSTS=<host>` setzen, Dienst neu starten |
| **403 Invalid Origin** | Origin-Header nicht erlaubt | `AGIRA_MCP_ALLOWED_ORIGINS=https://<host>` setzen |
| **406 Not Acceptable** bei `curl …/mcp` | nackter GET ohne MCP-Accept-Header | **Normal** — Endpoint lebt, kein Fehler |
| **405 Method Not Allowed** bei `curl -I` | HEAD wird nicht unterstützt | **Normal** — `allow: GET, POST, DELETE` beachten |
| **500** an der REST-API | `CUSTOMGPT_API_SECRET` in Agira nicht gesetzt | Secret in Agira-Env setzen |
| **400** „requires Agent role" beim Anlegen | Token-User ist kein `Agent` | Rolle auf „Agent" setzen oder anderen User nehmen |
| `No module named 'agira_mcp'` | `-m` aus falschem Verzeichnis | aus `/opt/Agira` starten (`WorkingDirectory`) |
| `No module named 'mcp'` | venv-Mismatch | mit demselben Interpreter installieren: `venv/bin/python -m pip install …` |
| systemd `Result: resources`, „Start request repeated too quickly" | ExecStart-Pfad/`User=`/`EnvironmentFile` falsch | `sudo systemctl reset-failed …` dann `journalctl -u …` lesen; Pfade/User prüfen |
| Connector zeigt nur 1 Projekt | Test-Script schneidet `content[0]` ab | nicht der Server — siehe Parse-Hinweis in §8 |

### Diagnose-Befehle

```bash
# läuft der Dienst, sieht er die Env-Variablen?
PID=$(systemctl show -p MainPID --value agira-mcp.service)
sudo tr '\0' '\n' < /proc/$PID/environ | grep AGIRA_MCP

# lädt die Unit die Env-Datei?
systemctl cat agira-mcp.service | grep -i environment

# lokaler Direkttest am Upstream (umgeht DNS/Proxy)
curl -s -o /dev/null -w "%{http_code}\n" \
  --resolve agiramcp.isarlabs.de:443:127.0.0.1 "https://agiramcp.isarlabs.de/mcp"
```
