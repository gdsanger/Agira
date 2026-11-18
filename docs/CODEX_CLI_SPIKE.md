# Codex-CLI-Spike (Epic #1294, Sub-Issue #1295)

Prüft die Annahmen des Epics „OpenAI Codex als zweiter Provider der Agent-Queue“
gegen die echte Codex-CLI. Kein Produktivcode. Grundlage für 4/7 (Codex-Provider
Umsetzung) und 5/7 (Codex-Provider Review).

## Status dieses Dokuments

Die Abschnitte 1–8 sind **gemessen** (manuell auf einem Host mit CLI und
API-Key). Die frühere Fassung dieses Dokuments (Annahmen und Messprotokoll, aus
einem headless Worker-Lauf ohne CLI/Node/Key) ist in Abschnitt 9 für die
**noch offenen Punkte** erhalten. Dort gelten weiterhin nur **Annahmen**; sie
sind nicht verifiziert und dürfen von 4/5 nicht als gesichert behandelt werden.

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

## 9. Noch offen: Messprotokoll (Annahmen, nicht verifiziert)

Pro Punkt die Annahme aus der früheren Fassung und das, was noch zu messen ist. Vorbereitung wie in Abschnitt 3; der Key kommt als `CODEX_API_KEY` (Abschnitt 5).

### 9.1 Weitere Flags

Annahme: `codex exec` liest den Prompt von stdin, wenn das Prompt-Argument `-`
ist oder fehlt; relevante Flags: `-m/--model`, `-s/--sandbox
{read-only|workspace-write|danger-full-access}`, `--json` (JSONL auf stdout),
`-o/--output-last-message <file>`, `--output-schema <file>`,
`-C/--cd <dir>`, `--skip-git-repo-check`, `-c key=value` (Config-Override),
`--ephemeral`. Fortschritt/Logs gehen auf stderr, nur das Ergebnis auf stdout.

```bash
echo "Lege Datei x.txt mit Inhalt hi an" | codex exec --json -s workspace-write -C . - \
  > events.jsonl 2> stderr.log; echo "exit=$?"
```

Beobachtet: _offen_ (Flags aus `codex exec --help` kopieren; prüfen, ob `-` nötig
ist; ob `--json` stderr-Ausgaben unterdrückt).

### 9.2 Sandbox: Netzwerk, Push, Tests

Annahmen für `workspace-write`: Schreiben nur im Arbeitsverzeichnis (+ tmp);
`.git` ist je nach Version **schreibgeschützt** → `git commit` scheitert eventuell;
Netzwerk standardmäßig **aus** (→ `git push`, `gh`, `pip install` scheitern);
Konfigurierbar über `-c sandbox_workspace_write.network_access=true`. Der
Worker-Flow (Commit/Push/`gh pr create`) wäre damit ohne Anpassung nicht
lauffähig. Alternative `--dangerously-bypass-approvals-and-sandbox` (`--yolo`):
volle Rechte; nur in einem externen Container/VM-Isolat vertretbar, dort aber
einfachste Variante. Alternative C: Codex nur Code ändern lassen, Commit/Push/PR
macht der Worker (Abweichung vom Claude-Pfad, aber robust).

Zu messen (je Ergebnis + Fehlertext):

| Test (in `workspace-write`) | Beobachtet |
|---|---|
| Datei schreiben im Repo | **beobachtet:** funktioniert (mit `bubblewrap` + AppArmor-Profil, Abschnitt 2) |
| `git add && git commit` | **beobachtet:** `.git` schreibgeschützt, `git add` scheitert; mit `writable_roots` auf `.git` gelingt der Commit (Abschnitt 6) |
| `git push` | _offen_ |
| `gh pr list` / `gh auth status` | _offen_ |
| `python manage.py test … --settings=agira.test_settings` (SQLite) | _offen_ |
| `pip install`/DNS | _offen_ |
| Gleiche Tests mit `network_access=true` | _offen_ |
| Gleiche Tests mit `--dangerously-bypass-approvals-and-sandbox` | _offen_ |

Auf Linux zusätzlich prüfen: Landlock/seccomp verfügbar im Worker-Container
(Sandbox kann in Containern ohne Rechte fehlschlagen).
Approvals: headless muss `approval_policy=never` greifen (`exec` ist
nicht-interaktiv; mit `-c approval_policy=never` absichern).

### 9.3 Read-only Review mit Diff und Schema

Annahme: `--sandbox read-only` erlaubt Dateilesen und lesende Git-Befehle
(`git log/diff/show`), verbietet Schreiben. Zu prüfen: `git status` (schreibt
ggf. Index-Lock → Fehler?), `gh pr view` (Netzwerk!), Schreibversuch wird
abgelehnt und im Event-Strom sichtbar. Review-Urteil als JSON per
`--output-schema` erzwingen (strukturiertes `pass|deviations`).

Beobachtet: _offen_.

### 9.4 AGENTS.md

