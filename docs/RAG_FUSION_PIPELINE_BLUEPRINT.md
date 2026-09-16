# Blueprint: RAG-Pipeline mit 3-stufiger Fusion

**Zweck dieses Dokuments:** Das in Agira erprobte RAG-Retrieval-Verfahren so beschreiben, dass es
in einem beliebigen anderen Projekt — bevorzugt mit KI-Unterstützung (Claude Code, Copilot, Cursor) —
nachgebaut werden kann. Das Dokument ist bewusst **produktneutral** geschrieben: Weaviate, Django und
die Agira-Objekttypen sind Referenz-Implementierung, nicht Voraussetzung.

**Referenz-Implementierung:** `core/services/rag/extended_service.py`, `core/services/rag/config.py`,
`agents/question-optimization-agent.yml`.

---

## 1. Das Problem, das dieses Muster löst

Naives RAG ("Frage einbetten → Top-K Vektortreffer → in den Prompt kippen") scheitert in
Wissensbasen mit gemischten Objekttypen regelmäßig an vier Punkten:

| Problem | Symptom | Antwort dieses Blueprints |
|---|---|---|
| Fragen sind umgangssprachlich, Dokumente fachsprachlich | Vektorsuche findet Geplauder statt Technik | Stufe 0: Query-Optimierung |
| Reine Semantik verfehlt exakte Bezeichner (Dateinamen, Fehlercodes, IDs) | `NullPointerException` oder `config.py` wird nicht gefunden | Stufe 1: zwei Suchpfade mit unterschiedlicher alpha-Gewichtung |
| Ein Objekttyp dominiert die Top-K | 6 Kommentare, 0 Dokumentation | Stufe 2 + Stufe 3: Reranking und typbasierte Quotierung |
| Ein 200-kB-Dokument sprengt das Kontextfenster oder wird bei Zeichen 6000 mitten im Satz abgeschnitten | LLM sieht nur das Inhaltsverzeichnis | Stufe 3: Budgetierung + abschnittsbewusstes Trimmen |

Der Kern ist die **3-stufige Fusion**: an drei verschiedenen Stellen werden Ergebnismengen
zusammengeführt, jeweils mit einem anderen Ziel.

---

## 2. Gesamtarchitektur

```
                    ┌──────────────────────────────┐
  Rohe Nutzerfrage ─▶│ Stufe 0: Query-Optimierung   │  1 LLM-Call, gecacht, optional
                    │ (LLM → strukturiertes JSON)   │
                    └──────────────┬───────────────┘
                                   │ OptimizedQuery
                     ┌─────────────┴─────────────┐
                     ▼                           ▼
          ┌────────────────────┐      ┌────────────────────┐
          │ Semantischer Pfad  │      │ Keyword-Pfad       │   Stufe 1
          │ alpha = 0.6        │      │ alpha = 0.3        │   FUSION #1:
          │ core+syn+phr+tags  │      │ tags + core        │   BM25 ⊕ Vektor
          │ Limit 24           │      │ Limit 24           │   (in der DB)
          └─────────┬──────────┘      └─────────┬──────────┘
                    └───────────┬───────────────┘
                                ▼
                   ┌─────────────────────────────┐             Stufe 2
                   │ Dedup + gewichtetes Rerank  │             FUSION #2:
                   │ 0.6·sem + 0.2·kw            │             Pfad ⊕ Pfad
                   │ + 0.15·agree + 0.05·same    │
                   │ → Top 6                     │
                   └─────────────┬───────────────┘
                                 ▼
                   ┌─────────────────────────────┐             Stufe 3
                   │ A/B/C-Layer-Bündelung       │             FUSION #3:
                   │ + Primary-Doc-Boost         │             Treffer ⊕ Budget
                   │ + Smart-Trim                │             → ein Kontext
                   └─────────────┬───────────────┘
                                 ▼
                    Kontext-Text mit [#A1] [#B1] [#C1]
```

Die drei Fusionsstufen im Klartext:

1. **Fusion innerhalb eines Pfades** — lexikalisch (BM25) und vektoriell werden zu *einem*
   Score pro Pfad verschmolzen. Macht die Vektor-DB; du steuerst sie über `alpha`.
2. **Fusion zwischen den Pfaden** — zwei unabhängig gerankte Listen werden dedupliziert und
   nach einer gewichteten Formel neu sortiert. Das ist deine Anwendungslogik.
3. **Fusion in den Kontext** — aus der flachen Top-N-Liste wird ein *strukturierter*, in
   Zeichenbudgets aufgeteilter Prompt-Block mit Typ-Quoten.

