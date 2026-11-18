# Review für Items (Integrated / Testing) – Claude oder Codex

Regeln und Hintergrund zum Review-Job (`kind=review`) der Claude-Queue. Die
verbindliche Kurzfassung steht in `CLAUDE.md` (Abschnitt „Review
(Integrated/Implemented)“); diese Datei darf ihr nicht widersprechen.

## Zweck

Nach der Umsetzung prüft Claude read-only, ob der Code im Checkout die
Akzeptanzkriterien des Items erfüllt. Das Ergebnis ist ein strukturiertes
Urteil; **angewendet wird es vom Worker**, nicht von Claude.

## Ablauf

1. **Auslösen:** Button „Review durch Claude“ am Item
   (`enqueue_review_for_claude`). Zulässig nur für Items im Status
   `Integrated` (Sub-Issue, gegen den Sub-Issue-PR) oder `Testing`
   (Einzel-Issue bzw. Epic gegen den Epic-PR) **mit verknüpftem PR**. Ein
   bereits aktiver Review-Job am Item wird wiederverwendet, kein zweiter
   angelegt. Der Job gehört nicht zur Epic-Kette.
2. **Checkout:** Der Worker setzt den Checkout auf den PR-Stand (Merge-Commit,
   sonst PR-Head) – ohne Branch, Commit, Push oder PR – und ermittelt den Diff.
3. **Prompt:** Issue-Beschreibung (ohne Git-Workflow-Hinweis), erwartete
   Lösung, PR-Text und Diff (gekürzt bei sehr großen Diffs).
4. **Lauf:** Claude läuft headless mit nur lesenden Werkzeugen und antwortet
   mit genau einem JSON-Urteil.
5. **Parsen:** `parse_review_verdict` wirft nie; alles Unlesbare wird `unclear`.
   Rohantwort und Urteil werden am Job gespeichert.
6. **Anwenden:** `apply_review_result` schreibt einen internen Bericht-Kommentar
   am Item und handelt je Urteil (siehe unten). Idempotent pro Job.

## Urteils-Schema

```json
{
  "verdict": "pass | deviations",
  "summary": "Kurztext",
  "criteria": [
    {"text": "Akzeptanzkriterium", "status": "met | not_met | accepted_deviation",
     "evidence": "Datei:Zeile oder PR-Hinweis"}
  ],
  "deviations": [
    {"title": "...", "description": "...", "criterion": "betroffenes Kriterium",
     "severity": "major | minor"}
  ]
}
```

| Urteil       | Bedingung                                                        | Wirkung durch den Worker                                  |
|--------------|------------------------------------------------------------------|-----------------------------------------------------------|
| `pass`       | kein `major`-Befund zu einem `not_met`-Kriterium (ggf. `minor`-Hinweise) | Bericht-Kommentar (ggf. „Hinweise (nicht blockierend)“), Item → `Closed`, kein Folge-Issue |
| `deviations` | mindestens ein `major`-Befund, PR-Verweis am Item vorhanden       | Bericht-Kommentar, genau ein Folge-Issue nur mit den `major`-Befunden, Item unverändert |
| `unclear`    | alles andere (nur der Parser/Worker erzeugt es, nie Claude)       | Bericht-Kommentar, Item unverändert, Job „Ggf. unvollständig“ |

Widersprüche (z. B. `pass` mit `not_met`-Kriterium oder `deviations` ohne
Eintrag) sind ebenfalls `unclear`. **Geschlossen wird nur bei `pass`.**

## Schweregrade (`severity`)

Das Review prüft **Vollständigkeit und Plausibilität**, nicht die fachliche
Korrektheit zur Laufzeit (der fachliche Test findet später statt). Jeder
Eintrag in `deviations` hat eine `severity`.

**Fehlender Nachweis ist keine Abweichung:** Der Review-Checkout ist read-only
und hat meist keine Toolchain. Ein nicht ausführbarer Build/Test/Start ist für
sich kein Befund. Als Build-/Test-Beleg dient der **CI-Status des PR**, den der
Worker (`gh pr checks`) in den Prompt schreibt: grün = gebaut und getestet,
rot = `not_met`. Ein bloßer Wunsch nach mehr Nachweis ist höchstens `minor`.

