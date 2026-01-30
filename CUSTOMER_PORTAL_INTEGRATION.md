# Customer Portal - Dokumentation zur Integration

## Übersicht

Das **Customer Portal** (auch **Embed Portal** genannt) ermöglicht es, Projektissues von Agira in externe Websites oder Anwendungen einzubetten. Kunden oder externe Partner können so Issues einsehen, erstellen und kommentieren, ohne direkten Zugriff auf das Hauptsystem haben zu müssen.

### Hauptmerkmale

- **Token-basierte Authentifizierung** – Sicherer Zugriff ohne Benutzerverwaltung
- **iFrame-Integration** – Einfache Einbettung in bestehende Websites
- **Read-Only und Create-Modus** – Kunden können Issues ansehen und erstellen
- **Kommentarfunktion** – Externe Nutzer können öffentliche Kommentare hinzufügen
- **Projektspezifisch** – Jeder Token gewährt Zugriff auf genau ein Projekt
- **Ein-/Ausschaltbar** – Tokens können jederzeit deaktiviert werden

---

## 1. Voraussetzungen

Um das Customer Portal zu nutzen, benötigen Sie:

1. Eine laufende **Agira-Installation** (Backend)
2. Zugriff auf das **Django Admin Interface**
3. Ein bestehendes **Projekt** in Agira
4. Eine **Organisation**, die Zugriff auf das Projekt erhalten soll

---

## 2. Einrichtung: Embed Token generieren

### 2.1 Über das Django Admin Interface

1. Melden Sie sich im Django Admin an: `https://ihr-agira-server.de/admin/`
2. Navigieren Sie zu **Core** → **Organisation Embed Projects**
3. Klicken Sie auf **Add Organisation Embed Project**
4. Wählen Sie die entsprechende **Organisation** aus
5. Wählen Sie das entsprechende **Projekt** aus
6. Stellen Sie sicher, dass **Is enabled** aktiviert ist
7. Klicken Sie auf **Save**

Das System generiert automatisch einen **kryptographisch sicheren Token** (64 Zeichen, URL-safe).

### 2.2 Token anzeigen

Nach dem Speichern wird der Token im Admin-Interface angezeigt:

- **Im Detail-View**: Der vollständige Token wird im Feld `Embed Token` angezeigt
- **In der Listen-Ansicht**: Der Token wird maskiert angezeigt (erste 8 + letzte 8 Zeichen)

⚠️ **Wichtig**: Kopieren Sie den vollständigen Token sofort. Sie benötigen ihn für die Integration.

### 2.3 Token verwalten

**Token rotieren (erneuern):**
1. Wählen Sie im Admin-Interface ein oder mehrere Embed Projects aus
2. Wählen Sie die Aktion **"Rotate embed token (invalidates old token)"**
3. Klicken Sie auf **Go**
4. Das System generiert einen neuen Token – der alte Token ist ab sofort ungültig

**Token deaktivieren:**
1. Öffnen Sie das entsprechende Embed Project im Admin
2. Deaktivieren Sie **Is enabled**
3. Speichern Sie die Änderung
4. Der Token bleibt bestehen, aber alle Zugriffe werden mit HTTP 403 (Forbidden) abgelehnt

---

## 3. Integration in ein externes Projekt

### 3.1 Basis-Integration via iFrame

Die einfachste Methode ist die Einbettung über ein iFrame:

```html
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Support Portal</title>
    <style>
        body {
            margin: 0;
            padding: 0;
            font-family: Arial, sans-serif;
        }
        .portal-container {
            width: 100%;
            height: 100vh;
            border: none;
        }
    </style>
</head>
<body>
    <iframe 
        src="https://ihr-agira-server.de/embed/projects/1/issues/?token=IHR_EMBED_TOKEN_HIER"
        class="portal-container"
        title="Customer Portal">
    </iframe>
</body>
</html>
```

**Parameter anpassen:**
- Ersetzen Sie `ihr-agira-server.de` mit Ihrer Agira-Domain
- Ersetzen Sie `1` mit Ihrer Projekt-ID
- Ersetzen Sie `IHR_EMBED_TOKEN_HIER` mit dem generierten Token

### 3.2 Integration in eine React/Vue/Angular App

**React Beispiel:**

