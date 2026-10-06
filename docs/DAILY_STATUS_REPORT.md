# Täglicher Status-Report

Täglich um **07:30 Europe/Berlin** (auch am Wochenende) verschickt Agira einen
projektübergreifenden Report über alle Items als HTML-Mail mit Text-Fallback.
Erzeugt wird er direkt aus der Datenbank durch das Management-Command
`daily_status_report`.

## Inhalt

Stichtagsfenster: Vortag 07:30 bis Stichtag 07:30 (lokale Zeit). An den Tagen
der Zeitumstellung ist das Fenster 23 h (März) bzw. 25 h (Oktober) lang, die
Fenster schließen lückenlos aneinander an.

1. **Neue Items (24 h)** – Basis `created_at`; ID, Titel, Projekt, Requester.
2. **Statusverteilung** – offene Items je Status (Inbox, Backlog, Working,
   Testing, Review, Ready for Release), zusätzlich je Projekt (nur Projekte mit
   offenen Items).
3. **Geschlossen (24 h)** – Items, die im Fenster tatsächlich auf `Closed`
   gewechselt sind (aus `ItemStatusChange`, nicht `updated_at`); ID, Titel,
   Projekt, Responsible. Mehrfaches Schließen im Fenster zählt einmal.
4. **Requester** – offene Items je Requester (Name), eigene Zeile „ohne Requester“.
5. **Responsible in Bearbeitung** – Items in Working/Testing/Review je
   Responsible, eigene Zeile „ohne Responsible“.
6. **Verlauf 7 Tage** – je Tag neu, geschlossen, Bestand offen und je Status;
   Tabelle plus Inline-Balkendiagramm (nur Tabellen/`bgcolor`, rendert in Outlook).

## Datengrundlage / Historie

- **`ItemStatusChange`** – jeder Statuswechsel wird in `Item.save()` protokolliert
  (`from_status`, `to_status`, `changed_at`, `changed_by`), die Anlage eines Items
  als `'' → Startstatus`. Damit sind alle Pfade erfasst (UI, API, MCP, Worker,
  GitHub-Sync), nicht nur die, die explizit ins Activity-Log schreiben.
  `changed_by` wird gesetzt, wo der Akteur bekannt ist (Workflow-Guard,
  Item-Bearbeitung in der UI).
- Bei der Migration `0082_item_status_history` werden vorhandene
  `item.status_changed`-Einträge aus dem Activity-Log übernommen
  (`backfilled=True`). Diese Historie ist **nicht vollständig** und wird nur für
  „Geschlossen“ älterer Fenster genutzt – mit `*` gekennzeichnet.
- **`ItemStatusSnapshot`** – beim regulären Lauf wird der Bestand je Projekt und
  Status für den Stichtag gespeichert. Der erste Lauf eines Tages gewinnt, ein
  späterer manueller Lauf überschreibt den 07:30-Stand nicht. `--dry-run` und
  vergangene Stichtage schreiben keinen Snapshot.
- Tagesbestand im Verlauf: Snapshot → (für heute) Live-Stand → Rekonstruktion aus
  der lückenlosen Historie → sonst Lücke („–“, „keine Daten“). Die Historie gilt
  als lückenlos ab dem ersten nicht-backfilled `ItemStatusChange`, d. h. ab
  Deployment. Beim ersten Lauf ist der Verlauf daher nur für den aktuellen Tag
  gefüllt; der Report weist im Abschnitt „Hinweise“ darauf hin.

## Aufruf

```bash
python manage.py daily_status_report --dry-run                  # Text-Report ausgeben, nichts senden/speichern
python manage.py daily_status_report --dry-run --html-out /tmp/report.html   # HTML-Vorschau
python manage.py daily_status_report --date 2026-10-05 --dry-run # vergangener Stichtag
python manage.py daily_status_report --to ich@example.com       # abweichende Empfänger
python manage.py daily_status_report                            # Snapshot schreiben + senden
```

Bei vergangenen Stichtagen werden die Abschnitte 2, 4 und 5 aus der Historie
rekonstruiert (Projekt/Requester/Responsible = heutiger Stand). Reicht die
Historie nicht zurück, zeigt der Report den aktuellen Stand mit Hinweis.

## Konfiguration (`.env`)

| Variable | Standard | Bedeutung |
|---|---|---|
| `DAILY_REPORT_RECIPIENTS` | `christian.angermeier@isartec.de` | Empfänger, kommagetrennt |
| `DAILY_REPORT_SENDER` | Graph `default_mail_sender` | Absender (UPN) |
| `DAILY_REPORT_TIMEZONE` | `Europe/Berlin` | Zeitzone des Stichtags |
| `DAILY_REPORT_CUTOFF` | `07:30` | Uhrzeit des Stichtags |

Versand über Microsoft Graph (Konfiguration im Admin unter *Graph API
Configuration*) als MIME `multipart/alternative` (HTML + Text).

## Zeitplan (systemd-Timer)

Agira hat keinen In-Process-Scheduler; die Worker laufen per systemd/cron (siehe
`GITHUB_WORKERS.md`). Der Report wird analog über einen systemd-Timer geplant.
`OnCalendar` mit expliziter Zeitzone hält 07:30 Berlin über die Zeitumstellung
hinweg (systemd ≥ 235).

`/etc/systemd/system/agira-daily-report.service`

```ini
[Unit]
Description=Agira daily status report
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=oneshot
User=agira
WorkingDirectory=/opt/agira
EnvironmentFile=/opt/agira/.env
ExecStart=/opt/agira/venv/bin/python manage.py daily_status_report
```

`/etc/systemd/system/agira-daily-report.timer`

```ini
[Unit]
Description=Agira daily status report at 07:30 Europe/Berlin

[Timer]
OnCalendar=*-*-* 07:30:00 Europe/Berlin
Persistent=true

[Install]
WantedBy=timers.target
```

Pfade/User an die Installation anpassen, dann:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now agira-daily-report.timer
systemctl list-timers agira-daily-report.timer   # nächster Lauf
sudo systemctl start agira-daily-report.service  # Testlauf
journalctl -u agira-daily-report.service         # Ausgabe/Fehler
```

`Persistent=true` holt einen verpassten Lauf (Server aus) beim Start nach.

## Fehlerbehandlung

Fehler beim Erzeugen oder Versand werden geloggt (`logger.error`/`exception`,
damit auch an Sentry) und beenden das Command mit Exit-Code ≠ 0 – die Unit
steht dann in `systemctl --failed`. Der Snapshot wird vor dem Versand
geschrieben, ein fehlgeschlagener Versand verliert also keinen Verlaufspunkt;
ein manueller Neustart der Unit verschickt den Report erneut.
