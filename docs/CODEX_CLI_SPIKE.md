# Codex-CLI-Spike (Epic #1294, Sub-Issue #1295)

Prüft die Annahmen des Epics „OpenAI Codex als zweiter Provider der Agent-Queue“
gegen die echte Codex-CLI. Kein Produktivcode.

## Status dieses Dokuments – bitte zuerst lesen

**Die Messungen mit der echten CLI stehen noch aus.** Die Umgebung, in der der
Spike bearbeitet wurde (headless Claude-Worker-Lauf), hatte

- keine installierte Codex-CLI (`codex: command not found`),
- kein Node/npm (Installation via `npm i -g @openai/codex` nicht möglich),
- keinen `OPENAI_API_KEY` / `CODEX_API_KEY`.

Es wurden deshalb **keine Events aufgezeichnet und keine Versionsnummer
ermittelt**. Erfundene „Beobachtungen“ wären für 4/5 schädlicher als Lücken.
Dieses Dokument enthält daher:

1. pro Punkt die **Annahme** (aus dem Epic bzw. aus der Codex-Dokumentation, aus
   dem Gedächtnis, **nicht verifiziert**),
2. das **Messprotokoll** (exakte Kommandos), mit dem ein Mensch auf einer Maschine
   mit CLI + Key jede Zeile in <1 h verifiziert,
3. eine **Ergebnisspalte `Beobachtet`**, die beim Ausfüllen die Annahme ersetzt.

> **Akzeptanzkriterien dieses Issues sind damit nicht erfüllt**, solange die
> Spalte „Beobachtet“ leer ist. 4/5 dürfen die Annahmen unten nicht als
> gesichert behandeln.

CLI-Version: **_offen_** (`codex --version` eintragen).
Datum/Maschine/Auth: **_offen_**.

## Worker-Seite (Ist, aus dem Repo – verifiziert)

Der Claude-Pfad in `core/management/commands/run_claude_worker.py` setzt voraus:

- Prozess mit stdout-Eventstrom (`--output-format stream-json`), Zeile = JSON.
- Idle-Watchdog: ohne Event → ein `SIGINT`, dann `INTERRUPT_GRACE_SECONDS = 30`
  für ein finales Result-Event; zweiter Idle → Kill.
- Usage-Limit-Erkennung per Substring-Liste (`usage limit`, `rate_limit`, …) mit
  Backoff bis zum Reset; separate Substrings für kaputte Credentials.
- Prompt-Weitergabe, Arbeitsverzeichnis = Checkout, Git/`gh` durch Claude selbst
  (Commit, Push, PR-Draft); Merge macht der Worker.

## Messprotokoll und Annahmen

Vorbereitung (Wegwerf-Verzeichnis, nicht im Repo):

```bash
export WORK=$(mktemp -d); cd "$WORK"
git clone <agira-testclone> repo && cd repo && git checkout -b spike/codex
codex --version
export CODEX_API_KEY=sk-...   # siehe Abschnitt Auth
```

### 1. Headless-Aufruf

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

### 2. JSONL-Events

Annahme: Events der Art `thread.started`, `turn.started`, `item.started/updated/
completed` (Item-Typen u. a. `agent_message`, `reasoning`, `command_execution`,
`file_change`, `mcp_tool_call`, `web_search`, `todo_list`), `turn.completed`,
`turn.failed`, `error`. Schemanamen sind versionsabhängig.

Aufzeichnen (jeweils vollständig nach `docs/`-Anhang kopieren, Secrets schwärzen):

```bash
# a) Umsetzung (workspace-write)
echo "<echte kleine Aufgabe inkl. Test>" | codex exec --json -s workspace-write - > impl.jsonl
# b) Review read-only mit Schema
echo "<Review-Prompt>" | codex exec --json -s read-only \
  --output-schema review_schema.json -o last.json - > review.jsonl
# c) Fehlerfälle: falscher Key, kein Key, ungültiges Modell, Schema-Verletzung
```

Beobachtet: _offen_ – Event-Beispiele (Umsetzung, Review, je ein Fehlerfall) hier
einfügen. Fragen: Gibt es ein dediziertes Abschluss-Event (Gegenstück zum
Claude-`result`)? Wie erkennt der Worker Erfolg vs. Fehler (Exit-Code, `turn.failed`)?

### 3. Token-Usage

Annahme: `turn.completed` enthält `usage` mit `input_tokens`,
`cached_input_tokens`, `output_tokens` (ggf. `reasoning_output_tokens`).
**Keine Kosten (USD) und keine Turn-Zahl** wie beim Claude-`result`-Event → Kosten
müssten aus Token × Preistabelle berechnet werden; Turns = Anzahl `turn.completed`.

Beobachtet: _offen_ (Feldnamen, Summe über mehrere Turns oder kumulativ?).

### 4. Sandbox

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
| Datei schreiben im Repo | _offen_ |
| `git add && git commit` | _offen_ |
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

### 5. Read-only Review

Annahme: `--sandbox read-only` erlaubt Dateilesen und lesende Git-Befehle
(`git log/diff/show`), verbietet Schreiben. Zu prüfen: `git status` (schreibt
ggf. Index-Lock → Fehler?), `gh pr view` (Netzwerk!), Schreibversuch wird
abgelehnt und im Event-Strom sichtbar. Review-Urteil als JSON per
`--output-schema` erzwingen (strukturiertes `pass|deviations`).

Beobachtet: _offen_.

### 6. AGENTS.md