```jsx
import React from 'react';

const CustomerPortal = () => {
  const AGIRA_URL = 'https://ihr-agira-server.de';
  const PROJECT_ID = 1;
  const EMBED_TOKEN = 'IHR_EMBED_TOKEN_HIER';
  
  const portalUrl = `${AGIRA_URL}/embed/projects/${PROJECT_ID}/issues/?token=${EMBED_TOKEN}`;
  
  return (
    <div style={{ width: '100%', height: '100vh' }}>
      <iframe
        src={portalUrl}
        style={{ width: '100%', height: '100%', border: 'none' }}
        title="Customer Portal"
      />
    </div>
  );
};

export default CustomerPortal;
```

**Vue.js Beispiel:**

```vue
<template>
  <div class="portal-container">
    <iframe 
      :src="portalUrl"
      title="Customer Portal"
      class="portal-iframe"
    />
  </div>
</template>

<script>
export default {
  name: 'CustomerPortal',
  data() {
    return {
      agiraUrl: 'https://ihr-agira-server.de',
      projectId: 1,
      embedToken: 'IHR_EMBED_TOKEN_HIER'
    };
  },
  computed: {
    portalUrl() {
      return `${this.agiraUrl}/embed/projects/${this.projectId}/issues/?token=${this.embedToken}`;
    }
  }
};
</script>

<style scoped>
.portal-container {
  width: 100%;
  height: 100vh;
}
.portal-iframe {
  width: 100%;
  height: 100%;
  border: none;
}
</style>
```

### 3.3 Integration mit Server-seitiger Token-Verwaltung

Für erhöhte Sicherheit können Sie den Token serverseitig speichern:

**Node.js/Express Beispiel:**

```javascript
const express = require('express');
const app = express();

// Token sicher in Umgebungsvariablen speichern
const AGIRA_URL = process.env.AGIRA_URL;
const EMBED_TOKEN = process.env.AGIRA_EMBED_TOKEN;
const PROJECT_ID = process.env.AGIRA_PROJECT_ID;

app.get('/portal', (req, res) => {
  const portalUrl = `${AGIRA_URL}/embed/projects/${PROJECT_ID}/issues/?token=${EMBED_TOKEN}`;
  
  res.send(`
    <!DOCTYPE html>
    <html>
    <head>
      <title>Support Portal</title>
      <style>
        body { margin: 0; padding: 0; }
        iframe { width: 100%; height: 100vh; border: none; }
      </style>
    </head>
    <body>
      <iframe src="${portalUrl}" title="Customer Portal"></iframe>
    </body>
    </html>
  `);
});

app.listen(3000);
```

**.env Datei:**
```env
AGIRA_URL=https://ihr-agira-server.de
AGIRA_PROJECT_ID=1
AGIRA_EMBED_TOKEN=IhrGenerierterTokenHier123456789...
```

---

## 4. Verfügbare Endpoints

Das Customer Portal stellt folgende Endpoints zur Verfügung:

### 4.1 Issue-Liste anzeigen
```
GET /embed/projects/<project_id>/issues/?token=<embed_token>
```

**Beschreibung:** Zeigt alle Issues des Projekts in einer Tabelle an

**Response:** HTML-Seite mit Issue-Übersicht

**Funktionen:**
- Sortiert nach Aktualisierungsdatum (neueste zuerst)
- Zeigt ID, Titel, Typ, Status, Zuständiger, Update-Datum
- Klick auf eine Zeile → Detail-Ansicht

### 4.2 Issue-Details anzeigen
```
GET /embed/issues/<issue_id>/?token=<embed_token>
```

**Beschreibung:** Zeigt Details eines Issues inkl. öffentlicher Kommentare

**Response:** HTML-Seite mit Issue-Details

**Funktionen:**
- Vollständige Issue-Informationen
- Öffentliche Kommentare (chronologisch sortiert)
- Formular zum Hinzufügen neuer Kommentare

### 4.3 Issue erstellen (Formular)
```
GET /embed/projects/<project_id>/issues/create/?token=<embed_token>
```

**Beschreibung:** Zeigt ein Formular zum Erstellen eines neuen Issues

**Response:** HTML-Formular

**Felder:**
- **Title** (Pflichtfeld, max. 500 Zeichen)
- **Type** (Pflichtfeld, Dropdown mit aktiven Issue-Typen)
- **Description** (Optional, Textarea)

### 4.4 Issue erstellen (Submit)
```
POST /embed/projects/<project_id>/issues/create/submit/?token=<embed_token>
```

**Beschreibung:** Erstellt ein neues Issue

**Request Body (form-data):**
```
title: "Mein Issue-Titel"
type: 1
description: "Detaillierte Beschreibung..."
token: <embed_token>
```