Annahme: Codex liest `AGENTS.md` im Repo-Root (und Unterverzeichnissen, auch
`~/.codex/AGENTS.md`); `CLAUDE.md` wird **nicht** gelesen. Symlink
`AGENTS.md -> CLAUDE.md` sollte funktionieren (Git speichert Symlinks; auf
Windows-Checkouts problematisch). Es gibt ein Größenlimit (`project_doc_max_bytes`,
Default 32 KiB) – `CLAUDE.md` ist derzeit deutlich kleiner, prüfen.
Test: Marker-Regel in AGENTS.md („Antworte immer mit dem Wort BANANE“) und
Symlink-Variante einzeln ausprobieren.

Beobachtet: _offen_.

### 9.5 Limit-/Rate-Limit-Fehler

Annahme: API-Key-Betrieb liefert HTTP 429 (`rate_limit_exceeded`,
`insufficient_quota`) mit Text à la „Rate limit reached … Please try again in
1.2s“; **kein Reset-Zeitstempel wie bei Claude-Subscription-Limits**, höchstens
eine relative Wartezeit im Text; bei ChatGPT-Login (Plan-Limits) andere Texte
(„You've hit your usage limit … try again at …“). `insufficient_quota`
(Guthaben leer) ist kein temporäres Limit → eigener Fall, kein Backoff-Retry.
CLI retryt 429 intern mehrfach, bevor sie fehlschlägt.

Beobachtet: _offen_. Praktisch: Limit mit sehr niedrigem Projekt-Limit oder
Parallel-Last provozieren, Text + Event + Exit-Code festhalten.

### 9.6 Exit-Codes und SIGINT

Annahme: Exit 0 bei Erfolg, ≠0 bei Fehler (Auth, Netz, `turn.failed`). Bei
SIGINT beendet sich die CLI ohne garantiertes finales Event; evtl. Exit 130.
Zu messen: SIGINT mitten im Lauf (`kill -INT`): Exit-Code, kommt ein
`turn.failed`/Abschluss-Event, bleiben Kindprozesse (Tests, git) übrig
(Prozessgruppe!), wie lange dauert das Beenden (Grace 30 s ausreichend?), wird
`-o last.json` trotzdem geschrieben (wohl nicht).

Beobachtet: _offen_.

### 9.7 Modelle

Annahme (unsicher, Stand Wissen): Coding-Modelle der GPT-5-Codex-Linie
(`gpt-5-codex`, spätere Nachfolger `gpt-5.x-codex`), kleines/billiges Modell für
leichte Aufgaben (`gpt-5-codex-mini`/`-mini`); Reasoning-Aufwand per
`-c model_reasoning_effort=low|medium|high`. IDs ändern sich oft → Auswahl in
Agira konfigurierbar halten, nicht hart verdrahten. Zu messen: Welche IDs akzeptiert
der verwendete Key (`codex exec -m <id> "ping"`), Fehlertext bei unbekanntem
Modell.

Beobachtet: _offen_.

### 9.8 Vorläufige Argumentlisten der früheren Fassung (zu verifizieren)

Die in Abschnitt 8 genannten, gemessenen Listen haben Vorrang; diese hier enthalten zusätzlich ungetestete Flags.

Umsetzung:

```
codex exec --json -m <model> -C <checkout> \
  -s workspace-write -c approval_policy=never \
  -c sandbox_workspace_write.network_access=true \
  -o <tmp>/last_message.txt -        # Prompt via stdin
```
(Falls `.git` read-only bleibt: Commit/Push/PR im Worker oder
`--dangerously-bypass-approvals-and-sandbox` in isolierter Umgebung.)

Review (read-only):

```
codex exec --json -m <model> -C <checkout> \
  -s read-only -c approval_policy=never \
  --output-schema <review_schema.json> -o <tmp>/verdict.json -
```

Env: `CODEX_API_KEY`, `CODEX_HOME=<pro Worker>`.

## 10. Hinweise an die Folge-Issues

Aus den Messungen (Abschnitte 1–8):

- **3/7 (bereits auf `main`):** Env-Name des Keys ist `CODEX_API_KEY`;
  `OPENAI_API_KEY` wirkt bei `codex exec` nicht. Modellliste erst nach Test von
  `-m` und den verfügbaren Modellen (9.7) füllen.
- **4/7:** Worker committet für Codex (Abschnitt 6); Parser nach Abschnitt 4;
  Auth-Fehler früh erkennen (Abschnitt 5); `OPENAI_API_KEY` aus der Env
  entfernen.
- **5/7:** `--output-schema` zuerst prüfen (9.3); sonst `parse_review_verdict`
  auf der letzten `agent_message`.
- **7/7 (Einrichtungsdoku):** `bubblewrap` und AppArmor-Profil für Ubuntu 24.04,
  `PATH` bzw. Pfad zu `codex` für den Worker.

Risiken aus der früheren Fassung, die **weiter offen** sind (Messungen in
Abschnitt 9): Netzwerk in der Sandbox, kein Reset-Zeitpunkt bei Limits
(`insufficient_quota` separat behandeln), SIGINT/Grace-Zeit und Prozessgruppen,
`AGENTS.md`-Symlink.
