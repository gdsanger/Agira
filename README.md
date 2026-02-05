# Agira

Agira ist ein pragmatisches Projekt-, Change- und Arbeitsmanagement-System für Softwareentwicklung  
mit starkem Fokus auf **Nachvollziehbarkeit**, **Integration** und **KI-Unterstützung**. 

Agira folgt bewusst einem **Kigil-Prinzip**:  
> *Der Weg von Idee → Umsetzung → Deployment soll so kurz, klar und transparent wie möglich sein.*

---

## Motivation

Klassische Tools wie Jira, Azure DevOps oder GitHub Projects sind mächtig –  
aber:
- zu prozesslastig
- zu projektspezifisch konfigurierbar
- schwer nachvollziehbar für Außenstehende
- unnötig komplex für kleine bis mittlere Teams
- schlecht geeignet für **Change- & Audit-Szenarien**

Agira verfolgt einen anderen Ansatz:
- **wenige, klare Konzepte**
- **keine Methodendogmen**
- **keine Projekt-spezifischen Prozessdefinitionen**
- **ein System, das sich dem Entwickler anpasst – nicht umgekehrt**

---

## Kernprinzipien

- **Projekt = Repo = logische Einheit**
- **Items sind universell** (Bug, Feature, Task, Idee, Spike …)
- **Parent/Child statt Epic/Story/Task-Hierarchie**
- **Abhängigkeiten explizit, nicht implizit**
- **Release = Version**
- **Change = konkretes Deployment**
- **Auditfähigkeit ohne Bürokratie**
- **KI als Assistenz, nicht als Zwang**

---

## Technologiestack

- **Backend:** Python, Django
- **UI:** Django Admin + HTMX + Bootstrap
- **Datenbank:** PostgreSQL
- **Storage:** Lokaler Filesystem-Storage (keine Cloud-Abhängigkeit)
- **Vektor-Datenbank:** Weaviate
- **Integrationen:**
  - GitHub (Issues & PRs)
  - Sentry
  - E-Mail (Mail In/Out)
  - optionale Systeme (Zammad, Graph API, Google PSE)
- **KI:** Agentenbasierte Architektur (adaptiert aus KIGate)

- Bei der Uis muss auf Usability geachtet werden. Sie muss mindest Qualitätsstandard eines Premium Tools wie Jira, JetBrains, DevOps usw. erfüllen. Die einfache und pragmatische Struktur muss in der UI abgebildet sein. 

---

## Zentrale Domänen

### Projekt
- Logische Klammer
- Genau **ein GitHub-Repository**
- Optional mehrere Kunden/Organisationen
- Sentry-Integration auf Projektebene

### Item
- Zentrale Arbeitseinheit
- Kann sein: Bug, Feature, Task, Idee, Spike, Change-Auslöser
- Frei verschachtelbar (Parent/Child)
- Kann Abhängigkeiten zu anderen Items haben
- Kann GitHub Issues & PRs zugeordnet bekommen
- Hat Kommentare, Kommunikation und Attachments

### Release
- Repräsentiert eine ausgelieferte Version
- Items können als „ausgeliefert in Release X“ markiert werden
- Grundlage für Changelog und Historie

### Change
- Repräsentiert **ein konkretes Deployment / Update**
- Jeder Deployment-Vorgang hat **genau einen Change**
- Bündelt Items
- Enthält Risiko, Rollback, Kommunikationsplan
- Kann (optional) an ein Release gebunden sein
- Ist auditfähig

### Change Approval
- Minimalistisch, aber revisionssicher
- Definiert:
  - wer approven muss
  - wer approved hat
  - wann entschieden wurde
- Keine Rollenmatrix, keine Prozesslogik im Modell
- UI entscheidet, **wer required ist**

---

## Kommunikation & Nachvollziehbarkeit

### Kommentare
- Notizen
- Öffentliche / interne Kommentare
- Eingehende & ausgehende E-Mails
- Threading (Message-ID, Reply-To)

### Attachments
- Lokal gespeichert
- Metadaten in DB
- An Projekt, Item oder Kommentar anhängbar
- UI kann daraus eine Ordnerstruktur aufbauen

### Activity Stream
- Zentrale Aktivitätschronik
- Änderungen, Statuswechsel, GitHub-Syncs, Approvals
- Grundlage für Dashboard & Audit

---

## KI-Integration

Agira ist von Anfang an **KI-ready**, aber nicht KI-zentriert.

- KI kann:
  - Fragen beantworten
  - Kontext aus Weaviate nutzen
  - Issues vorfiltern / vortriagieren
  - Texte zusammenfassen oder formulieren
- KI **entscheidet nicht allein**
- Entscheidungen bleiben nachvollziehbar und menschlich

Langfristige Idee:
- Eingang von Anfragen über KI-Chat
- Mail-Pipeline mit KI-Unterstützung
- KI als Assistenz, nicht als Gatekeeper

---

## Kein Multi-Tenant-System (bewusst)

Agira ist **SaaS-fähig**, aber **nicht mandantenfähig im klassischen Sinne**.

Gedanke:
- Pro Installation ein dedizierter Server
- Klare Datenhoheit
- Keine DSGVO-Komplexität durch Mandanten-Mischung
- Bessere Skalierbarkeit und Isolation

---

## Zielgruppe

- Kleine bis mittlere Entwicklerteams
- Interne IT-Abteilungen
- Agenturen mit klarer Kundenstruktur
- Entwickler, die:
  - Verantwortung tragen
  - pragmatisch arbeiten
  - kein Prozess-Overhead wollen

---

## Status

- Datenmodell: **final (v1)**
- Nächste Schritte:
  - Django Models
  - Admin UI
  - Inbox / Backlog Views
  - Change- & Approval-UI
  - Mail-Ingestion

Agira ist ein **Arbeitswerkzeug**, kein Framework, kein Methodenzwang.

---

## Management Commands

### Backfill Item Relations

To migrate existing parent-child relationships from the `Item.parent` field to `ItemRelation` entries:

```bash
# Dry-run mode (shows what would be created without making changes)
python manage.py backfill_item_relations --dry-run

# Actually create the relations
python manage.py backfill_item_relations
```

This command:
- Creates `ItemRelation` entries with `type=Related` for all items with a `parent` field set
- Is **idempotent** - running multiple times won't create duplicates
- Only creates relations that don't already exist
- Provides detailed output showing which relations were created, skipped, or had errors

---

## Leitgedanke

> *Agira soll nicht vorschreiben, wie gearbeitet wird –  
> sondern sichtbar machen, **was** gemacht wurde, **warum**, **wann** und **von wem**.*

## License & Usage

Agira is licensed under the **Business Source License (BSL 1.1)**.

### What this means:
- You may use Agira internally without restriction
- You may adapt it to your own needs
- You may use it in customer or institutional projects
- All features are available to all users

### What is not allowed:
- Offering Agira as a SaaS or hosted service
- Selling Agira or derived products
- Redistributing Agira as a standalone product

Agira was developed as a private project and is provided in good faith.
It is intended for productive use, learning, and collaboration —
not for commercial exploitation without agreement.

For commercial licensing or special use cases, please contact the author.

---