**Response:** Redirect zu `/embed/issues/<new_issue_id>/?token=<embed_token>`

**Validation:**
- Title darf nicht leer sein
- Title max. 500 Zeichen
- Type muss eine gültige, aktive Type-ID sein

### 4.5 Kommentar hinzufügen
```
POST /embed/issues/<issue_id>/comments/?token=<embed_token>
```

**Beschreibung:** Fügt einen Kommentar zu einem Issue hinzu

**Request Body (form-data):**
```
body: "Mein Kommentar-Text..."
token: <embed_token>
```

**Response:** Redirect zu `/embed/issues/<issue_id>/?token=<embed_token>`

**Eigenschaften:**
- Kommentare werden als **öffentlich** markiert
- Autor ist `None` (externes System)
- Visibility: `PUBLIC`
- Kind: `COMMENT`

---

## 5. Sicherheitsaspekte

### 5.1 Token-Sicherheit

✅ **Best Practices:**

1. **Niemals im Client-Code hardcoden** – Token können über Backend-APIs bereitgestellt werden
2. **HTTPS verwenden** – Schützt Token vor Man-in-the-Middle-Angriffen
3. **Regelmäßig rotieren** – Erneuern Sie Tokens in regelmäßigen Abständen
4. **Sofort deaktivieren bei Kompromittierung** – Setzen Sie `is_enabled=False` im Admin

⚠️ **Zu vermeiden:**

- Token in öffentlichen Git-Repositories committen
- Token in URL-Parametern loggen
- Token mit Dritten teilen

### 5.2 Zugriffskontrolle

Das System validiert bei jedem Request:

1. **Token vorhanden?** → Falls nein: HTTP 404
2. **Token gültig?** → Falls nein: HTTP 404
3. **Token aktiviert?** → Falls nein: HTTP 403
4. **Projekt-ID korrekt?** → Falls nein: HTTP 404
5. **Issue gehört zum Projekt?** → Falls nein: HTTP 404

### 5.3 CSRF-Schutz

Die Embed-Endpoints sind **CSRF-exempt**, da:
- Externe Systeme kein Django CSRF-Token haben
- Sicherheit durch Embed-Token gewährleistet wird
- Alle Endpoints den Token validieren

### 5.4 Datenexposition

**Sichtbar für externe Nutzer:**
- Alle Issues des Projekts
- Öffentliche Kommentare (`visibility=PUBLIC`)
- Item-Metadaten (Typ, Status, Zuständiger)

**NICHT sichtbar:**
- Interne Kommentare (`visibility=INTERNAL`)
- Andere Projekte
- Benutzer-Details
- System-Konfiguration

---

## 6. Beispiel-Workflows

### 6.1 Kunde meldet einen Bug

1. Kunde öffnet das eingebettete Portal
2. Klickt auf **"New Issue"**
3. Füllt Formular aus:
   - Title: "Login funktioniert nicht"
   - Type: "Bug"
   - Description: "Nach Eingabe der Credentials erscheint Fehlermeldung..."
4. Klickt auf **"Create Issue"**
5. System erstellt Issue mit Status `INBOX`
6. Kunde wird zur Detail-Ansicht weitergeleitet

### 6.2 Support antwortet auf Issue

1. Interner Mitarbeiter sieht Issue im Agira-System
2. Fügt einen **öffentlichen Kommentar** hinzu: "Wir prüfen das Problem..."
3. Kunde sieht den Kommentar im Portal
4. Kunde kann antworten: "Vielen Dank für die schnelle Reaktion"

### 6.3 Issue wird geschlossen

1. Entwickler behebt Bug und ändert Status zu `DONE`
2. Kunde sieht den aktualisierten Status im Portal
3. Issue bleibt sichtbar, kann aber nicht mehr bearbeitet werden

---

## 7. Anpassungen und Styling

### 7.1 Standard-Layout

Das Customer Portal nutzt:
- **Bootstrap 5.3** für Styling
- **Bootstrap Icons** für Icons
- **Responsive Design** (mobile-friendly)
- **Deutsches Layout** (anpassbar)

### 7.2 Eigene Styles hinzufügen

Da die Integration via iFrame erfolgt, können Sie **keine direkten CSS-Änderungen** am Portal vornehmen. Alternativen:

**Option 1: Wrapper-Styling**
```html
<div class="custom-portal-wrapper">
  <iframe src="..." class="portal-frame"></iframe>
</div>

<style>
.custom-portal-wrapper {
  border: 2px solid #007bff;
  border-radius: 8px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.1);
  overflow: hidden;
}
</style>
```