Severities:

- `major`: ein Kriterium ist fachlich nicht erreicht oder Verhalten/Funktion
  fehlt.
- `minor`: formal, kosmetisch, rein dokumentarisch, Widerspruch/Unschärfe in
  der Vorgabe selbst, Anregung zur Verbesserung.
- Bei Zweifel zwischen `major` und `minor`: `major`, außer die Vorgabe
  widerspricht sich selbst oder der Befund ist rein formal.
- Fehlt `severity` oder ist sie ungültig, gilt der Eintrag als `major`.

`deviations` ergibt sich nur, wenn mindestens ein `major`-Befund zu einem
`not_met`-Kriterium existiert. `minor`-Befunde sind Hinweise: Urteil `pass`,
Item → `Closed`, **kein** Folge-Issue; der Bericht enthält den Abschnitt
„Hinweise (nicht blockierend)“ mit Beleg. Das Folge-Issue bei `deviations`
enthält nur die `major`-Befunde. In Job-Detail und Queue-Zeile zeigt ein
Badge „Pass (n Hinweise)“ die Hinweise an.

## Bewusste Abweichungen

Eine im PR-Text begründete, bewusste Abweichung (Abschnitt „## Warum /
Entscheidungen“, insbesondere „nicht X, weil Y“) ist keine Abweichung: Status
`accepted_deviation`, `evidence` verweist auf die Begründung. Eine
**unbegründete** Lücke ist `not_met`; im Zweifel `not_met` statt `met`. Deshalb
ist die PR-Text-Pflicht aus `CLAUDE.md` die Grundlage des Reviews.
Akzeptierte Abweichungen erscheinen im Bericht und im Folge-Issue als
„nicht erneut umsetzen“.

## Befund überschreiben („Trotz Befunden schließen“)

Ein Mensch kann das Ergebnis eines Reviews bewusst überschreiben. Das ist
**nie** Sache von Claude oder dem Worker.

- **Sichtbar** (Dropdown „Aktionen“ am Item) nur, wenn das Item nicht `Closed`
  ist und der jüngste Review-Job (`kind=review`, Status `done`) das Urteil
  `deviations` oder `unclear` hat und noch nicht überschrieben wurde.
- **Pflicht-Begründung** (mindestens 10 Zeichen, serverseitig geprüft), sonst
  keine Änderung. View: `POST items/<id>/review-override/`, CSRF-geschützt,
  angemeldeter User.
- **Service** `core.services.claude_queue.review_override.override_review`:
  Item → `Closed` über den `ItemWorkflowGuard` (Status-History), interne
  Notiz „Review-Befund überschrieben“ (`CommentKind.NOTE`) mit Begründung, User,
  Zeitpunkt, Job-Nr., Urteil, PR-Link und ggf. Folge-Issue, Felder
  `review_overridden_by` / `review_overridden_at` / `review_override_reason` am
  Job sowie ein Activity-Eintrag (`claudequeuejob.review_overridden`).
- **Folge-Issue:** Das Modal bietet „Folge-Issue ebenfalls schließen“ (Default
  an), solange es offen und unbearbeitet ist. Befindet es sich in `Working`,
  `Integrated`, `Testing` oder hat es einen PR, wird es nie automatisch
  geschlossen (Hinweis im Modal). Geschlossen erhält es eine Notiz „Durch
  Überschreiben des Review-Befunds erledigt“ mit der Begründung.
- **Idempotent:** Ein zweiter Submit (Doppelklick) ändert nichts und erzeugt
  weder zweiten Kommentar noch zweite Aktivität.
- **Nachvollziehbar:** `review_verdict` und Bericht bleiben unverändert; Queue
  und Job-Detail zeigen „Überschrieben durch <User>“ mit Begründung.

## Sicherheits-Defaults

- Read-only: erlaubt sind `Read`, `Grep`, `Glob` und lesende Git-Befehle
  (`diff`, `log`, `show`, `status`, `blame`, `ls-files`).
