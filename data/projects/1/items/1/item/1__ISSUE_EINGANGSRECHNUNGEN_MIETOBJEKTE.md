# 🎯 Issue: Eingangsrechnungen pro Mietobjekt (Nebenkosten / Energie / Betrieb / Reparaturen)

## Ziel
Im Bereich **Vermietung → Mietobjekte** sollen **Eingangsrechnungen** erfasst und verwaltet werden können (Nebenkosten, Energiekosten, Betriebskosten, Reparaturen usw.).

Wichtig:
- Standardfall: **eine** Kostenart pro Rechnung
- Ausnahmefall: eine Rechnung enthält mehrere Kostenarten → **minimaler Split** nach Kostenarten
- **Dokument/Beleg-Upload ist explizit nicht Bestandteil dieses Issues** (kommt in separatem Issue inkl. KI-Erkennung)
- Umlage erfolgt **immer flächenbasiert (qm)**

---

## Fachliche Anforderungen

### Eingangsrechnung – Felder
- **Lieferant** (Auswahl aus Lieferanten)
- **Belegdatum**
- **Fälligkeit**
- **Belegnummer**
- **Betreff**
- **Referenznummer**
- **Leistungszeitraum von** (optional)
- **Leistungszeitraum bis** (optional)
- **Notizen** (Langtext / Textarea)
- **Status** (ENUM: Neu, Prüfung, Offen, Klärung, Bezahlt)
- **Mietobjekt** (Auswahl aus Mietobjekten)
- **Umlagefaehig** (Boolean)
- **Zahlungsdatum** (nur bei Status = Bezahlt)

### Beträge
- **Nettobetrag** (berechnet)
- **Umsatzsteuer** (berechnet)
- **Bruttobetrag** (berechnet)

> Die Umsatzsteuer wird **nicht manuell** erfasst, sondern kommt aus der Kostenart (0 %, 7 %, 19 %).

---

## Kostenaufteilung (nur nach Kostenarten)

### Motivation
Wenn eine Rechnung mehrere Themen enthält (z. B. *Winterdienst* + *Reparaturen*), muss sie auf mehrere Kostenarten aufgeteilt werden.

### Prinzip
- Keine Material‑ oder Detailpositionen
- Aufteilung **ausschließlich nach Kostenarten**

### EingangsrechnungAufteilung
- **Kostenart 1** (Auswahl aus `Core.Kostenarten1`)
- **Kostenart 2** (untergeordnet, abhängig von Kostenart 1)
- **Nettobetrag**
- (optional) Kurztext

**Berechnung pro Aufteilung**
- Umsatzsteuer-Satz aus Kostenart (0/7/19)
- `USt = Netto * Steuersatz`
- `Brutto = Netto + USt`

### Standardfall
- Beim Anlegen wird automatisch **eine Aufteilung** erzeugt
- Benutzer wählt nur Kostenart + Netto

---

## Summen & Validierungen

### Summen
Die Summen der Eingangsrechnung ergeben sich **ausschließlich aus den Aufteilungen**:
- Netto = Summe Netto
- Umsatzsteuer = Summe USt
- Brutto = Netto + Umsatzsteuer

### Validierungsregeln
- Kostenart2 muss zu Kostenart1 passen
- Netto ≥ 0
- Leistungszeitraum: von ≤ bis
- Status **Bezahlt** erfordert ein Zahlungsdatum

---

## Workflow / Aktionen

### Action: „Bezahlt …“
- Button in der Detailansicht
- Fragt Zahlungsdatum ab (Default: heute)
- Setzt:
  - `status = Bezahlt`
  - `zahlungsdatum = gewähltes Datum`

Action ist nur verfügbar, wenn Status ≠ Bezahlt.

---

## UI-Anforderungen

### Mietobjekt – Detail
- Neuer Tab **„Eingangsrechnungen“**
- Tabelle:
  - Belegdatum
  - Lieferant
  - Betreff
  - Belegnummer
  - Netto / Brutto
  - Status
  - Fälligkeit
  - Umlagefaehig
  - Aktionen (Detail, Bearbeiten)

### Aufteilungen UI
- Inline-Tabelle im Formular
- Zeilen hinzufügen / entfernen
- Live-Berechnung von USt & Brutto

---

## Out of Scope
- Dokumente / Belege / OCR / KI-Erkennung
- Zahlungsverkehr / Banking
- Umlage- & Nebenkostenabrechnung auf Mieter
- Individuelle Umlageschlüssel

---

**Status:** ⬜ Offen  
**Priorität:** Mittel–Hoch  
**Modul:** Vermietung / Mietobjekte
