# Codex-CLI Spike (Epic „OpenAI als zweiter Provider“, Item 1295)

Ergebnis des Spikes zu Sub-Issue 1/7. Grundlage für 3/7 (Datenmodell), 4/7
(Codex-Provider Umsetzung) und 5/7 (Codex-Provider Review).

Alles hier ist **gemessen** auf dem Test-Host (Ubuntu 24.04.5 LTS, Kernel
6.8.0, VMware-VM, Node v20.20.2, npm 10.8.2) mit **`codex-cli 0.170.0`**,
Auth per API-Key. Was nicht getestet wurde, steht im Abschnitt „Offen“ und ist
dort ausdrücklich als Annahme gekennzeichnet.

## 1. Installation

```bash
npm config set prefix ~/.npm-global      # User-Prefix, kein sudo
npm install -g @openai/codex
codex --version                          # codex-cli 0.170.0
```

- Node 20 genügt für 0.170.0 (keine Engine-Warnung, Start fehlerfrei).
- Der Worker findet `codex` nur, wenn sein `PATH` den npm-Prefix enthält. Läuft
  er per systemd/Cron: vollen Pfad (`~/.npm-global/bin/codex`) konfigurieren.

## 2. Sandbox-Voraussetzungen (wichtig für den Worker-Host)

`--sandbox workspace-write` und `read-only` isolieren über `bubblewrap`
(User-Namespaces).

- Ohne System-`bwrap` warnt Codex („could not find bubblewrap“) und nimmt ein
  mitgeliefertes Binary. Auf Ubuntu 24.04 scheiterte damit jeder Schreibzugriff
  („Failed to write file“), weil AppArmor unprivilegierte User-Namespaces
  blockiert (`kernel.apparmor_restrict_unprivileged_userns = 1`).
- Fix, nur für `/usr/bin/bwrap`, ohne den Host global zu lockern:

  ```bash
  sudo apt-get install -y bubblewrap
  sudo tee /etc/apparmor.d/bwrap >/dev/null <<'EOF'
  abi <abi/4.0>,
  include <tunables/global>

  profile bwrap /usr/bin/bwrap flags=(unconfined) {
    userns,

    include if exists <local/bwrap>
  }
  EOF
  sudo apparmor_parser -r /etc/apparmor.d/bwrap
  bwrap --ro-bind / / --dev /dev --unshare-user true && echo "bwrap ok"
  ```

- Danach schreibt Codex im Workdir erfolgreich (Test: `hello.txt` angelegt und
  selbst verifiziert).
- Rückbau: `sudo rm /etc/apparmor.d/bwrap && sudo apparmor_parser -R /etc/apparmor.d/bwrap`.
- Die Ausnahme erlaubt jedem lokalen User, `bwrap` für Namespaces zu nutzen.
- **Ohne Namespaces** bleibt nur `--dangerously-bypass-approvals-and-sandbox`.
  Das gehört nur in eine isolierte VM/einen Container, nicht auf einen Host, auf
  dem die Anwendung selbst läuft.

## 3. Headless-Aufruf

```bash
echo "<Prompt>" | codex exec --json --sandbox <read-only|workspace-write> -
```

- Prompt über stdin mit `-` funktioniert (kein argv-Größenlimit).
- Mit `--json` ist **stdout reines JSONL**. Die Zeilen `ERROR codex_api::…`
  kommen von stderr (Test mit `2>/dev/null`: nur JSON auf stdout). Der Parser
  liest nur stdout und überspringt trotzdem Nicht-JSON-Zeilen, wie bei Claude.
- Der Textheader (Modell, Sandbox, Session-ID) erscheint ohne `--json`, nicht
  im Stream.
- Standardmodell des Hosts: `gpt-6.2-sol` (nur beobachtet; keine Modellliste
  getestet).

## 4. Event-Format und Zuordnung zu Claude

Beobachtete Events (Beispiele aus echten Läufen):

```jsonl
{"type":"thread.started","thread_id":"01a1ef1a-c3a4-72d0-af71-b8d27295781d"}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"..."}}
{"type":"item.started","item":{"id":"item_1","type":"command_execution","command":"/bin/bash -lc 'ls -la'","aggregated_output":"","exit_code":null,"status":"in_progress"}}
{"type":"item.completed","item":{"id":"item_1","type":"command_execution","command":"...","aggregated_output":"...","exit_code":0,"status":"completed"}}
{"type":"turn.completed","usage":{"input_tokens":29151,"cached_input_tokens":14467,"cache_write_input_tokens":14678,"output_tokens":80,"reasoning_output_tokens":0}}
```

