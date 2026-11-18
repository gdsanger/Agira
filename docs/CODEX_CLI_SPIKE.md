# Codex-CLI-Spike (Epic #1294, Sub-Issue #1295)

Prüft die Annahmen des Epics „OpenAI Codex als zweiter Provider der Agent-Queue“
gegen die echte Codex-CLI. Kein Produktivcode. Grundlage für 4/7 (Codex-Provider
Umsetzung) und 5/7 (Codex-Provider Review).

## Status dieses Dokuments

Die Abschnitte 1–8 und 9.1–9.5 sind **gemessen** (manuell auf einem Host mit
CLI und API-Key). Die frühere Fassung dieses Dokuments (Annahmen und
Messprotokoll, aus einem headless Worker-Lauf ohne CLI/Node/Key) ist in 9.6 und
9.7 für die **noch offenen Punkte** erhalten. Dort gelten weiterhin nur
**Annahmen**; sie sind nicht verifiziert und dürfen nicht als gesichert behandelt
werden.

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

## Worker-Seite (Ist, aus dem Repo – verifiziert)

Der Claude-Pfad in `core/management/commands/run_claude_worker.py` setzt voraus:

- Prozess mit stdout-Eventstrom (`--output-format stream-json`), Zeile = JSON.
- Idle-Watchdog: ohne Event → ein `SIGINT`, dann `INTERRUPT_GRACE_SECONDS = 30`
  für ein finales Result-Event; zweiter Idle → Kill.
- Usage-Limit-Erkennung per Substring-Liste (`usage limit`, `rate_limit`, …) mit
  Backoff bis zum Reset; separate Substrings für kaputte Credentials.
- Prompt-Weitergabe, Arbeitsverzeichnis = Checkout, Git/`gh` durch Claude selbst
  (Commit, Push, PR-Draft); Merge macht der Worker.

## 9. Zweite Messrunde (gemessen) und Rest

Gleicher Host und CLI-Version wie oben (`codex-cli 0.170.0`), `CODEX_API_KEY`
per Env, eigenes `CODEX_HOME`.

### 9.1 Flags (gemessen)

`codex exec --help` kennt alle benötigten Optionen: `-c/--config`,
`-m/--model`, `-s/--sandbox`, `-C/--cd`, `--skip-git-repo-check`,
`--ephemeral`, `--output-schema`, `--json`, `-o/--output-last-message`.
`-C <dir>` zusammen mit `-c model_reasoning_effort=low` lief erfolgreich
(`ok`, `turn.completed`).

### 9.2 Modelle (gemessen, teils offen)

Die Modellliste des Keys (`GET /v1/models`, erste 60 sortierte IDs, daher
unvollständig) enthält u. a. `gpt-5.3-codex`, `gpt-5.4` (`-mini`, `-nano`,
`-pro`), `gpt-5.5` (`-pro`), `gpt-5.6-luna/-sol/-terra`, `gpt-6-astra/-luna/-sol`,
`gpt-6.1-sol/-terra`, `gpt-6.2-astra/-sol`. **`gpt-5-codex` und
`gpt-5-codex-mini` sind in dieser Liste nicht enthalten** (sie müssten vor
`gpt-5-mini` stehen). Das CLI-Standardmodell des Hosts ist `gpt-6.2-sol`
(Header von `codex exec`).

Ein unbekanntes Modell (`-m gibt-es-nicht`) liefert auf stdout einen sauberen
Fehlerstrom, Exit-Code 1:

```jsonl
{"type":"thread.started","thread_id":"…"}
{"type":"item.completed","item":{"id":"item_0","type":"error","message":"Model metadata for `gibt-es-nicht` not found. Defaulting to fallback metadata; this can degrade performance and cause issues."}}
{"type":"turn.started"}
{"type":"error","message":"The model `gibt-es-nicht` does not exist or you do not have access to it."}
{"type":"turn.failed","error":{"message":"The model `gibt-es-nicht` does not exist or you do not have access to it."}}
```

Der Fehler ist über `turn.failed` erkennbar (Text „does not exist or you do not
have access to it“), nicht über ein fehlendes Ergebnis-Event. Eine erste
Messrunde mit `2>/dev/null` zeigte dazu keine Ausgabe; das war nicht
reproduzierbar und ist durch diese Messung ersetzt.

### 9.3 Sandbox: Netzwerk, `gh`, Tests (gemessen)

Prompt: drei Befehle (`curl https://github.com`, `gh auth status`,
`python3 -c "import django"`) in drei Modi.

| Modus | `curl github.com` | `gh auth status` | `import django` |
|---|---|---|---|
| `workspace-write` (Standard) | `Could not resolve host`, Exit 6 | „token invalid“ (Exit 0, irreführend: ohne Netz nicht prüfbar) | `6.1.2` |
| `workspace-write` + `-c sandbox_workspace_write.network_access=true` | HTTP 200 | „Logged in“, Scopes `gist, read:org, repo, workflow` | `6.1.2` |
| `--dangerously-bypass-approvals-and-sandbox` | HTTP 200 | „Logged in“ | `6.1.2` |

- Ohne `network_access=true` hat die Sandbox **kein DNS**. Ein `gh`-Befehl
  schlägt dort unzuverlässig fehl; `gh auth status` meldet fälschlich einen
  ungültigen Token.
- Ein Django-Testlauf (`manage.py test … --settings=agira.test_settings`, SQLite)
  **läuft in der Sandbox** (Testdatenbank wurde angelegt, 8 Tests gefunden). Er
  brach im Testclone an einem Migrationskonflikt ab (`0083_merge_20261007_0824`
  gegen `0091_agent_queue_job_verbose_name`). Diese Migration existiert nur in der
  lokalen Historie von `/opt/Agira`, nicht auf `origin/main`; der Fehler hat mit
  Codex nichts zu tun.
