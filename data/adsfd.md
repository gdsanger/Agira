**Titel**  
Worker-Job zur Synchronisation von ExternalIssueMapping, Item-Status, PR-Verlinkung und Weaviate-Index

---

## Ziel

Implementiere einen Worker-Job, der regelmäßig/verlässlich:

1. den Status von über `ExternalIssueMapping` verlinkten Issues synchronisiert,  
2. den zugehörigen `ItemStatus` aktualisiert,  
3. verknüpfte Pull Requests (PRs) am Item hinterlegt und  
4. Issue- und PR-Inhalte nach Weaviate pushed, um den Vektor-/Kontextindex zu erweitern.

---

## Fachliche Anforderungen

### 1. Status-Synchronisation External Issue → Item

- Quelle: Datenstruktur `ExternalIssueMapping` (enthält Verlinkung zwischen internem Item und externem Issue).
- Bei Statusänderung eines externen Issues:
  - **Wenn das verlinkte Issue geschlossen ist** (z.B. Status `closed` beim externen Tracker):
    - Setze den `ItemStatus` des verknüpften Items auf `"Testing"` (bitte exakt so schreiben, falls bereits im System vorhanden, ansonsten Angleich an existierende Status-Werte beachten).
- Die Erkennung der Statusänderung soll über den neuen Worker erfolgen (Polling, Webhook-Queue oder anderes im Projekt übliches Verfahren – siehe Offene Fragen).

### 2. PR-Verlinkung am Item

- Für jedes über `ExternalIssueMapping` verlinkte Issue:
  - Ermittle den/die zugehörigen Pull Request(s) (PRs).  
    - Beispiel: Bei GitHub-Issues über die GitHub-API `issues/{id}/events` oder `pulls`-Bezug, je nach vorhandener Integration.
  - Verlinke den/die PR(s) am entsprechenden internen Item:
    - Persistiere im Item-Modell eine Referenz auf den PR (z.B. `externalPullRequestId`, `externalPullRequestUrl` o.ä.; konkrete Feldnamen nach vorhandener Struktur).

### 3. Push von Issue- und PR-Inhalten nach Weaviate

- **Wann pushen?**
  - Spätestens, wenn ein verlinktes Issue geschlossen wird (Statuswechsel), und der Worker den ItemStatus auf `"Testing"` setzt.
  - Auch bei anderen relevanten Statuswechseln

- **Welche Inhalte?**
  - Vom externen Issue:
    - Titel
    - Beschreibung/Body
    - Relevante Metadaten (Labels, Status, Erstell-/Updatezeit, Referenzen) – sofern für Weaviate-Schema sinnvoll.
  - Vom/dem zugehörigen PR:
    - Titel
    - Beschreibung/Body
    - Optional: Liste der geänderten Dateien, Commit-Messages oder Diff-Auszüge (abhängig von bestehender Weaviate-Integration und Datenmenge).

Alles was wir in Weaviate speichern, machen wir über das eine Objekt AgiraObject das wie volgt aussieht:
```JSON
{
  "mime_type": null,
  "created_at": "2026-01-24 19:52:40.473439+00:00",
  "source_system": "agira",
  "title": "Add Crud Operation to Entity Project in User UI ",
  "type": "item",
  "size_bytes": null,
  "project_id": "1",
  "sha256": null,
  "updated_at": "2026-01-25 10:08:59.748469+00:00",
  "status": "Working",
  "parent_object_id": null,
  "org_id": "1",
  "url": "/items/1/",
  "object_id": "1",
  "external_key": null,
  "text": "Status: Working\n\nBetrifft UI /items/inbox/\n\n## ListView\n1. \u00c4ndere das Layout von einer Table Struktur zu Cards. In den Card muss der Name, Status angezeigt werden, und die Anzahl der Items getrennt in Inbox, Backlog, Working, Testing, ready for Release. Hier kann man gerne mit Icon arbeiten und im Tooltip anzeigen was es ist. \n2. F\u00fcge eine Filterbar hinzu. wo man nach Organisation, Type und Status Filtern kann. \n\n\n## DetailView\n1. Add all Crud Operation\n2. Speicher die Active Tab Position im Lokal Storage und zeige immer den darin gespeichertn Tab beim Page Load an \n3. Add Operation to Add new Items, Nodes, Releases\n4. Add Logik to Add / Rekate Clients\n",
  "uuid": "00a700b1-f9b6-5e47-9438-d49140cd8928"
}
```

