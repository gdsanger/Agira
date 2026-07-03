# GitHub PR Webhook — Einrichtung

## 1. Zweck und Abgrenzung

Wenn ein Pull Request auf GitHub gemerged wird, soll Agira automatisch informiert werden, damit:

- das zugehörige Item den Status **`Working` → `Testing`** wechselt, und
- der aktuelle PR-Status (offen, merged, geschlossen) sichtbar in Agira gepflegt wird (Job und Activity-Log).

Dazu wird ein **GitHub Webhook** auf Repository-Ebene eingerichtet, der bei relevanten `pull_request`-Events direkt einen HTTP-POST-Request an einen öffentlich erreichbaren Agira-Endpoint sendet.

**Es wird keine GitHub Action benötigt.** GitHub liefert das Event nativ per Webhook aus, sobald die Payload-URL im Repository konfiguriert ist — es ist kein Workflow-File (`.github/workflows/*.yml`), kein Runner und keine zusätzliche Pipeline notwendig. Der Webhook sendet direkt von GitHub an Agira, weil Agira öffentlich per HTTPS erreichbar ist und den Request selbst authentifizieren und verarbeiten kann; ein Umweg über eine Action würde nur zusätzliche Latenz und Komplexität einführen, ohne einen Vorteil zu bringen.

Implementierung in Agira: `core/views_webhooks.py` (`github_pull_request_webhook`), Signaturprüfung in `core/services/github/webhook.py`, fachliche Verarbeitung in `core/services/github/service.py` (`GitHubService.apply_pr_webhook_event`).

## 2. Voraussetzungen

- Agira ist öffentlich per HTTPS erreichbar (siehe `APP_BASE_URL` in den Agira-Settings, z. B. `https://agira.angermeier.net`).
- Der Endpoint `/webhooks/github/pull-request/` ist in Agira bereits vorhanden und für GitHub-PR-Events vorgesehen (`core/urls.py`, Route `github-pull-request-webhook`).
- Ein gemeinsames Secret existiert, das **identisch** in GitHub (Webhook-Konfiguration) und in Agira (`GitHubConfiguration.webhook_secret`) hinterlegt wird.
- Der Webhook wird **nur in den relevanten Repositories** eingerichtet, nicht org-weit.
- Zugriff auf die GitHub-Repository-Settings (Admin-Rechte auf dem Repository) sowie auf das Agira-Admin-Backend.

## 3. Einrichtung in GitHub

1. Im Ziel-Repository navigieren zu **Settings → Webhooks → Add webhook**.
2. **Payload URL**: `https://<agira-host>/webhooks/github/pull-request/` (z. B. `https://agira.angermeier.net/webhooks/github/pull-request/`).
3. **Content type**: `application/json`.
4. **Secret**: das gemeinsame Webhook-Secret eintragen (siehe Abschnitt 4) — dasselbe, das in Agira unter `GitHubConfiguration.webhook_secret` hinterlegt ist.
5. **Which events would you like to trigger this webhook?**: "Let me select individual events" auswählen und mindestens **`Pull requests`** aktivieren. Weitere Events sind nicht erforderlich, da nicht-`pull_request`-Events von Agira ohne Verarbeitung bestätigt werden.
6. **Active** angehakt lassen und mit **Add webhook** speichern.
7. Empfehlung: Den Webhook **pro Repository** einrichten, nicht als Organization-Webhook — so bleibt die Zuordnung Repository ↔ Secret ↔ Agira-Projekt eindeutig und ein kompromittiertes Secret betrifft nur ein Repository statt aller.

## 4. Einrichtung in Agira

- **Endpoint-URL**: `POST /webhooks/github/pull-request/` (CSRF-exempt, da von GitHub ohne Session aufgerufen; siehe `core/views_webhooks.py`).
- **Secret**: dasselbe Secret wie in GitHub wird in Agira unter **Admin → GitHub Configuration → Legacy GitHub App → Webhook Secret** (`GitHubConfiguration.webhook_secret`, verschlüsselt gespeichert) hinterlegt.
- **Signaturprüfung**: Jeder Request muss den Header `X-Hub-Signature-256` mit einer gültigen HMAC-SHA256-Signatur über den rohen Request-Body (berechnet mit dem Secret) enthalten. Die Prüfung erfolgt in `verify_signature()` (`core/services/github/webhook.py`).
- **Verhalten bei ungültiger Signatur**: Fehlt der Header, ist er falsch formatiert oder stimmt die Signatur nicht, wird der Request mit `403 Forbidden` verworfen und **nicht** verarbeitet; ein Warning wird geloggt.
- **Idempotenz**: GitHub kann dasselbe Event mehrfach zustellen (Retries bei Timeouts, manuelle Redelivery). Die Verarbeitung in `apply_pr_webhook_event()` ist idempotent: Der Mapping-Zustand wird immer auf den aktuellen Stand aus dem Payload gesetzt (kein Aufsummieren), und der Statuswechsel `Working → Testing` erfolgt nur, wenn das Item aktuell tatsächlich noch in `Working` ist — eine erneute Zustellung desselben "merged"-Events verändert den Status danach nicht mehr.

