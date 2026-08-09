# Per-User-Auth: eigenes Claude-Konto je Benutzer (#1083)

[`docs/CLAUDE_CODE_OAUTH.md`](CLAUDE_CODE_OAUTH.md) beschreibt den Ein-Konto-Fall
(#1078): **ein** Token auf dem Worker-Host, alle Jobs laufen darüber. Im
Team-Einsatz hat aber jeder sein eigenes Claude-Abo. Dieses Dokument beschreibt
die Verallgemeinerung: **jeder Benutzer hinterlegt seine eigenen Credentials,
jedes Issue wählt den Modus, jeder Job bekommt genau ein Credential.**

## Kurzfassung

| Frage                                   | Antwort |
|-----------------------------------------|---------|
| Wo liegen die Credentials?              | Im Benutzerprofil („User Settings“), verschlüsselt (`EncryptedCharField`) |
| Welche Credentials?                     | `claude_oauth_token` (Abo) und `claude_api_key` (Pay-per-use) |
| Wer entscheidet ABO vs. API?            | Das Issue: `Item.claude_auth_mode`, Default `ABO` |
| Wessen Credential nutzt ein Job?        | `ClaudeQueueJob.auth_user` — Auslöser, sonst Responsible → Assigned To → Requester |
| Wie kommt es in den Prozess?            | Child-Env je Job (`CLAUDE_CODE_OAUTH_TOKEN` bzw. `ANTHROPIC_API_KEY`) |
| Was passiert ohne Credential?           | Klarer Fehler (kein stiller Moduswechsel) |

## 1. Credentials im Benutzerprofil

Unter **User Settings** hinterlegt jeder Benutzer selbst:

* **Claude OAuth-Token (ABO)** — erzeugt mit `claude setup-token`. Damit laufen
  Jobs über das bereits bezahlte Max/Pro-Kontingent dieses Benutzers.
* **Anthropic API-Key (API)** — Pay-per-use, für Issues, die bewusst auf `API`
  gestellt werden (typisch: Abo-Kontingent voll).

Beide Felder sind **write-only**: gespeichert wird verschlüsselt, angezeigt wird
nur „hinterlegt / nicht hinterlegt“. Ein leeres Formularfeld bedeutet
„unverändert lassen“, gelöscht wird über die explizite Checkbox. Die Felder sind
bewusst **nicht** im Django-Admin — ein persönliches Credential setzt sein
Besitzer, kein Administrator.

## 2. Auth-Modus je Issue

`Item.claude_auth_mode` (`ABO` = `oauth`, Default / `API` = `api_key`) ist im
Item-Formular und inline im Item-Detail umschaltbar. Beim Einreihen friert der
Job die Wahl ein (`ClaudeQueueJob.requested_auth_mode`) — eine spätere Änderung
am Issue schreibt einen laufenden oder fertigen Job nicht um.

Das Umschalten `ABO → API` ist **manuell**. Ein automatischer Fallback bei
erreichtem Limit existiert nur als bewusst gesetztes Job-Flag
(`allow_api_key_fallback`, siehe #1078) — dann wird der API-Key **desselben
Benutzers** verwendet.

## 3. Wessen Credential? (`auth_user`)

Feste Reihenfolge, unabhängig davon, wer gerade ein Credential hinterlegt hat:

1. **Auslöser** des Laufs (wer „An Claude übergeben“ gedrückt hat)
2. `item.responsible`
3. `item.assigned_to`
4. `item.requester`

Der Auslöser steht vorn, weil er den Lauf startet und den Modus je Issue wählt —
es ist seine Quota, die ausgegeben wird. Die Reihenfolge hängt bewusst **nicht**
davon ab, wer ein Credential hinterlegt hat: sonst würde sich die
Kostenzuordnung verschieben, sobald jemand sein Profil ändert.

Das Ergebnis wird beim Einreihen einmal aufgelöst und als
`ClaudeQueueJob.auth_user` gespeichert. Ein späterer Wechsel des Responsible
kann einen abgeschlossenen Lauf damit nicht rückwirkend umbuchen.

## 4. Credential-Injection pro Job

Der Worker baut für **jeden** Lauf ein frisches Child-Environment
(`_build_env`): erst werden **beide** Auth-Variablen aus dem geerbten
Environment entfernt, dann genau die passende gesetzt.

```
ABO  → CLAUDE_CODE_OAUTH_TOKEN=<Token des auth_user>   (kein ANTHROPIC_API_KEY!)
API  → ANTHROPIC_API_KEY=<Key des auth_user>           (kein OAuth-Token)
```

Zwei Gründe für Env statt CLI-Flag: die Claude-CLI kennt für Auth ohnehin nur
Umgebungsvariablen (`--model` ist das einzige relevante Flag), und `argv` ist
über `ps` für jeden Prozess sichtbar, das Environment nicht.

**Harte Regel (aus #1078, jetzt pro Benutzer):** Im ABO-Lauf darf
`ANTHROPIC_API_KEY` nicht im Child-Env stehen. Der Credential-Vorrang der CLI
ist prozess-lokal — sieht sie einen API-Key, nimmt sie ihn *still*, und der
vermeintlich kostenlose Abo-Lauf wird abgerechnet.

## 5. Fehlendes Credential

`CLAUDE_REQUIRE_USER_CREDENTIALS` (Default `false`) steuert, was passiert, wenn
der zuständige Benutzer für den gewählten Modus nichts hinterlegt hat:

* **`false` (Default):** Rückfall auf das Host-Credential
  (`CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` bzw. `claude login`), also
  exakt das Verhalten aus #1078. Der Lauf wird als `shared` markiert
  (`ClaudeQueueJob.auth_credential_source`) und zählt damit **nicht** als
  persönliche Nutzung — die Kostenzuordnung bleibt ehrlich.
* **`true` (Team-Betrieb):** harter Fehler mit Klartext („Kein persönlicher
  Claude-OAuth-Token für … hinterlegt … unter ‚User Settings‘ hinterlegen oder
  das Issue auf ‚API‘ umstellen“). Der Fehler kommt schon beim Einreihen
  (HTTP 400 an der Schaltfläche) und im Worker **vor** Checkout und Draft-PR.

Unabhängig vom Schalter gilt: ein `API`-Lauf ohne jeden Key schlägt fehl. Ein
stiller Wechsel auf den anderen Modus findet nie statt — genau der wäre der
teure bzw. unerwartete Ausgang.

## 6. Kosten: tatsächlich vs. theoretisch

Jeder Job trägt `auth_user` + `auth_mode` (Modus des letzten Versuchs) +
`auth_credential_source`. Daraus rechnet die System-Analytics je Benutzer:

* **Tatsächliche Kosten** — Summe `total_cost_usd` der `api_key`-Läufe: wirklich
  pay-per-use abgerechnet.
* **Theoretische Kosten** — Summe `total_cost_usd` der `oauth`-Läufe: über das
  bereits bezahlte Abo gelaufen, also das, was pay-per-use gekostet *hätte* —
  das Eingesparte.

Beides bleibt Claudes eigener Schätzwert je Job (`total_cost_usd`, siehe #997),
keine Rechnungsdaten und keine Neuberechnung.

## 7. Konfiguration

```bash
# Host-weite Fallback-Credentials (#1078) — greifen nur, wenn der Benutzer
# selbst keins hinterlegt hat und der Fallback erlaubt ist.
CLAUDE_CODE_OAUTH_TOKEN=
ANTHROPIC_API_KEY=
# Team-Betrieb: nur persönliche Credentials zulassen.
CLAUDE_REQUIRE_USER_CREDENTIALS=false
```

`CLAUDE_AUTH_MODE` bleibt nur noch der Host-Default für Jobs **ohne** eigene
Modus-Angabe (Alt-Jobs von vor #1083); die Wahl je Issue hat Vorrang.