- `git push` wurde bewusst nicht getestet (ein Push nach `origin` würde einen
  echten Branch anlegen; der Worker pusht außerhalb des Agentenlaufs).

### 9.4 Read-only Review (gemessen)

- `--sandbox read-only` erlaubt `git log`, `git status` und `git diff` (auch
  ein sehr großer Diff kam vollständig in `aggregated_output` zurück).
- Ein Schreibversuch (`x.txt`) wurde abgelehnt („schreibgeschütztes
  Dateisystem“), die Datei wurde nicht angelegt.
- `--output-schema <file> -o <file>` funktioniert: `last.json` enthielt genau
  ein JSON-Objekt nach dem Schema (Test mit `verdict` und `summary`).

### 9.5 `AGENTS.md` (gemessen)

Mit `AGENTS.md` als Symlink auf `CLAUDE.md` (Regel: „Antworte immer nur mit dem
Wort BANANE“) antwortete Codex `BANANE`; nach dem Entfernen des Symlinks normal
(`1 + 1 = 2.`). Ein Symlink genügt, `CLAUDE.md` allein wird nicht gelesen.

### 9.6 Limit-/Rate-Limit-Fehler (offen)

Annahme: API-Key-Betrieb liefert HTTP 429 (`rate_limit_exceeded`,
`insufficient_quota`) mit Text à la „Rate limit reached … Please try again in
1.2s“; **kein Reset-Zeitstempel wie bei Claude-Subscription-Limits**, höchstens
eine relative Wartezeit im Text; bei ChatGPT-Login (Plan-Limits) andere Texte
(„You've hit your usage limit … try again at …“). `insufficient_quota`
(Guthaben leer) ist kein temporäres Limit → eigener Fall, kein Backoff-Retry.
CLI retryt 429 intern mehrfach, bevor sie fehlschlägt.

Beobachtet: _offen_. Praktisch: Limit mit sehr niedrigem Projekt-Limit oder
Parallel-Last provozieren, Text + Event + Exit-Code festhalten.

### 9.7 Exit-Codes und SIGINT (offen)

Annahme: Exit 0 bei Erfolg, ≠0 bei Fehler (Auth, Netz, `turn.failed`). Bei
SIGINT beendet sich die CLI ohne garantiertes finales Event; evtl. Exit 130.
Zu messen: SIGINT mitten im Lauf (`kill -INT`): Exit-Code, kommt ein
`turn.failed`/Abschluss-Event, bleiben Kindprozesse (Tests, git) übrig
(Prozessgruppe!), wie lange dauert das Beenden (Grace 30 s ausreichend?), wird
`-o last.json` trotzdem geschrieben (wohl nicht).

Beobachtet: _offen_.

### 9.8 Noch offen

- Limit-/Rate-Limit-Text und Reset-Zeit (9.6), SIGINT und Kindprozesse (9.7).
- Vollständige Modellliste (nur die ersten 60 IDs wurden gelesen) und welche
  davon für die Queue taugen.
- `-o` bei einem Umsetzungslauf, `git push` aus dem Lauf.

## 10. Abgleich mit dem Code auf `main`

Der Worker hat 3/7 bis 7/7 bereits auf Basis der früheren Annahmen umgesetzt
(`providers/codex.py`, `models.py`). Die Messungen bestätigen das meiste und
zeigen zwei Punkte zum Nachziehen.

**Bestätigt:**

- `CODEX_API_KEY` wird gesetzt (zusätzlich `OPENAI_API_KEY`, harmlos), fremde
  OpenAI-/Codex-Variablen werden entfernt, `CODEX_HOME` liegt unter
  `REPO_BASE_DIR` und nicht unter `/tmp` (Abschnitt 5).
- Event-Parser: `thread.started`, `item.*`, `turn.completed`/`turn.failed`,
  tolerante `error`-Events und Nicht-JSON-Zeilen entsprechen Abschnitt 4.
- Review: `-s read-only`, `--output-schema`, `-o`, Fallback auf die letzte
  `agent_message` (9.4).
- `AGENTS.md` als Symlink auf `CLAUDE.md` genügt (9.5).
- Fehler bei unbekanntem Modell kommt als `turn.failed` mit Klartext (9.2); der
  Parser setzt ihn als `result_text`, der Job schlägt mit dieser Meldung fehl.
- Umsetzung mit `--dangerously-bypass-approvals-and-sandbox`: nötig, weil
  `workspace-write` kein Netzwerk hat und `.git` nicht beschreibbar ist
  (Abschnitt 6, 9.3). Der Worker-Host ist dann die Isolationsgrenze.

**Nachziehen:**

1. **Modell-IDs.** `OpenAIQueueJobModel` kennt nur `gpt-5-codex` und
   `gpt-5-codex-mini`; beide fehlen in der (gekürzten) Modellliste des Keys
   (9.2). Ein Lauf mit einer nicht vorhandenen ID scheitert mit „does not exist
   or you do not have access to it“. Die IDs müssen aus der tatsächlich
   verfügbaren Liste kommen (CLI-Standard des Hosts: `gpt-6.2-sol`).
2. **Netzwerk im Review.** `read-only` hat kein Netzwerk. `gh`-Aufrufe im
   Review-Lauf scheitern; der Review darf nur auf den Checkout und den
   mitgelieferten Diff bauen (so ist der Prompt heute schon aufgebaut).

Offene Messungen: 9.6 bis 9.8.
