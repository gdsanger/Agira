# CLAUDE.md – Regeln für die Arbeit an Agira

Diese Datei ist die **einzige Quelle der Wahrheit** für Git-Workflow und
Arbeitsweise von Claude in diesem Repository. Der Claude-Queue-Worker
(`core/management/commands/run_claude_worker.py`) und der Git-Workflow-Hinweis
am Item (`core/services/claude_queue/hint.py`) setzen dieselben Regeln um und
dürfen ihr nicht widersprechen. Wer eine Regel ändert, ändert sie hier **und**
im Code, nicht nur an einer Stelle.

Detail- und Hintergrunddoku zum Epic-Modus: `docs/EPIC_BRANCH_WORKFLOW.md`.

## Projekt

- Django-App (Python 3.13), Hauptmodule unter `core/`.
- Sprache in UI, Doku, Commit-Bodys und PR-Texten: Deutsch. Code-Bezeichner
  und Kommentare: Englisch, im Stil des umgebenden Codes.

## Git-Workflow (Einzel-Issue – der Normalfall)

1. Feature-Branch **von `main`**, niemals direkt auf `main` committen.
2. PR gegen `main`, **immer als Draft** eröffnen.
3. Wenn die Arbeit sauber fertig ist, wird der PR auf *ready for review*
   gesetzt. **Review und Merge nach `main` macht ein Mensch.**
4. Nach dem Merge wechselt das Item auf `Testing` („Implemented“).

## Epic-Modus (Ausnahme von „Branch immer von `main`“)

Ein Item mit Sub-Issues ist ein **Epic**: eine vertikale Scheibe in Schichten
(Datenmodell → Logik → UI). Die Sub-Issues werden **sequenziell** abgearbeitet,
mit **genau einem menschlichen Review – am Epic-PR nach `main`**.

- **Epic-Branch:** `feature/<epic-id>-<slug>`, abgeleitet vom Epic-Item, von
  `main` abgezweigt. Er bleibt ohne Branch-Protection.
- **Sub-Issue-Branch:** zweigt vom **Epic-Branch** ab (nicht von `main`, nicht
  von einem anderen Sub-Issue). Der PR geht **als Draft gegen den
  Epic-Branch**.
- **Reihenfolge:** strikt nach `epic_order` (bei Gleichstand Item-ID). Ein
  Sub-Issue startet erst, wenn alle Vorgänger im Epic-Branch gemergt sind.
- **Merge in den Epic-Branch macht der Worker**, nicht Claude. Erst nach einem
  sauberen Lauf und deterministisch:
  ```
  gh pr ready <nr>
  gh pr checks <nr> --watch --fail-fast
  gh pr merge <nr> --squash --delete-branch
  ```
  Erst danach startet das nächste Sub-Issue, auf dem aktualisierten Epic-Branch.
  **Claude merged nie selbst** und ruft keinen der Befehle oben auf.
- **Stopp statt Retry:** Rote oder fehlende CI-Checks, ein Merge-Konflikt, ein
  als „Ggf. unvollständig“ (`completion_uncertain`) markierter Lauf (auch:
  Claude meldet `TESTS ROT`, siehe „Tests“) oder ein
  fehlgeschlagener Merge halten die Kette an. Das Epic wird in Agira sichtbar
  als blockiert markiert, mit Grund. Es gibt **keinen automatischen Retry**.
  Ein Mensch prüft den Fall und stößt das Sub-Issue neu an.
- **Status:** Merge eines Sub-Issues in den Epic-Branch → `Integrated`. Merge
  des Epic-PRs nach `main` → das Epic und alle `Integrated`-Sub-Issues auf
  `Testing`. PR-Description und RAG-Update laufen pro Sub-Issue-PR wie bei
  jedem anderen PR.
- **Abschluss:** Nach dem letzten Sub-Issue merged der Worker `main` in den
  Epic-Branch (bei Konflikt: Stopp, Epic blockiert) und legt dann den
  **Epic-PR nach `main` als Draft** an. Review und Merge macht ein Mensch.
- Einzel-Issues ohne Parent sind davon unberührt (siehe oben).

## Commits

- Conventional Commits, mit Agira-ID im Scope, wenn es eine gibt:
  `feat(#1234): …`, `fix(#1234): …`. Im Epic-Modus wird jedes Sub-Issue zu
  genau einem Squash-Commit im Epic-Branch; die ID macht den Epic-PR
  commit-für-commit lesbar.

## PR-Text

Feste Abschnitte, wörtlich: `## Zusammenfassung`, `## Änderungen`,
`## Warum / Entscheidungen`, `## Test-Hinweise`. Unter „Warum / Entscheidungen“
bewusst verworfene Alternativen als „nicht X, weil Y“. Die Texte werden beim
Merge in die Item-PR-Description übernommen und in Weaviate indexiert.

## Tests

- Ohne PostgreSQL: `python manage.py test <module> --settings=agira.test_settings`
  (SQLite in-memory, ohne Whitenoise-Manifest).
- Vor einem Push mindestens die Tests der betroffenen Module laufen lassen
  und das Ergebnis im PR-Text unter „## Test-Hinweise“ dokumentieren.
- **Rote Tests** (durch die Änderung rot oder nicht grün zu bekommen) werden
  dort benannt, und die Schlussantwort endet mit einer eigenen Zeile
  `TESTS ROT`. Der Worker wertet das als „Ggf. unvollständig“: Der PR bleibt
  Draft, im Epic-Modus wird nicht gemergt und die Kette hält an.
  Fehlschläge, die nachweislich schon auf dem Basis-Branch bestehen, werden
  genannt, gelten aber nicht als rot.
  Im Epic-Umfeld sind das u. a. `core.services.claude_queue`,
  `core.management.commands.test_run_claude_worker` und
  `core.test_github_pr_webhook`.