| Codex | Claude-Äquivalent im Worker |
|---|---|
| `thread.started.thread_id` | `system/init.session_id` |
| `item.completed` / `agent_message` | `assistant`-Text; die **letzte** ist das `result_text` |
| `item.started` / `command_execution` (`in_progress`) | `tool_use` (Fortschrittszeile, Tool in flight) |
| `item.completed` / `command_execution` (`exit_code`) | `tool_result` (Tool fertig) |
| `turn.completed` + `usage` | `result` (Lauf zu Ende) |
| `turn.failed` (`error.message`) | `result` mit `is_error` |

Folgen für den Parser:

- Es gibt **kein `result`-Event** und kein Ergebnis-Textfeld. Ende des Laufs ist
  `turn.completed`, der Text die letzte `agent_message`. Fehlt `turn.completed`
  (und `turn.failed`), gilt der Lauf als unvollständig (`saw_result=False`).
- **Keine Kosten (USD) und keine Turn-Zahl** im Stream, nur Token-Usage:
  `input_tokens`, `cached_input_tokens`, `cache_write_input_tokens`,
  `output_tokens`, `reasoning_output_tokens`. `total_cost_usd` bleibt leer
  (oder wird später aus einer Preistabelle berechnet).
- Der Idle-Watchdog verfolgt Tools in flight über `item.id` (started → completed).
- Verbrauch zur Einordnung: ein Trivialauftrag ≈ 15.000 Input-Tokens (großteils
  CLI-Systemprompt), ein Lauf mit `git status` ≈ 44.000.
- Weitere Item-Typen (z. B. Datei-Änderungen, MCP-Aufrufe, Reasoning) wurden
  **nicht** beobachtet. Der Parser muss unbekannte Item-Typen tolerieren.
  Ein `item.completed` mit `type: "error"` kommt vor (z. B. „Falling back from
  WebSockets to HTTPS transport“) und ist **kein** Laufabbruch.

## 5. Authentifizierung

Getestet mit leerem `CODEX_HOME` (ohne `auth.json`), damit der Key allein per
Env wirkt:

| Env | Ergebnis |
|---|---|
| `CODEX_API_KEY=<gültig>` | funktioniert (`ok`, `turn.completed`, Exit 0) |
| `OPENAI_API_KEY=<gültig>` | **wirkungslos**: `401 … Missing bearer or basic authentication`, Exit 1 |
| `OPENAI_API_KEY=sk-bad` | identisch (`Missing bearer…`): es wird gar kein Key gesendet |
| `CODEX_API_KEY=sk-bad` | `401 … Incorrect API key provided … auth error code: invalid_api_key`, Exit 1 |

Entscheidungen:

- Der Worker setzt den Key **ausschließlich als `CODEX_API_KEY`** in der
  Child-Env. `auth.json` ist nicht nötig. Alle anderen OpenAI-/Codex-Variablen
  (`OPENAI_API_KEY`, `CODEX_API_KEY`) werden vorher entfernt, analog zu
  `ALL_AUTH_ENV_VARS` bei Claude.
- Ein `CODEX_HOME` unter `/tmp` wird für Helper-Binaries abgelehnt (Warnung,
  Lauf geht weiter). Falls der Worker ein eigenes Home braucht: Verzeichnis
  unter dem Home des Users.
- **Auth-Fehler erkennen:** Der Lauf endet mit `turn.failed` und Exit-Code 1.
  Die Meldung enthält `401 Unauthorized` und je nach Fall `Missing bearer or
  basic authentication` oder `auth error code: invalid_api_key`.
- **Retry-Verhalten:** Davor erscheinen viele `{"type":"error",…}`-Events
  („Reconnecting… n/5“), erst 5× WebSocket, dann 5× HTTPS. Diese `error`-Events
  sind Zwischenstände, **nicht** das Ende. Der Fehlerlauf dauert grob 20–30 s
  (aus Zeitstempeln geschätzt, nicht exakt gemessen). Der Auth-Fehler sollte
  deshalb erkannt werden, ohne den ganzen Retry-Zyklus abzuwarten, z. B. beim
  ersten `error`-Event mit `401`/`invalid_api_key`.