- Ausdrücklich verboten: `Edit`, `Write`, `NotebookEdit`, `git push`,
  `commit`, `checkout`, `reset`, `add` und `gh`.
- Claude ändert nichts in Agira; Statuswechsel, Kommentar und Folge-Issue
  erzeugt ausschließlich der Worker.
- Der Review verändert den Status des Items nur bei `pass` (→ `Closed`).

## Folge-Issue-Konventionen

- Titel: `Folge zu PR #<nr>: <Titel> – Abweichungen aus Review`.
- Status `Backlog`, gleiches Projekt, gleicher Parent und Typ; Relation
  „related“ zum Ursprungs-Item.
- Die Beschreibung ist **selbst-enthaltend** und verweist auf den
  **GitHub-PR**, nicht auf Agira (Claude Code und Copilot können Agira nicht
  lesen): Ursprung, ursprünglicher Auftrag, festgestellte Abweichungen mit
  Beleg, akzeptierte Abweichungen, Akzeptanzkriterien.
- Pro Job höchstens ein Folge-Issue (Idempotenz über Marker im Kommentar und
  `review_followup_item`).

## Fehlerfälle

- **`unclear`:** Urteil nicht lesbar/widersprüchlich, Lauf unsicher oder
  `deviations` ohne PR-Verweis. Item bleibt unverändert; der Job ist DONE mit
  Markierung „Ggf. unvollständig“ und der Bericht nennt den Grund. Ein Mensch
  prüft und stößt den Review ggf. neu an.
- **Kein PR:** Enqueue wird abgelehnt (`ReviewNotAllowed`); fehlt das Mapping
  erst im Worker, schlägt der Job mit klarer Meldung fehl, Claude wird nicht
  gestartet.
- **Limit:** Erreicht der Lauf das Abo-Limit, wird der Job geparkt
  (`waiting_limit`) und später fortgesetzt bzw. – wenn erlaubt – auf dem
  API-Key wiederholt. Timeout, Auth- oder CLI-Fehler lassen den Job
  fehlschlagen; das Item bleibt unberührt, die Epic-Kette wird nie blockiert.
- **Anwenden schlägt fehl:** Urteil bleibt am Job gespeichert, Job wird als
  „Ggf. unvollständig“ markiert.

## Tests

`core.services.claude_queue`, `core.management.commands.test_run_claude_worker`
(inkl. End-to-End für `pass`, `deviations`, `unclear`),
`core.test_claude_enqueue_view`, `core.test_claude_queue_views`.

## Provider (Claude / OpenAI Codex)

Review-Jobs laufen mit dem Review-Provider des Items (`review_provider`, leer =
der jeweils andere als bei der Umsetzung). Prompt, Urteils-Schema, Parser und
`review_apply`/`review_override` sind provider-neutral; der Bericht-Kommentar
nennt Provider und Modell („Geurteilt von“).

- **Regel „anderer Provider“:** Ohne gesetzten `review_provider` reviewt der
  andere Provider als der, der zuletzt sauber umgesetzt hat (ein Lauf mit
  `completion_uncertain` zählt nicht; ohne Lauf: der andere als
  `implementation_provider`). Ein gesetzter `review_provider` gewinnt.
  Umsetzung Claude → Review OpenAI und umgekehrt. Einrichtung des
  OpenAI-Providers: [`OPENAI_PROVIDER_SETUP.md`](OPENAI_PROVIDER_SETUP.md).
- **Codex read-only:** `codex exec -s read-only -c approval_policy=never`,
  ohne `--dangerously-bypass-approvals-and-sandbox` (Test:
  `test_codex_review`). Schreiben, Commit und Push sind damit durch die Sandbox
  ausgeschlossen.
- **Urteil:** bevorzugt aus `--output-last-message` (Antwort gegen
  `--output-schema`, strikt: alle Felder Pflicht, `verdict` nur `pass |
  deviations`); fehlt die Datei, gilt die letzte Agent-Nachricht aus dem
  Stream. Beides läuft durch `parse_review_verdict` – Unlesbares oder
  Schema-Verstöße bleiben `unclear`.
