# Agira v0.1 - Setup Guide

## Anforderungen

- Python 3.12 oder höher
- PostgreSQL 15+ (für Produktion) oder SQLite (für Entwicklung)
- pip (Python Package Manager)

## Installation

### 1. Repository klonen

```bash
git clone https://github.com/gdsanger/Agira.git
cd Agira
```

### 2. Virtuelle Umgebung erstellen und aktivieren

```bash
python -m venv venv
source venv/bin/activate  # Unter Windows: venv\Scripts\activate
```

### 3. Abhängigkeiten installieren

```bash
pip install -r requirements.txt
```

### 4. Umgebungsvariablen konfigurieren

Kopieren Sie `.env.example` nach `.env` und passen Sie die Werte an:

```bash
cp .env.example .env
```

Bearbeiten Sie `.env` und konfigurieren Sie:

- `SECRET_KEY`: Generieren Sie einen sicheren Secret Key für Produktion
- `DEBUG`: Setzen Sie auf `False` in Produktion
- `ALLOWED_HOSTS`: Fügen Sie Ihre Domain hinzu
- Datenbank-Einstellungen (siehe unten)

#### Datenbank-Konfiguration

**Für Entwicklung (SQLite):**
```env
DB_ENGINE=django.db.backends.sqlite3
DB_NAME=db.sqlite3
```

**Für Produktion (PostgreSQL):**
```env
DB_ENGINE=django.db.backends.postgresql
DB_NAME=agira
DB_USER=agira_user
DB_PASSWORD=your-secure-password
DB_HOST=localhost
DB_PORT=5432
```

### 5. PostgreSQL Datenbank erstellen (nur für PostgreSQL)

```bash
# PostgreSQL Benutzer und Datenbank erstellen
sudo -u postgres psql
CREATE DATABASE agira;
CREATE USER agira_user WITH PASSWORD 'your-secure-password';
ALTER ROLE agira_user SET client_encoding TO 'utf8';
ALTER ROLE agira_user SET default_transaction_isolation TO 'read committed';
ALTER ROLE agira_user SET timezone TO 'UTC';
GRANT ALL PRIVILEGES ON DATABASE agira TO agira_user;
\q
```

### 6. Datenbank-Migrationen ausführen

```bash
python manage.py migrate
```

### 7. Superuser erstellen

```bash
python manage.py createsuperuser
```

### 8. Server starten

```bash
python manage.py runserver
```

Die Anwendung ist nun unter `http://localhost:8000` erreichbar.

## Projekt-Struktur

```
Agira/
├── agira/              # Django Projekt-Einstellungen
│   ├── settings.py     # Haupt-Konfiguration
│   ├── urls.py         # URL-Routing
│   └── wsgi.py         # WSGI-Konfiguration
├── core/               # Kern-App
│   ├── views.py        # Views
│   └── urls.py         # App-URLs
├── static/             # Statische Dateien
│   └── css/
│       └── site.css    # Zentrale CSS-Datei
├── templates/          # Django Templates
│   ├── base.html       # Basis-Template
│   └── home.html       # Homepage
├── manage.py           # Django Management-Skript
├── requirements.txt    # Python-Abhängigkeiten
└── .env.example        # Beispiel-Umgebungsvariablen
```

## Tech-Stack

- **Backend:** Python 3.12, Django 5.2
- **Frontend:** Django Templates, HTMX 2.0
- **UI Framework:** Bootstrap 5.3 (Dark Mode)
- **Datenbank:** PostgreSQL (Produktion) / SQLite (Entwicklung)
- **CSS:** Zentrale `site.css` mit Dark Mode Optimierung

## Features (v0.1)

✅ Django Projekt-Setup  
✅ PostgreSQL/SQLite Datenbank-Unterstützung  
✅ Bootstrap 5.3 Dark Mode Integration  
✅ HTMX Integration  
✅ Zentrale CSS-Datei mit angenehmer Dark Mode Farbpalette  
✅ Saubere Projektstruktur  
✅ Umgebungsvariablen-Konfiguration  
✅ Homepage mit Feature-Übersicht  

## Nächste Schritte

Die folgenden Features werden in zukünftigen Versionen implementiert:

- Django Models für Projekt, Item, Release, Change
- Admin-Interface-Anpassungen
- Inbox / Backlog Views
- Change- & Approval-UI
- Mail-Ingestion
- GitHub Integration
- Sentry Integration
- KI-Unterstützung

## Entwicklung

### Static Files sammeln (für Produktion)

```bash
python manage.py collectstatic
```

### Tests ausführen

```bash
python manage.py test
```

## Lizenz

Siehe [LICENSE](LICENSE) Datei.