**Option 2: Agira-Templates anpassen**
Für weitreichende Anpassungen können Sie die Templates in Ihrer Agira-Installation anpassen:
- `/templates/embed/base.html` – Basis-Layout
- `/templates/embed/issue_list.html` – Issue-Liste
- `/templates/embed/issue_detail.html` – Issue-Details
- `/templates/embed/issue_create.html` – Formular

---

## 8. Troubleshooting

### Problem: "Invalid token" (HTTP 404)

**Ursachen:**
- Token wurde falsch kopiert
- Token wurde rotiert und ist jetzt ungültig
- Tippfehler in der URL

**Lösung:**
- Prüfen Sie den Token im Django Admin
- Kopieren Sie den Token erneut
- Stellen Sie sicher, dass keine Leerzeichen vor/nach dem Token sind

### Problem: "Access disabled" (HTTP 403)

**Ursache:**
- `is_enabled` ist auf `False` gesetzt

**Lösung:**
- Öffnen Sie das Embed Project im Admin
- Setzen Sie `is_enabled` auf `True`
- Speichern Sie die Änderung

### Problem: "Project not found" (HTTP 404)

**Ursachen:**
- Falsche Projekt-ID in der URL
- Projekt wurde gelöscht
- Token gehört zu einem anderen Projekt

**Lösung:**
- Prüfen Sie die Projekt-ID im Admin
- Stellen Sie sicher, dass Token und Projekt-ID zusammenpassen

### Problem: Issue wird nicht angezeigt

**Ursachen:**
- Issue gehört zu einem anderen Projekt
- Issue wurde gelöscht

**Lösung:**
- Prüfen Sie im Admin, welchem Projekt das Issue zugeordnet ist
- Verwenden Sie den korrekten Token für das entsprechende Projekt

### Problem: Kommentare nicht sichtbar

**Ursache:**
- Kommentar ist als `INTERNAL` markiert

**Lösung:**
- Im Agira-System: Ändern Sie Kommentar-Visibility zu `PUBLIC`
- Nur öffentliche Kommentare werden im Portal angezeigt

---

## 9. API-Integration (Erweitert)

Für fortgeschrittene Integrationen können Sie die Endpoints auch via API nutzen:

### 9.1 Issue-Daten abrufen

Da die Endpoints HTML zurückgeben, empfiehlt sich für API-Nutzung eine Custom-Integration oder JSON-Endpoints (falls verfügbar).

**Aktuell unterstützt:** HTML-Responses für iFrame-Integration

**Für JSON-API:** Sie können die Endpoints erweitern oder GraphQL nutzen (falls in Ihrer Installation verfügbar)

### 9.2 Programmatisches Issue-Erstellen

```python
import requests

url = "https://ihr-agira-server.de/embed/projects/1/issues/create/submit/"
payload = {
    'title': 'Automatisch erstelltes Issue',
    'type': 1,
    'description': 'Dieses Issue wurde programmatisch erstellt',
    'token': 'IHR_EMBED_TOKEN'
}

response = requests.post(url, data=payload, allow_redirects=False)
if response.status_code == 302:
    print("Issue erfolgreich erstellt")
    print(f"Redirect: {response.headers['Location']}")
```

---

## 10. Zusammenfassung

Das Customer Portal bietet eine **sichere, einfache Methode**, um Kunden oder Partner direkten Zugriff auf Projektissues zu geben:

✅ **Vorteile:**
- Keine Benutzerverwaltung notwendig
- Einfache iFrame-Integration
- Token-basierte Sicherheit
- Jederzeit ein-/ausschaltbar
- Projektspezifisch isoliert

⚠️ **Einschränkungen:**
- Nur Read & Create (keine Edit/Delete)
- Nur öffentliche Kommentare sichtbar
- Ein Token = ein Projekt
- HTML-basiert (keine native JSON-API)

📋 **Nächste Schritte:**
1. Embed Token im Admin generieren
2. iFrame in Ihre Website einbauen
3. Token sicher speichern (Umgebungsvariablen)
4. Testen mit Testdaten
5. Produktiv schalten

---

## Support

Bei Fragen oder Problemen:
- Prüfen Sie die Django Admin Logs
- Kontaktieren Sie Ihren Agira-Administrator
- Erstellen Sie ein Issue im Agira-Repository (falls Open Source)

**Dokumentation erstellt:** Januar 2026  
**Version:** 1.0