Stufe 1 und 2 sind reine Relevanz. Stufe 3 ist **Komposition**: sie entscheidet, was das LLM
tatsächlich zu lesen bekommt, und ist erfahrungsgemäß der Hebel mit dem größten Qualitätseffekt.

---

## 3. Voraussetzungen

### 3.1 Der Index

Ein einziger, flacher Index über alle Objekttypen. Ein Datensatz pro Objekt:

| Feld | Typ | Vektorisiert | Zweck |
|---|---|---|---|
| `object_id` | string | nein | Dedup-Schlüssel, Ausschlussfilter |
| `type` | string | ja | Layer-Zuordnung, Typfilter |
| `title` | string | ja | Anzeige, Dateinamen-Match |
| `text` | string | **ja** | der eigentliche RAG-Body |
| `project_id` / Mandant | string | nein | Harter Scope-Filter |
| `status` | string | nein | erlaubt dem LLM „Bug ist geschlossen" |
| `url` | string | nein | Quellenangabe/Deep-Link |
| `source_system` | string | nein | Herkunft (agira/github/mail/…) |
| `updated_at` | date | nein | Aktualität, spätere Zeit-Boosts |

Nicht vektorisierte Felder bewusst markieren (`skip_vectorization`) — IDs und URLs im Embedding
verrauschen die Semantik.

**Ein flacher Index über heterogene Typen ist Absicht.** Getrennte Collections pro Typ erzwingen
N Queries und machen Stufe 2 unnötig kompliziert. Die Typtrennung passiert später, in Stufe 3.

### 3.2 Die Suchmaschine

Gebraucht wird **Hybrid-Suche in einem Call** (BM25 + Vektor mit einstellbarer Gewichtung):

- **Weaviate** — `collection.query.hybrid(alpha=…, fusion_type=RELATIVE_SCORE)` (Referenz)
- **Qdrant** — Prefetch mit Dense + Sparse und `FusionQuery(fusion=RRF)`
- **Elasticsearch / OpenSearch** — `rrf` Retriever über `standard` + `knn`
- **PostgreSQL / pgvector** — zwei CTEs (`ts_rank_cd` und `<=>`), Fusion in SQL über RRF
- **Ohne Hybrid-Suche** — zwei getrennte Queries absetzen und Stufe 1 und 2 zu einer
  RRF-Fusion über vier Listen zusammenziehen (siehe §8.2)

### 3.3 Ein LLM für Stufe 0

Kleines, schnelles, günstiges Modell mit verlässlicher JSON-Ausgabe. Es denkt nicht, es formt um.

---

## 4. Stufe 0 — Query-Optimierung

Ein LLM-Call übersetzt die rohe Frage in eine **suchbare Struktur**.

### Kontrakt

```json
{
  "language": "de",
  "core": "Login Bug Sonderzeichen Passwort",
  "synonyms": ["Anmeldung Fehler", "Authentication Problem", "Login-Fehler"],
  "phrases": ["Sonderzeichen im Passwort", "Login-Bug"],
  "entities": {"person": ["Max"], "component": ["Login", "Passwort"]},
  "tags": ["login", "authentication", "bug", "password", "special-characters"],
  "ban": ["wie", "kann", "ich"],
  "followup_questions": ["Welche Sonderzeichen verursachen das Problem?"]
}
```

Rollenverteilung der Felder — das ist der Punkt, an dem die zwei Suchpfade entstehen:

- `core`, `synonyms`, `phrases` → nähren die **semantische** Suche (Bedeutungsraum aufspannen)
- `tags` → nähren die **lexikalische** Suche (BM25 braucht exakte Fachbegriffe)
- `entities`, `language`, `ban`, `followup_questions` → derzeit Metadaten für UI, Logging und
  spätere Filter; im Retrieval noch ungenutzt (siehe §10)

### Implementierungsregeln