## 6. Git in der Sandbox

`workspace-write` erlaubt Dateiänderungen im Workdir, aber **`.git` ist
schreibgeschützt**:

- Test: `git add` scheiterte („`.git` schreibgeschützt“). Der Agent meldete das
  ehrlich, es entstand kein Commit.
- Mit `-c 'sandbox_workspace_write.writable_roots=["<repo>/.git"]'` konnten
  `git add` und `git commit` ausgeführt werden (Commit angelegt).

Optionen für den Worker:

1. **Worker committet (Empfehlung):** Der Worker committet nach dem Lauf alles
   (`_commit_uncommitted_work` wird für Codex zur Regel), mit
   Conventional-Commit-Nachricht und Agira-ID (`feat(#<id>): <Titel>`). Der
   Agent bekommt keinen Schreibzugriff auf `.git` (Hooks!). Im Epic-Modus wird
   ohnehin je Sub-Issue ein Squash-Commit erzeugt.
2. `writable_roots` auf `.git`: funktioniert, macht aber Hooks für den Agenten
   schreibbar. Nur mit bewusster Entscheidung.
3. Bypass der Sandbox: siehe Abschnitt 2, nicht auf Hosts mit der Anwendung.

Folge für `hint.py`/Prompt: Für Codex-Läufe nicht „committe selbst“ verlangen.

## 7. Review (read-only)

`--sandbox read-only` erlaubt lesende Befehle (`ls -la`, `git status`) und
schreibt nichts. Ob lesende Git-Befehle wie `git diff`/`git log` reichen, wurde
mit `git status` indirekt belegt; ein Review-Prompt mit Diff wurde **nicht**
durchgespielt.

## 8. Empfohlene Argumentlisten (Entwurf, nicht vollständig getestet)

Umsetzung:

```
codex exec --json --sandbox workspace-write -        # Prompt via stdin
```

Review:

```
codex exec --json --sandbox read-only -              # Prompt via stdin
```

Env für beide: `CODEX_API_KEY=<Key des Job-Users oder host-weit>`, kein
`OPENAI_API_KEY`. Arbeitsverzeichnis wie bei Claude per `cwd` des Subprozesses
(die CLI-Option `-C` wurde nicht getestet).

## 9. Offen (nicht getestet, nur Annahmen)

- **Limit-/Rate-Limit-Fehler:** Text und ob eine Reset-Zeit geliefert wird,
  nicht beobachtet. Marker und Park-Logik (`WAITING_LIMIT`) erst nach echtem
  Fall festlegen.
- **SIGINT/Watchdog:** Verhalten bei Abbruch (Grace-Zeit, finales Event) nicht
  getestet.
- **`--output-schema` / `--output-last-message`:** Existenz und Verhalten in
  0.170.0 nicht geprüft. Bis dahin Fallback `parse_review_verdict` auf der
  letzten `agent_message`.
- **`AGENTS.md`:** Wird sie gelesen, genügt ein Symlink auf `CLAUDE.md`? Nicht
  getestet.
- **Modellflag und Modellliste:** `-m` und konkrete Modell-IDs für 3/7 nicht
  getestet (beobachtet nur das Standardmodell `gpt-6.2-sol`).
- **Netzwerk in der Sandbox** (z. B. Paketinstallation, Tests mit Netz) und ein
  echter Django-Testlauf in `workspace-write` nicht getestet. Push und `gh`
  laufen über den Worker außerhalb der Sandbox.
- **Weitere Item-Typen** im Stream (Datei-Änderungen, MCP, Reasoning).

## 10. Hinweise an die Folge-Issues

- **3/7:** Key-Feld und Env-Name `CODEX_API_KEY`; Modellliste erst nach einem
  Test von `-m` und der verfügbaren Modelle füllen.
- **4/7:** Worker committet für Codex (Abschnitt 6); Parser nach Abschnitt 4;
  Auth-Fehler früh erkennen (Abschnitt 5); `OPENAI_API_KEY` aus der Env
  entfernen.
- **5/7:** `--output-schema` zuerst prüfen; sonst `parse_review_verdict`.
- **7/7 (Einrichtungsdoku):** `bubblewrap` und AppArmor-Profil für Ubuntu 24.04,
  `PATH`/Pfad zu `codex` für den Worker.