- **Ziel:**
  - Erweiterung des bestehenden Weaviate-Vektorraums, damit zukünftige Issues besseren Kontext nutzen können.
  - Nutzung des bestehenden Weaviate-Schemas (keine schema-fremden Felder einführen, ohne das bestehende Schema zu prüfen).

## Wichtiger Hinweis
Ist das Objekt in Weaviate anicht vorhanden, legen wir ein neues an! Ist das Objekt schon vorhanden, ändern wir das Objket in Weaviate nur dann wenn sich der Status geändert hat. Wenn der Status gleich ist, machen wir nicht, denn dann ist keine relevante Änderung zu erwarten, und es verhindert das ein Closed Item ständig einen update bekommt, 

---

## Technische Anforderungen

### 1. Worker-Job

- Implementiere einen wiederholt ausführbaren Worker/Job/Task (gemäß den im Projekt üblichen Patterns).
- Aufgaben des Workers:
  1. Alle relevanten `ExternalIssueMapping`-Einträge ermitteln, bei denen:
     - der externe Status noch nicht mit dem internen Status synchron ist, **oder**
     - die Inhalte noch nicht nach Weaviate gepusht wurden.
  2. Für jedes Mapping:
     - Externen Issue-Status abrufen.
     - Falls geschlossen:
       - Item laden.
       - `ItemStatus` des Items auf `"Testing"` setzen (unter Berücksichtigung von möglichen Status-Transition-Regeln im System).
       - Verknüpfte PRs ermitteln und im Item speichern.
       - Issue- und PR-Inhalte nach Weaviate pushen (mit geeigneter Id/Referenzierung).
     - Persistenz von Synchronisations-Metadaten (z.B. `lastSyncedAt`, `weaviatePushedAt` o.ä.), sofern vorhanden oder sinnvoll.

### 2. Fehlerbehandlung & Robustheit

- Der Worker soll idempotent arbeiten:
  - Mehrfachausführung darf keine widersprüchlichen Zustände erzeugen.
- Bei Fehlern in externen Abfragen (API-Fehler, Timeouts):
  - Logging und Retry-Mechanismus nutzen, wie im Projekt üblich.
- Keine endlosen Retries auf denselben fehlerhaften Datensatz ohne Backoff.

### 3. Performance / Umfang

- Worker soll in Batches arbeiten (z.B. limitierte Anzahl Mappings pro Lauf), falls viele Mappings existieren.
- Keine Vollreindizierung aller Issues/PRs pro Lauf, sondern inkrementell anhand von Status-/Zeitstempeln.

---

## Akzeptanzkriterien

1. **Item-Status-Aktualisierung**
   - Wenn ein externes Issue (über `ExternalIssueMapping` verknüpft) auf `closed` steht:
     - Der zugehörige `ItemStatus` wird auf `"Testing"` gesetzt.
   - Statusänderung ist in der Datenbank und/oder API sichtbar.

2. **PR-Verlinkung**
   - Für ein Item mit verknüpftem, geschlossenem Issue:
     - Der/die zugehörigen PR(s) sind am Item referenziert (gemäß Datenmodell).
   - Die Referenzen sind per API oder DB-Query nachvollziehbar.

3. **Weaviate-Integration**
   - Zu einem geschlossenen Issue:
     - Es existiert ein Eintrag in Weaviate, der die Inhalte des Issues enthält.
   - Zu den verknüpften PR(s):
     - Deren Inhalte (mindestens Titel + Beschreibung) sind ebenfalls in Weaviate vorhanden.
   - Wiederholtes Ausführen des Workers führt nicht zu fehlerhaften Duplikaten oder Inkonsistenzen (nur erwartbare Duplikate je nach Schema/ID-Strategie).

4. **Logging & Monitoring**
   - Relevante Aktionen (Statusänderung, Weaviate-Push, Fehler) werden geloggt.
   - Fehlgeschlagene Synchronisationen sind identifizierbar (z.B. über Logs, Metriken oder Statusfelder).

---