## 5. Relevante Event-Verarbeitung

- Relevant ist ausschließlich das GitHub-Event **`pull_request`** (Header `X-Github-Event: pull_request`). Andere Events werden mit `{"ignored": true, "event": "<name>"}` bestätigt, damit GitHub sie nicht erneut zustellt, aber nicht weiterverarbeitet.
- Beim Payload-Feld `action` interessiert insbesondere `closed` mit `pull_request.merged = true` (PR wurde gemerged, nicht nur geschlossen).
- Zuordnung des Events zu einem Agira-Item erfolgt über `ExternalIssueMapping`, gesucht per `github_id` des PRs (nicht Nummer/Branch/Titel) und `kind = PR` (siehe #836 als Grundlage für diese Zuordnung). Existiert kein passendes Mapping, wird das Event ignoriert und geloggt.
- Ist ein Mapping gefunden und wurde der PR gemerged, während das zugehörige Item im Status `Working` ist, wechselt Agira den Item-Status auf `Testing` und protokolliert den Wechsel in der Activity.
- Der aktuelle PR-Status (`open`/`closed`/`merged`) wird unabhängig vom Statuswechsel immer auf dem `ExternalIssueMapping` (Feld `state`) sowie — falls vorhanden — auf dem zugehörigen `ClaudeQueueJob` (Feld `pr_state`) aktualisiert, damit der PR-Status in Agira sichtbar bleibt.

## 6. Test / Verifikation

1. **Test-Delivery aus GitHub**: Im Repository unter **Settings → Webhooks → (Webhook auswählen) → Recent Deliveries** eine bestehende Zustellung erneut senden ("Redeliver") oder einen echten Test-PR öffnen/mergen.
2. **In GitHub prüfen**: Unter "Recent Deliveries" sollte die Zustellung einen `200`-Response von Agira zeigen (Response-Body z. B. `{"matched": true, ...}` oder `{"ignored": true, ...}`).
3. **In Agira prüfen**: In den Server-Logs sollte kein "Rejected GitHub webhook delivery"-Eintrag erscheinen; bei erfolgreicher Zuordnung ist ein Activity-Eintrag `github.pr_state_changed` (und ggf. der Statuswechsel) am betroffenen Item sichtbar.
4. **Statuswechsel prüfen**: Nach dem Merge eines PRs, dessen zugehöriges Item vorher auf `Working` stand, muss das Item danach auf `Testing` stehen.
5. **Negativtest Signatur**: Einen Request mit falschem oder fehlendem `X-Hub-Signature-256`-Header senden (z. B. via `curl` mit falschem Secret) und prüfen, dass Agira mit `403 Forbidden` antwortet und keine Item-Änderung erfolgt.

## 7. Troubleshooting

| Symptom | Mögliche Ursache |
|---|---|
| GitHub zeigt Zustellfehler / Timeout | Falsche Payload-URL, oder Agira-Endpoint nicht öffentlich per HTTPS erreichbar (Firewall, DNS, TLS-Zertifikat) |
| Agira antwortet mit `403 Forbidden` | Secret in GitHub und Agira ist nicht identisch, oder `X-Hub-Signature-256`-Header fehlt/ist falsch formatiert |
| Zustellung kommt an, aber nichts passiert (`ignored`) | Falsches Event ausgewählt — es muss mindestens `Pull requests` aktiviert sein |
| Zustellung erfolgreich, aber Item wechselt nicht auf `Testing` | Item stand zum Merge-Zeitpunkt nicht in `Working`, oder es existiert kein passendes `ExternalIssueMapping` (`kind=PR`, passende `github_id`) für den PR |
| Kein `ExternalIssueMapping` vorhanden | Mapping wird beim PR-Bootstrap in Agira angelegt (siehe #836) — prüfen, ob der PR über Agira erstellt bzw. verknüpft wurde, bevor der Webhook Events dafür verarbeiten kann |
| Wiederholte Zustellungen erzeugen wiederholte Statuswechsel | Sollte laut Implementierung nicht auftreten (Verarbeitung ist idempotent) — falls doch beobachtet, als Bug melden |
