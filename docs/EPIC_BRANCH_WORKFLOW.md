# Epic-Branch-Workflow (#1076)

Optionale Fähigkeit für fachlich zusammenhängende Issue-Ketten: Ein Parent-Issue
(„Epic") definiert einen langlebigen Branch, seine Sub-Issues zweigen davon ab
statt von `main` und mergen einzeln wieder hinein. Nach `main` geht am Ende
genau ein Pull Request — manuell reviewt, manuell gemergt.

**Der bisherige Ablauf bleibt unverändert.** Ein Issue ohne Parent-Issue
branched von `main`, bekommt einen Draft-PR gegen `main` und wird wie bisher von
Hand gemergt. Es gibt keinen Zwang und keinen Schalter: Ob ein Issue im
Epic-Modus läuft, entscheidet allein, ob es ein Parent-Issue hat.

## Leitprinzip

> **Das Epic ist die Einheit der Testbarkeit, nicht das einzelne Sub-Issue.**

Ein Epic ist eine vertikale Scheibe, in Schichten zerlegt: Datenmodell →
Methoden/Logik → UI. Die Sub-Issues sind keine unabhängigen Features, sondern
Teile *einer* Sache. Ein Datenmodell allein lässt sich zur Laufzeit nicht
sinnvoll testen — erst die zusammengesetzte Scheibe ergibt ein Produkt, das man
ausprobieren kann. Deshalb wird pro Sub-Issue **nicht** einzeln getestet oder
reviewt, sondern das gesamte Epic am Ende.

## Entscheidungsregel: Epic-Branch oder direkt gegen `main`?

Epic-Branch verwenden, wenn:

- die Issues Schichten *einer* Sache sind und aufeinander aufbauen,
- ein späteres Issue ohne das frühere gar nicht sinnvoll gebaut werden kann,
- die Kette ohne Begleitung durchlaufen soll (nachts, am Wochenende).

Direkt gegen `main` arbeiten, wenn:

- das Issue für sich steht oder explorativ ist,
- es sofort einzeln testbar und deploybar ist,
- der Zuschnitt noch unklar ist.

Es gibt bewusst **keine** Regel zur maximalen Epic-Größe. Ob ein Zuschnitt trägt,
ist eine Entwickler-Einschätzung, keine Systemregel.

## Branch-Modell

```
main
 └── feature/<epic-id>-<slug>          Epic-Branch (langlebig)
      ├── fix/<sub-issue-1-slug>-<id>  → PR gegen feature/… , Squash-Auto-Merge
      ├── fix/<sub-issue-2-slug>-<id>  → PR gegen feature/… , Squash-Auto-Merge
      └── fix/<sub-issue-3-slug>-<id>  → PR gegen feature/… , Squash-Auto-Merge

feature/<epic-id>-<slug> → main        Epic-PR: Draft, manueller Review + Merge
```

Der Epic-Branch-Name wird aus dem Parent-Issue **abgeleitet**, nicht gespeichert
(`core/services/claude_queue/branch.py`): Enqueue, Worker und Webhook müssen
denselben Namen unabhängig voneinander errechnen können, ohne einen gemeinsamen
Datensatz, der auseinanderlaufen kann.

Sub-Issues zweigen alle vom **Epic-Branch** ab, nie voneinander. Stacked PRs
(Issue N+1 von Issue N) sind ausdrücklich nicht Teil des Modells.

## Reihenfolge: das Order-Feld

Die Reihenfolge steht am Sub-Issue im Feld `epic_order` (UI: „Epic-Order",
sichtbar sobald ein Parent Item gesetzt ist). Gedacht in Zehnerschritten, damit
sich später eine Schicht dazwischenschieben lässt:

| Sub-Issue   | `epic_order` |
|-------------|--------------|
| Datenmodell | 10           |
| Logik       | 20           |
| UI          | 30           |

Abgearbeitet wird strikt aufsteigend, bei Gleichstand nach Item-ID. Bewusst ein
flaches Feld und **kein** Abhängigkeits-Graph: Ein Graph ist ausdrucksstärker,
aber man sieht ihm einen Fehler nicht mehr an.

**Ein Sub-Issue startet erst, wenn alle seine Vorgänger in den Epic-Branch
gemergt sind.** Der Worker überspringt beim Claim jeden Job, dessen Vorgänger
noch offen sind; der Job bleibt `queued` und wird beim nächsten Poll erneut
geprüft — der Merge des Vorgängers gibt ihn ohne Zutun frei.

Warum die Strenge: Läuft das UI-Issue, bevor sein Datenmodell existiert, baut die
KI trotzdem irgendetwas — im schlechtesten Fall **erfindet sie sich einen
Mock/Stub** für das fehlende Fundament. Der PR ist grün, und niemand merkt, dass
auf einer Attrappe gebaut wurde.

## Ablauf eines Sub-Issues

1. Der Worker holt das Repo und setzt es auf `origin/main` zurück.
2. Er legt den Epic-Branch an, falls er noch nicht existiert — sonst zieht er
   `main` in den Epic-Branch nach, damit die nächste Schicht auf dem aktuellsten
   Fundament startet.
3. Der Sub-Issue-Branch wird vom Epic-Branch abgezweigt.
4. Der PR wird gegen den Epic-Branch geöffnet — **kein Draft** — und
   **Squash-Auto-Merge** wird scharf geschaltet.
5. Claude implementiert und committet mit Agira-ID im Scope
   (`feat(#1234): …`), damit der Epic-PR commit-für-commit lesbar bleibt.
6. GitHub mergt den PR selbstständig, sobald die Required Checks grün sind.
7. Beim Merge wechselt das Sub-Issue auf `Testing`.
8. Ist es das letzte Sub-Issue des Epics, wird automatisch der Epic-PR gegen
   `main` als **Draft** angelegt.

## Auto-Merge-Gate

Weil ein einzelnes Sub-Issue nicht eigenständig testbar ist, gibt es zwischen den
Schichten keinen sinnvollen Runtime-Test. Der Zwischen-Gate ist deshalb ehrlich
auf zwei Signale reduziert:

1. **Build/CI bleibt grün** (kompiliert, Lint, vorhandene Unit-Tests) —
   verhindert, dass sich Schichten auf zerbrochenem Fundament stapeln.
2. **Review-Pass blockiert nicht** — der einzige inhaltliche Qualitäts-Sensor pro
   Sub-Issue. Er läuft in frischem Kontext und idealerweise mit einem *anderen*
   Modell als dem, das den Code geschrieben hat: Autor und Reviewer im selben
   Modell haben dieselben blinden Flecken.

Inhaltlich verifiziert wird die Scheibe als Ganzes — durch den manuellen
Epic-Review vor `main`.

## Statuslogik

| Ereignis                              | Statuswechsel                     |
|---------------------------------------|-----------------------------------|
| Sub-Issue-PR → Epic-Branch gemergt    | Sub-Issue `Working` → `Testing`   |
| Epic-PR → `main` gemergt              | Parent-Issue `Working` → `Testing`|

Ein Merge in einen `feature/*`-Branch lässt ein Epic (ein Item mit Sub-Issues)
bewusst in `Working` stehen: Der Container ist erst fertig, wenn sein eigener
Branch auf `main` gelandet ist.

## Repository-Voraussetzungen

- Branch-Protection **nur** auf `main`; `feature/*` bleibt ungeschützt.
- Auto-Merge im Repository aktiviert (`Settings → General → Allow auto-merge`).
- Squash als Merge-Methode erlaubt.
- CI-Workflows laufen auch für PRs gegen `feature/*`:

  ```yaml
  on:
    pull_request:
      branches: [main, 'feature/**']
  ```

Fehlt die Auto-Merge-Einstellung oder gibt es keine Required Checks, schlägt das
Scharfschalten fehl und der Sub-Issue-PR wartet auf einen manuellen Merge. Das
ist eine langsamere Kette, kein kaputter Job.

## Abgrenzung

Dieses Dokument beschreibt das **Branch-Modell**. Wie die Kette getrieben wird
(hierarchische Queue, Advancement nur bei eindeutigem Erfolg, Halt bei
„Ggf. unvollständig"/Fehler), gehört zu #1079.

Nicht Teil des Modells: Stacked PRs, Rebase-basierte Kettenpflege früherer
Branches, eine feste Obergrenze für die Epic-Größe.

## Code-Landkarte

| Datei | Rolle |
|-------|-------|
| `core/services/claude_queue/branch.py` | Ableitung von `fix/*`- und `feature/*`-Namen, Base-Branch-Auflösung |
| `core/services/claude_queue/epic.py`   | Reihenfolge, Start-Gate, finaler Epic-PR |
| `core/services/claude_queue/hint.py`   | Git-Workflow-Hinweis am Item (nennt den Base-Branch) |
| `core/management/commands/run_claude_worker.py` | Epic-Branch anlegen/nachziehen, PR-Ziel, Auto-Merge, Order-Gate beim Claim |
| `core/services/github/service.py`      | Statuslogik beim Merge, Auslösen des Epic-PRs |