1. **Antwort defensiv parsen.** Markdown-Code-Fences (` ```json `) entfernen, bevor `json.loads`
   läuft. Das kommt in der Praxis laufend vor.
2. **Pflichtfelder validieren.** Fehlt eines → Optimierung als fehlgeschlagen behandeln, nicht
   halb befüllen.
3. **Cachen.** Content-Hash als Schlüssel, TTL ~600 s. Die gleiche Frage im gleichen Kontext
   darf keinen zweiten Call kosten.
4. **Niemals hart fehlschlagen.** Bei jedem Fehler auf die Rohfrage zurückfallen:

```python
optimized = OptimizedQuery(
    language='unknown', core=query,
    synonyms=[], phrases=[], entities={}, tags=[], ban=[], followup_questions=[],
)
```

Die Pipeline läuft dann degradiert weiter — beide Pfade suchen mit der Rohfrage, was ungefähr
klassischem Hybrid-RAG entspricht. **Das ist die wichtigste Eigenschaft des ganzen Designs:
jede Stufe hat einen definierten Degradationspfad.**

5. **Abschaltbar halten** (`skip_optimization=True`) — für Tests, Batch-Läufe und Latenz-kritische
   Aufrufe.

### Kosten

Ein zusätzlicher LLM-Call pro Retrieval, typ. 200–400 Tokens, bei Cache-Hit null. Gegenrechnung:
die deutlich bessere Trefferlage spart oft mehr Tokens im Haupt-Call, als die Optimierung kostet.

---

## 5. Stufe 1 — Zwei Suchpfade (Fusion #1)

Beide Pfade laufen gegen denselben Index mit denselben Filtern, aber mit anderer Query und
anderem `alpha`.

| | Semantischer Pfad | Keyword-Pfad |
|---|---|---|
| Query | `core` + 3 Synonyme + 2 Phrasen + 2 Tags | alle `tags` + `core` |
| `alpha` | **0.6** (Vektor-lastig) | **0.3** (BM25-lastig) |
| Limit | 24 | 24 |
| Findet | Umschreibungen, Konzepte, verwandte Themen | Bezeichner, Fehlercodes, Fachbegriffe |

`alpha` = Vektor-Anteil (1.0 = rein Vektor, 0.0 = rein BM25). **Fusion #1 passiert hier in
der Datenbank**: sie mischt den BM25- und den Vektor-Score zu einem Score pro Treffer.

Wichtig: `RELATIVE_SCORE`-Fusion (Score-Normalisierung) statt Rangfusion wählen, wenn du in
Stufe 2 mit Score-Arithmetik weiterrechnen willst — sonst sind die Zahlen nicht vergleichbar.

### Filter, die vor der Suche greifen

```python
where = type IN ALLOWED_OBJECT_TYPES
if project_id:       where &= (project_id == …)        # harter Mandanten-/Scope-Filter
if current_item_id:  where &= (object_id != …)         # Selbstfund-Ausschluss
```

Zwei Filterentscheidungen, die sich in der Praxis als wesentlich erwiesen haben:

**Selbstfund-Ausschluss.** Wird das Retrieval aus dem Kontext eines Objekts heraus aufgerufen
(„gib mir Kontext zu Ticket 123"), ist das Objekt selbst der semantisch ähnlichste Treffer im
Index und belegt Platz 1 — trägt aber null bei, weil das LLM seinen Inhalt ohnehin schon hat.
Im Query ausschließen.

**Typ-Whitelist.** Agira sucht bewusst nur in `item`, `github_issue`, `github_pr`, `attachment` —
Kommentare sind ausgeschlossen. Kommentare sind zahlreich, kurz und thematisch nah; sie fluten
die Top-N und verdrängen die eigentliche Dokumentation. Das ist eine **inhaltliche Entscheidung
für dokumentationszentriertes Retrieval**, die jedes Projekt für sich treffen muss. Die Regel
dahinter ist übertragbar: *kurze, redundante, zahlreiche Objekttypen aus dem Retrieval nehmen
oder in eine eigene Layer-Quote sperren.*

**Leere Inhalte nachgelagert filtern.** Datensätze mit Titel, aber ohne `text`, sind wertlos.
In Weaviate ist der Null-Filter an `indexNullState` im Schema gebunden — deshalb wird in Python
nach der Query gefiltert. Trade-off bewusst akzeptiert: ein paar Treffer des Limits gehen
verloren, dafür funktioniert die Query ohne Schema-Zwang.

---

## 6. Stufe 2 — Fusion und Reranking (Fusion #2)

Zwei Listen à ≤24 → eine Liste à 6.

### 6.1 Deduplizierung

Über `object_id` in eine Map, **beide Scores erhalten**:

```python
results_map[obj_id] = {**result, 'sem_score': …, 'kw_score': …}
```

Das ist der entscheidende Schritt: ein Objekt, das in *beiden* Pfaden auftaucht, darf nicht
nur einmal gezählt werden — die Doppelnennung ist selbst ein Relevanzsignal.

### 6.2 Scoring-Formel

```
final_score = 0.60 · sem_score      # semantische Relevanz (Hauptsignal)
            + 0.20 · kw_score       # lexikalische Übereinstimmung
            + 0.15 · agreement      # 1.0 wenn in beiden Pfaden, sonst 0.5
            + 0.05 · same_item      # Kontext-Kontinuitäts-Bonus
```

**Zur Ehrlichkeit über die Terme:** Im Code heißt der dritte Term `tag_match_score`, er misst
aber keinen Tag-Treffer, sondern **Pfad-Übereinstimmung** (`1.0 if kw_score > 0 else 0.5`). Er
belohnt Objekte, die beide Pfade gefunden haben, und gibt allen anderen einen konstanten Sockel
von 0.075. Das funktioniert, ist aber nicht das, was der Name verspricht — beim Nachbau
entweder ehrlich `path_agreement` nennen oder durch echten Tag-Overlap ersetzen:

```python
tag_match = len(set(tags) & set(object_tags)) / max(len(tags), 1)
```

Der `same_item`-Term ist in der aktuellen Agira-Konfiguration faktisch wirkungslos, weil das
aktuelle Objekt ohnehin aus den Ergebnissen gefiltert wird. Beim Nachbau weglassen, außer der
Term bekommt eine eigene Bedeutung (z. B. „gehört zum selben Epic/Thread").

### 6.3 Sortierung mit Typ-Tiebreak

```python
results.sort(key=lambda x: (-x['final_score'], -TYPE_PRIORITY.get(x['object_type'], 0)))
```

Bei Score-Gleichstand entscheidet die Typ-Priorität. In Agira:
`attachment 6 > github_pr 5 > github_issue 4 > item 3 > change 2 > file 1 > project 0` —
Dokumentation schlägt Ticket. Die Rangfolge ist projektspezifisch und gehört in die Config.

### 6.4 Warum gewichtet und nicht RRF

Reciprocal Rank Fusion (`Σ 1/(k + rank)`) ist robuster, weil sie keine vergleichbaren Scores
voraussetzt. Der gewichtete Ansatz wurde gewählt, weil Weaviates `RELATIVE_SCORE` bereits
normalisierte Scores liefert und die Formel damit **interpretierbar und einzeln justierbar**
bleibt — man kann einen einzelnen Term hochdrehen und die Wirkung erklären.

Einschränkung, die man kennen muss: `RELATIVE_SCORE` normalisiert **pro Query**. Der Top-Treffer
jedes Pfades bekommt ≈1.0, unabhängig von seiner absoluten Güte. Ein Pfad, der nichts Gutes
findet, bringt seinen besten Schrott trotzdem mit Score ≈1.0 ein. **Wenn dein Backend keine
normalisierten Scores liefert oder diese Verzerrung stört: nimm RRF** (§8.2).

### 6.5 Warum Top 6

Empirisch: unterhalb ~4 fehlt Querverweis-Kontext, oberhalb ~8 steigt der Rauschanteil schneller
als der Nutzen, und Stufe 3 kann die Zeichenbudgets nicht mehr sinnvoll verteilen. 6 ist der
Startwert, kein Naturgesetz — an das Kontextfenster und die Layer-Quoten koppeln.

---

## 7. Stufe 3 — Layer-Bündelung (Fusion #3)

Aus der flachen Top-6-Liste wird ein komponierter Kontext. Drei Mechanismen greifen hier
ineinander.

### 7.1 A/B/C-Quotierung

| Layer | Inhalt (Agira) | Max | Rolle im Prompt |
|---|---|---|---|
| **A** | `attachment`, `github_pr` | 3 | Primärdokumentation, konkrete Umsetzung |
| **B** | `item`, `github_issue` | 3 | Anforderung, Ticket-Kontext |
| **C** | alles Übrige | 2 | Hintergrund |

Zuweisung in Score-Reihenfolge; ist die Zielquote voll, fällt der Treffer in die nächste freie
Quote (Overflow-Kaskade A→B→C), statt verworfen zu werden.

**Der eigentliche Gewinn ist nicht die Sortierung, sondern die Garantie.** Ohne Quoten kann eine
Objektklasse alle Plätze belegen. Mit Quoten sieht das LLM garantiert *beide* Perspektiven:
was gebaut wurde (A) und was verlangt war (B). Die Layer-Marker `[#A1]`, `[#B2]` im Prompt-Text
geben dem Modell zusätzlich eine **Vertrauenshierarchie** und ein stabiles Zitierschema.

Übertragen heißt „A/B/C" also nicht „Attachment/Item/Rest", sondern:

- **A = die verlässlichste Quellenklasse** deiner Domäne
- **B = der Anforderungs-/Absichtskontext**
- **C = Hintergrund, knapp gehalten**

### 7.2 Primary-Document-Boost

Erkenntnis aus dem Betrieb: Bei Fragen zu einem konkreten Dokument bringen sechs 6-kB-Schnipsel
weniger als *ein* Dokument mit 24 kB und fünf kurze Kontext-Schnipsel.

Auswahl des Primärdokuments:

1. **Dateinamen-Match** — Regex zieht Dateinamen (`FOO_BAR.md`, `config.py`) aus Frage,
   `core` und `phrases`; Abgleich gegen `title`/`url` der Treffer.
2. **Sonst: bester Score** unter den Dokument-Treffern.
3. **In beiden Fällen Score-Schwelle** `≥ 0.70`. Ohne diese Schwelle bekommt bei jeder
   beliebigen Frage irgendein Dokument das große Budget — die Schwelle wurde genau deshalb
   nachgerüstet.

Budget je nach „Thinking Level" des aufrufenden Features: Standard 18 000 / Extended 24 000 /
Pro 30 000 Zeichen, gegenüber 6 000 für normale Treffer.

### 7.3 Abschnittsbewusstes Trimmen

Für Markdown-Dokumente über 20 000 Zeichen wird nicht hart abgeschnitten, sondern:

1. Dokument an `#`/`##`/`###` in Abschnitte zerlegen
2. **Inhaltsverzeichnis generieren** — das Modell erfährt, was es *nicht* sieht, und kann
   gezielt nachfragen
3. Abschnitte scoren: Query-Term im Heading **2.0**, im Text **1.0**, Domänen-Bonuswort **0.5**,
   plus Längenbonus (max. 2.0)
4. Top-Abschnitte (max. 4) bis zum Budget auswählen
5. Ausgabe: **Intro + TOC + ausgewählte Abschnitte in Dokumentreihenfolge**

Punkt 5 ist wichtig: sortiere die Abschnitte für die Ausgabe *zurück in Dokumentreihenfolge*.
Nach Score sortierte Abschnitte lesen sich für ein LLM wie ein zerschnittenes Dokument.

Für Nicht-Markdown-Quellen greift dasselbe Muster über jede vorhandene Struktur: Code nach
Funktionen/Klassen, HTML nach Überschriften, PDF nach Seiten/Kapiteln.

### 7.4 Ausgabeformat

```
CONTEXT:
[#A1] (type=attachment score=0.92) Auth-Architektur.md
       Link: /attachments/42/
       ## Passwort-Validierung
       Sonderzeichen werden vor dem Hashing nicht normalisiert …

[#B1] (type=item score=0.85) Login-Refactoring
       Link: /items/123/
       Überarbeitung der Authentifizierung …

[#C1] (type=github_issue score=0.71) UTF-8 im Passwortfeld
       Link: https://github.com/…/issues/77
       …
```

Format-Regeln, die sich bewährt haben: Typ und Score **sichtbar** machen (das LLM gewichtet
danach), Link **immer** mitgeben (Quellenangaben ohne Halluzination), `status` mitliefern (sonst
warnt das Modell vor längst behobenen Bugs), und pro Layer neu durchnummerieren.

---

## 8. Referenz-Implementierung (portabel)

### 8.1 Kern der Pipeline

```python
def build_context(query, *, scope_id=None, exclude_id=None,
                  skip_optimization=False, max_content_length=6000):
    # ---- Stufe 0 ----------------------------------------------------------
    optimized = None if skip_optimization else optimize_question(query)
    if optimized is None:
        optimized = OptimizedQuery(core=query)          # Degradationspfad

    # ---- Stufe 1 (Fusion #1 passiert im Backend) --------------------------
    sem_query = " ".join([optimized.core, *optimized.synonyms[:3],
                          *optimized.phrases[:2], *optimized.tags[:2]])
    kw_query  = " ".join([*optimized.tags, optimized.core])

    sem = search(sem_query, alpha=0.6, scope_id=scope_id,
                 exclude_id=exclude_id, limit=24)
    kw  = search(kw_query,  alpha=0.3, scope_id=scope_id,
                 exclude_id=exclude_id, limit=24)

    # ---- Stufe 2 (Fusion #2) ---------------------------------------------
    fused = fuse_and_rerank(sem, kw, limit=6)

    # ---- Stufe 3 (Fusion #3) ---------------------------------------------
    a, b, c = separate_into_layers(fused, query=query, optimized=optimized,
                                   max_content_length=max_content_length)
    return Context(query=query, optimized_query=optimized,
                   layer_a=a, layer_b=b, layer_c=c,
                   stats={...})
```

```python
def fuse_and_rerank(sem_results, kw_results, limit=6):
    merged = {}
    for r in sem_results:
        merged[r['object_id']] = {**r, 'sem_score': r.get('score') or 0, 'kw_score': 0}
    for r in kw_results:
        hit = merged.get(r['object_id'])
        if hit:
            hit['kw_score'] = r.get('score') or 0
        else:
            merged[r['object_id']] = {**r, 'sem_score': 0,
                                      'kw_score': r.get('score') or 0}

    out = []
    for r in merged.values():
        agreement = 1.0 if r['kw_score'] > 0 else 0.5
        r['final_score'] = (0.60 * r['sem_score']
                          + 0.20 * r['kw_score']
                          + 0.15 * agreement)
        out.append(r)

    out.sort(key=lambda x: (-x['final_score'],
                            -TYPE_PRIORITY.get(x['object_type'], 0)))
    return out[:limit]
```

```python
def separate_into_layers(results, *, query, optimized, max_content_length):
    primary_id = determine_primary_document(results, query, optimized)
    a, b, c = [], [], []

    for r in results:
        is_primary = r['object_id'] == primary_id
        budget = primary_budget(max_content_length) if is_primary else max_content_length

        content = r.get('content', '')
        if is_primary and len(content) > SMALL_DOC_THRESHOLD:
            content = smart_trim(content, budget, query, optimized)
        elif len(content) > budget:
            content = content[:budget].rstrip() + "..."

        obj = ContextObject(**r, content=content)

        if   r['object_type'] in LAYER_A_TYPES and len(a) < 3: a.append(obj)
        elif r['object_type'] in LAYER_B_TYPES and len(b) < 3: b.append(obj)
        elif len(c) < 2:                                       c.append(obj)
        elif len(a) < 3:                                       a.append(obj)   # Overflow
        elif len(b) < 3:                                       b.append(obj)
    return a, b, c
```

### 8.2 Variante: RRF statt gewichteter Fusion

Wenn dein Backend keine vergleichbar normalisierten Scores liefert, ersetze Stufe 2 durch
Reciprocal Rank Fusion — sie braucht nur Ränge:

```python
def fuse_rrf(*ranked_lists, k=60, weights=None, limit=6):
    weights = weights or [1.0] * len(ranked_lists)
    scores, objects = {}, {}
    for lst, w in zip(ranked_lists, weights):
        for rank, r in enumerate(lst, start=1):
            oid = r['object_id']
            scores[oid] = scores.get(oid, 0) + w * (1 / (k + rank))
            objects.setdefault(oid, r)
    ranked = sorted(scores.items(),
                    key=lambda kv: (-kv[1],
                                    -TYPE_PRIORITY.get(objects[kv[0]]['object_type'], 0)))
    return [{**objects[oid], 'final_score': s} for oid, s in ranked[:limit]]

fused = fuse_rrf(sem, kw, weights=[1.0, 0.6])   # semantischer Pfad schwerer
```

RRF ist der sicherere Default für einen Neubau. Der gewichtete Ansatz lohnt erst, wenn du
normalisierte Scores hast *und* einzelne Terme bewusst tunen willst.

### 8.3 Parallelisierung

Die beiden Suchen sind unabhängig. In Agira laufen sie sequenziell — eine bekannte, bewusst in
Kauf genommene Latenzreserve. Beim Nachbau direkt parallelisieren:

```python
with ThreadPoolExecutor(max_workers=2) as pool:
    f_sem = pool.submit(search, sem_query, alpha=0.6, ...)
    f_kw  = pool.submit(search, kw_query,  alpha=0.3, ...)
    sem, kw = f_sem.result(), f_kw.result()
```

Spart ~40 % der Retrieval-Latenz bei null Qualitätsverlust.

---

## 9. Tuning-Parameter

Alle in eine **Config-Datei**, nicht in den Code. Diese Werte werden beim Einführen in einem
neuen Projekt garantiert mehrfach angefasst.

| Parameter | Agira-Wert | Wirkung beim Verstellen |
|---|---|---|
| `ALPHA_SEMANTIC` | 0.6 | ↑ konzeptueller, ↓ wörtlicher |
| `ALPHA_KEYWORD` | 0.3 | ↓ strenger auf exakte Begriffe |
| `SEARCH_LIMIT` je Pfad | 24 | ↑ mehr Fusionsmasse, mehr Latenz |
| `FUSION_LIMIT` | 6 | ↑ mehr Kontext, mehr Rauschen |
| Gewichte (0.6/0.2/0.15/0.05) | s. §6.2 | Summe ≈ 1.0 halten |
| `LAYER_QUOTAS` | A3 / B3 / C2 | steuert Kontext-Zusammensetzung |
| `MAX_CONTENT_LENGTH` | 6 000 | Standard-Budget je Treffer |
| `PRIMARY_BUDGET` | 18/24/30 k | Budget des Primärdokuments |
| `PRIMARY_MIN_SCORE` | 0.70 | ↓ zu oft geboostet, ↑ Boost greift nie |
| `SMALL_DOC_THRESHOLD` | 20 000 | ab hier Smart-Trim statt Vollaufnahme |
| `TYPE_PRIORITY` | s. §6.3 | Tiebreak bei Score-Gleichstand |
| `ALLOWED_OBJECT_TYPES` | 4 Typen | **die folgenreichste Einstellung überhaupt** |

**Vorgehen beim Tunen:** erst `ALLOWED_OBJECT_TYPES` und die Layer-Quoten, dann die Budgets,
zuletzt die Score-Gewichte. Die Gewichte sind der Parameter mit der geringsten Wirkung pro
investierter Stunde — die Zusammensetzung des Kontexts schlägt die Feinsortierung.

---

## 10. Fallstricke und bewusste Schwächen

Aus dem Agira-Betrieb, damit ein Nachbau sie nicht wiederholt:

1. **Score-Normalisierung pro Query (§6.4).** Ein Pfad ohne gute Treffer liefert seinen besten
   Treffer trotzdem mit ≈1.0 ein. Gegenmittel: RRF, oder eine absolute Mindest-Score-Schwelle
   vor der Fusion.
2. **`tag_match` misst keine Tags.** Der Term ist faktisch ein Pfad-Übereinstimmungs-Bonus
   (§6.2). Beim Nachbau umbenennen oder durch echten Tag-Overlap ersetzen.
3. **`same_item`-Bonus ist tot**, weil das aktuelle Objekt vorher gefiltert wird. Weglassen
   oder neu definieren.
4. **`entities` und `ban` werden nicht genutzt.** Der Optimierungs-Agent liefert sie, das
   Retrieval ignoriert sie. Naheliegende Erweiterung: `entities` als Metadatenfilter oder
   Score-Boost, `ban` als Negativterme. Wer neu baut, sollte sie entweder nutzen oder gar
   nicht erst erzeugen lassen.
5. **Sequenzielle Suchpfade** (§8.3) — unnötige Latenz.
6. **Kein Chunking.** Agira indiziert ganze Dokumente und repariert das nachgelagert über
   Smart-Trim. Das funktioniert überraschend gut für strukturiertes Markdown und ist eine
   ehrliche Vereinfachung. Bei langen, unstrukturierten Texten ist echtes Chunking beim
   Indexieren (mit Parent-Document-Retrieval) der bessere Weg.
7. **Keine Wirksamkeitsmessung.** Es gibt keinen Feedback-Loop und kein Relevanz-Gold-Set — die
   Parameter sind erfahrungsbasiert. Wenn du neu baust: leg früh 20–30 Frage/Erwartung-Paare an
   und miss Recall@6, bevor du an Gewichten drehst. Ohne das tunst du blind.
8. **Ein LLM-Call vor jedem Retrieval** kostet Latenz. Cache und `skip_optimization` sind
   Pflicht, kein Nice-to-have.

---

## 11. Testplan

Die Referenz hat 53 Tests (19 für die erweiterte Pipeline, 34 Basis). Minimalset für einen
Nachbau:

**Stufe 0** — valides JSON; JSON in Code-Fences; kaputtes JSON → Fallback; fehlendes Pflichtfeld
→ Fallback; Cache-Hit ohne zweiten Call.

**Stufe 1** — Query-Bau semantisch/keyword; Backend nicht erreichbar → leere Liste, keine
Exception; Filter greifen (Scope, Selbstausschluss, Typ-Whitelist); leerer `text` fliegt raus.

**Stufe 2** — Objekt in beiden Pfaden erscheint **einmal** mit beiden Scores; Formel rechnet
korrekt; Limit greift; Typ-Tiebreak bei Gleichstand.

**Stufe 3** — Quoten werden eingehalten; Overflow-Kaskade greift; Primary-Boost unterhalb der
Score-Schwelle greift **nicht**; Smart-Trim bleibt im Budget und liefert TOC; Layer-Marker und
Links im Ausgabetext vorhanden.

**Integration** — vollständiger Durchlauf; Durchlauf mit fehlgeschlagener Optimierung;
Durchlauf mit `skip_optimization`; Debug-Infos vollständig.

**Nicht-Regression:** Weaviate/Backend aus → Pipeline liefert leeren Kontext, wirft nicht.
Dieser Test ist wichtiger als er aussieht — er hält den Degradationspfad am Leben.

---

## 12. Umsetzungs-Checkliste für KI-gestützte Entwicklung

Reihenfolge für einen Nachbau, jede Stufe einzeln lauffähig und testbar:

- [ ] **Index-Schema** anlegen (§3.1), `skip_vectorization` bei IDs/URLs setzen
- [ ] **Sync/Ingestion** der Quellobjekte in den Index (inkl. Löschpfad)
- [ ] **Basis-Hybrid-Suche** mit festem `alpha` + Scope-Filter → hier schon manuell testen
- [ ] **Stufe 3 zuerst**: Layer-Quoten und Ausgabeformat auf der Basis-Suche
      — größter Qualitätssprung, unabhängig vom Rest
- [ ] **Stufe 1**: zweiten Pfad ergänzen, parallel ausführen
- [ ] **Stufe 2**: Dedup + Fusion (RRF als Default, §8.2)
- [ ] **Stufe 0**: Optimierungs-Agent inkl. Cache, Fallback und `skip_optimization`
- [ ] **Primary-Boost + Smart-Trim** (§7.2/7.3)
- [ ] **Config extrahieren** (§9), dediziertes Logging pro Stufe mit Stats
- [ ] **Testset** aus 20–30 realen Fragen, Recall@6 messen, dann tunen

Die Reihenfolge ist Absicht: **Stufe 3 vor Stufe 2 vor Stufe 1 vor Stufe 0.** Sie liefert den
Nutzen in absteigender Reihenfolge und macht jede Stufe einzeln bewertbar. Wer mit Stufe 0
anfängt, baut drei Wochen und weiß am Ende nicht, welche Stufe wirkt.

### Prompt-Vorlage für einen KI-Coding-Assistenten

> Implementiere eine RAG-Retrieval-Pipeline nach dem Blueprint in
> `docs/RAG_FUSION_PIPELINE_BLUEPRINT.md`. Backend: **\<Weaviate | Qdrant | pgvector | …\>**.
> Objekttypen: **\<…\>**, davon gehören **\<…\>** in Layer A und **\<…\>** in Layer B.
> Halte dich an die Stufenreihenfolge aus §12 und implementiere pro Schritt die Tests aus §11,
> bevor du den nächsten beginnst. Verwende RRF für Stufe 2 (§8.2). Alle Parameter aus §9 gehören
> in eine eigene Config-Datei. Jede Stufe muss einen Degradationspfad haben: fällt eine Stufe
> aus, liefert die Pipeline ein schlechteres, aber gültiges Ergebnis — nie eine Exception.

---

## 13. Anhang: Herkunft und Quellen

Entstanden in Agira über mehrere Iterationen:

| Ausbaustufe | Ergebnis |
|---|---|
| Basis-Pipeline | Hybrid-Suche, alpha-Heuristik, Dedup, Typ-Priorität |
| Erweiterte Pipeline | Query-Optimierung, zwei Suchpfade, gewichtete Fusion, A/B/C-Layer |
| Retrieval-Fokussierung | Selbstfund-Ausschluss, Typ-Whitelist, Leerinhalt-Filter |
| Dokumentationszentrierung | A/B/C-Neuzuschnitt, `attachment` in Layer A, neue Typ-Prioritäten |
| Primary-Boost | Primärdokument-Erkennung, gestaffelte Budgets, Smart-Trim |
| Nachschärfung | Score-Schwelle 0.70 für den Boost |

Code in diesem Repository:

- `core/services/rag/extended_service.py` — Pipeline, alle drei Fusionsstufen
- `core/services/rag/config.py` — sämtliche Tuning-Parameter
- `core/services/rag/models.py` — Kontext-Datenmodelle
- `agents/question-optimization-agent.yml` — Stufe 0, Prompt und Cache-Policy
- `core/services/weaviate/schema.py` — Index-Schema
- `core/services/rag/test_extended_rag.py` — Testsuite