Annahme: Codex liest `AGENTS.md` im Repo-Root (und Unterverzeichnissen, auch
`~/.codex/AGENTS.md`); `CLAUDE.md` wird **nicht** gelesen. Symlink
`AGENTS.md -> CLAUDE.md` sollte funktionieren (Git speichert Symlinks; auf
Windows-Checkouts problematisch). Es gibt ein Größenlimit (`project_doc_max_bytes`,
Default 32 KiB) – `CLAUDE.md` ist derzeit deutlich kleiner, prüfen.
Test: Marker-Regel in AGENTS.md („Antworte immer mit dem Wort BANANE“) und
Symlink-Variante einzeln ausprobieren.

Beobachtet: _offen_.

### 7. Auth

Annahme: `codex exec` akzeptiert `CODEX_API_KEY` (nur für `exec`);
`OPENAI_API_KEY` wird je nach Version nur über `codex login --with-api-key`
bzw. vorhandene `~/.codex/auth.json` genutzt, nicht automatisch aus dem Env.
Zu testen: (a) nur `OPENAI_API_KEY`, (b) nur `CODEX_API_KEY`, (c) beide,
(d) keiner, (e) falscher Key; jeweils Exit-Code und Fehlertext (stderr/JSONL)
notieren. Wichtig für 4: ein vorhandenes `~/.codex/auth.json` (ChatGPT-Login)
kann den Env-Key überstimmen → dedizierten `CODEX_HOME` pro Worker setzen.

Beobachtet: _offen_ (Tabelle a–e mit Fehlertexten; daraus Substring-Liste für
„kaputte Credentials“ ableiten, analog zum Claude-Pfad).

### 8. Limit-/Rate-Limit-Fehler

Annahme: API-Key-Betrieb liefert HTTP 429 (`rate_limit_exceeded`,
`insufficient_quota`) mit Text à la „Rate limit reached … Please try again in
1.2s“; **kein Reset-Zeitstempel wie bei Claude-Subscription-Limits**, höchstens
eine relative Wartezeit im Text; bei ChatGPT-Login (Plan-Limits) andere Texte
(„You've hit your usage limit … try again at …“). `insufficient_quota`
(Guthaben leer) ist kein temporäres Limit → eigener Fall, kein Backoff-Retry.
CLI retryt 429 intern mehrfach, bevor sie fehlschlägt.

Beobachtet: _offen_. Praktisch: Limit mit sehr niedrigem Projekt-Limit oder
Parallel-Last provozieren, Text + Event + Exit-Code festhalten.

### 9. Exit-Codes und SIGINT

Annahme: Exit 0 bei Erfolg, ≠0 bei Fehler (Auth, Netz, `turn.failed`). Bei
SIGINT beendet sich die CLI ohne garantiertes finales Event; evtl. Exit 130.
Zu messen: SIGINT mitten im Lauf (`kill -INT`): Exit-Code, kommt ein
`turn.failed`/Abschluss-Event, bleiben Kindprozesse (Tests, git) übrig
(Prozessgruppe!), wie lange dauert das Beenden (Grace 30 s ausreichend?), wird
`-o last.json` trotzdem geschrieben (wohl nicht).

Beobachtet: _offen_.

### 10. Modelle

Annahme (unsicher, Stand Wissen): Coding-Modelle der GPT-5-Codex-Linie
(`gpt-5-codex`, spätere Nachfolger `gpt-5.x-codex`), kleines/billiges Modell für
leichte Aufgaben (`gpt-5-codex-mini`/`-mini`); Reasoning-Aufwand per
`-c model_reasoning_effort=low|medium|high`. IDs ändern sich oft → Auswahl in
Agira konfigurierbar halten, nicht hart verdrahten. Zu messen: Welche IDs akzeptiert
der verwendete Key (`codex exec -m <id> "ping"`), Fehlertext bei unbekanntem
Modell.

Beobachtet: _offen_.

## Vorläufige Argumentlisten (zu verifizieren)

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

## Hinweise an 4/5 (Risiken der Epic-Annahmen)

Bis zur Verifikation als Risiken führen, nicht als Fakten:

1. **Git/Netz in `workspace-write`**: Commit/Push/`gh` könnten scheitern → Entscheidung
   Sandbox-Modus (bypass vs. Worker übernimmt Git) vor Implementierung treffen.
2. **Kein Kosten-/Turn-Feld**: Kosten aus Tokens berechnen; Schema für Job-Felder
   anpassen.
3. **Kein Subscription-Reset-Zeitpunkt**: Backoff-Logik braucht Fallback (feste
   Wartezeit / relative Zeit aus Text); `insufficient_quota` separat behandeln.
4. **Eventformat unterscheidet sich** von Claude `stream-json` → eigener Parser;
   Format gegen die tatsächlich eingesetzte CLI-Version pinnen (Version im
   Worker loggen).
5. **`AGENTS.md`** fehlt im Repo; Symlink auf `CLAUDE.md` anlegen (CLAUDE.md nennt
   sich „einzige Quelle der Wahrheit“ – Symlink erhält das).
6. **Auth-Isolation** per `CODEX_HOME`; Env-Key-Vorrang prüfen.
7. **SIGINT/Grace**: erst mit Messung (Punkt 9) entscheiden, ob 30 s und ein
   einmaliges SIGINT passen; ggf. Prozessgruppen-Kill.

## Offene Aufgabe

Messprotokoll durchführen, „Beobachtet“-Zellen und Event-Anhänge füllen,
CLI-Version nennen, danach Status-Abschnitt oben entfernen und 4/5 anpassen.
