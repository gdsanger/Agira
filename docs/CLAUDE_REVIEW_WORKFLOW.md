# Claude-Review für Items (Integrated / Testing)

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
    {"title": "...", "description": "...", "criterion": "betroffenes Kriterium"}
  ]
}
```

| Urteil       | Bedingung                                                        | Wirkung durch den Worker                                  |
|--------------|------------------------------------------------------------------|-----------------------------------------------------------|
| `pass`       | alle Kriterien `met`/`accepted_deviation`, `deviations` leer      | Bericht-Kommentar, Item → `Closed`                        |
| `deviations` | mindestens eine Abweichung, PR-Verweis am Item vorhanden          | Bericht-Kommentar, genau ein Folge-Issue, Item unverändert |
| `unclear`    | alles andere (nur der Parser/Worker erzeugt es, nie Claude)       | Bericht-Kommentar, Item unverändert, Job „Ggf. unvollständig“ |

Widersprüche (z. B. `pass` mit `not_met`-Kriterium oder `deviations` ohne
Eintrag) sind ebenfalls `unclear`. **Geschlossen wird nur bei `pass`.**

## Bewusste Abweichungen

Eine im PR-Text begründete, bewusste Abweichung (Abschnitt „## Warum /
Entscheidungen“, insbesondere „nicht X, weil Y“) ist keine Abweichung: Status
`accepted_deviation`, `evidence` verweist auf die Begründung. Eine
**unbegründete** Lücke ist `not_met`; im Zweifel `not_met` statt `met`. Deshalb
ist die PR-Text-Pflicht aus `CLAUDE.md` die Grundlage des Reviews.
Akzeptierte Abweichungen erscheinen im Bericht und im Folge-Issue als
„nicht erneut umsetzen“.

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
