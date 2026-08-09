# Claude Code über Max-Abo (OAuth) statt API-Key betreiben

> **Ein-Konto-Fall.** Dieses Dokument beschreibt den Betrieb mit *einem*
> Credential auf dem Worker-Host. Im Team hat jeder sein eigenes Abo: dann
> liegen Token und API-Key im Benutzerprofil, der Modus wird je Issue gewählt
> und jeder Job läuft auf dem Credential seines Benutzers — siehe
> [`PER_USER_CLAUDE_AUTH.md`](PER_USER_CLAUDE_AUTH.md) (#1083). Die
> Host-Credentials hier sind dann nur noch Fallback.

Die Claude-Code-Läufe des Queue-Workers (`run_claude_worker`) können wahlweise
über das **Claude Max/Pro Abo** (OAuth) oder über einen **Anthropic API-Key**
laufen. Standard ist das Abo — so wird das bereits bezahlte Kontingent genutzt
und es entstehen keine variablen Pay-per-use-Kosten.

## Kurzfassung

| Ziel                              | Einstellung |
|-----------------------------------|-------------|
| Abo nutzen (Standard)             | `CLAUDE_AUTH_MODE=oauth` + OAuth-Login/Token auf dem Host |
| Pay-per-use API-Key               | `CLAUDE_AUTH_MODE=api_key` + `ANTHROPIC_API_KEY` |
| Kritischer Job darf bei Limit den API-Key nutzen | Job-Flag `allow_api_key_fallback=True` |

## 1. Einrichtung des OAuth-Tokens

Das Abo wird **durch die `claude`-CLI hindurch** genutzt (der Worker startet die
CLI als Subprozess). Der OAuth-Token darf nicht extrahiert und direkt gegen die
Anthropic-API verwendet werden — das verstößt gegen die ToS. Da Agira die CLI
ohnehin als Subprozess aufruft, ist der zulässige Weg gegeben.

Auf dem Worker-Host (Linux, ohne macOS-Keychain) einmalig anmelden:

```bash
# Variante A – interaktiv (Browser-OAuth):
claude login

# Variante B – für Automatisierung: erzeugt einen Token für die Umgebung
claude setup-token
```

Bei Variante B den ausgegebenen Token als Umgebungsvariable hinterlegen (analog
zu den übrigen Secrets, **nicht** ins Repo/Log):

```bash
CLAUDE_CODE_OAUTH_TOKEN=<token aus `claude setup-token`>
```

Ist `CLAUDE_CODE_OAUTH_TOKEN` leer, greift der Worker auf die von `claude login`
auf dem Host hinterlegten Credentials (`~/.claude`) zurück.

## 2. Umschalten des Auth-Modus

> Seit #1083 ist `CLAUDE_AUTH_MODE` nur noch der Host-Default für Jobs ohne
> eigene Angabe. Der Modus wird regulär **je Issue** gewählt
> (`Item.claude_auth_mode`, Default ABO) und beim Einreihen auf dem Job
> eingefroren.

`.env` (siehe `.env.example`):

```bash
# "oauth" (Standard) = Abo, "api_key" = Pay-per-use
CLAUDE_AUTH_MODE=oauth
CLAUDE_CODE_OAUTH_TOKEN=      # für Abo-Läufe
ANTHROPIC_API_KEY=           # für API-Key-Läufe und den Fallback
```

**Wichtig – prozess-lokaler Credential-Vorrang:** Sieht ein `claude`-Prozess
sowohl `ANTHROPIC_API_KEY` als auch einen OAuth-Login, nimmt er *still* den
API-Key. Der Worker baut das Child-Environment deshalb **pro Lauf** gezielt auf
(`_build_env`): Er entfernt zuerst beide Auth-Variablen aus dem geerbten
Environment und setzt dann genau die passende. So schlägt ein global
exportierter `ANTHROPIC_API_KEY` bei einem Abo-Lauf **nicht** durch.

## 3. Job-Flag „API-Key-Fallback erlaubt"

`ClaudeQueueJob.allow_api_key_fallback` (Default `False`) ist eine **statische
Job-Eigenschaft** — sie hängt nicht vom aktuellen Verbrauch ab und wird beim
Einreihen gesetzt:

```python
enqueue_item_for_claude(item, allow_api_key_fallback=True)
```

* **Flag aus (Default):** Bei erreichtem Abo-Limit **wartet** der Lauf bis zum
  Rollover (siehe unten). Kein Pay-per-use.
* **Flag an:** Bei erreichtem Abo-Limit wird derselbe Lauf sofort mit
  `ANTHROPIC_API_KEY` erneut ausgeführt und zu Ende gebracht. Das ist das
  „Ventil" für kritische Läufe, die nicht warten sollen.

Der Modus des jeweils letzten Versuchs steht in `ClaudeQueueJob.auth_mode`
(`oauth`/`api_key`) — ein Blick genügt, um zu sehen, ob ein Lauf Pay-per-use-
Kosten verursacht hat.

## 4. Limit-Handling (reaktiv)

Agira kennt oder zählt das Abo-Kontingent nicht. Es startet den Abo-Lauf, und
*falls* das Limit erreicht ist, meldet die CLI einen Rate-/Usage-Limit-Fehler.
Der Worker erkennt diesen (`_is_limit_error`, ausgewertet über `result`/`stderr`
des `--output-format`-Streams), unterscheidet ihn von echten Fehlern und von
Auth-Fehlern und reagiert:

1. **Flag gesetzt →** Fallback auf API-Key (Job läuft zu Ende).
2. **Sonst →** Job wechselt in den Status **`waiting_limit`**. Der (sofern
   vorhanden) aus der CLI geparste Reset-Zeitpunkt landet in `limit_reset_at`;
   fehlt er, gilt ein Default-Backoff. Der Worker **claimt den Job automatisch
   erneut**, sobald `limit_reset_at` erreicht ist — ohne stillen Abbruch.

Der Wartezustand ist überall erkennbar: eigener Status `waiting_limit`
(„Waiting for quota", eigenes Badge), `limit_reset_at` und ein `progress_text`
„Abo-Kontingent erreicht – wartet auf Rollover …". Das Item bleibt derweil in
`Working` (es wird weiter bearbeitet, nur mit Pause), wird also **nicht** wie bei
einem echten Fehler nach `Backlog` freigegeben.

### Fehlerpfad: abgelaufener/ungültiger Token

Ein abgelaufener oder ungültiger Token/Key ist **kein** Limit — Warten hilft
nicht. Der Worker erkennt Auth-Fehler (`_is_auth_error`) und setzt den Job auf
`failed` mit einer verständlichen Meldung (Hinweis auf `claude setup-token`
bzw. das Prüfen von `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_API_KEY`), sichtbar in
`error_text` und im PR-Body. Kein stiller Abbruch.

## 5. Token-Lebenszyklus auf dem Zielserver (Spike)

**Status: auf dem konkreten Zielserver zu evaluieren.** Der Linux-Host hat keine
macOS-Keychain; die Zuverlässigkeit des Hintergrund-Token-Refresh der CLI muss
dort gemessen werden, bevor die Dauerbetriebsvariante festgelegt wird.

Vorgehen:

1. Auf dem Zielserver `claude setup-token` (oder `claude login`) ausführen und
   `CLAUDE_AUTH_MODE=oauth` setzen.
2. Über mehrere Tage Abo-Läufe fahren und beobachten, ob der Token selbständig
   erneuert wird oder ob Auth-Fehler auftreten (im Item/Log als `failed` mit
   Auth-Meldung sichtbar — siehe Fehlerpfad oben).
3. Ergebnis hier dokumentieren und die Betriebsvariante wählen:
   * **Auto-Refresh vertrauen** — wenn der Refresh über die Beobachtungsdauer
     zuverlässig lief.
   * **Periodisch neu erzeugen + Monitoring** — `claude setup-token` per Cron
     erneuern und Auth-Fehler alarmieren, falls der Refresh nicht trägt.

> Ergebnis der Evaluierung (Datum / Beobachtung / gewählte Variante):
>
> _— hier nach Durchführung des Spikes auf dem Zielserver eintragen —_

Bis zur Durchführung ist die sichere Annahme: Auth-Fehler werden erkannt und als
`failed` gemeldet, sodass ein nicht refreshter Token nicht unbemerkt bleibt.
