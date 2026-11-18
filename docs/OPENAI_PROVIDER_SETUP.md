# OpenAI-Provider der Agent-Queue einrichten (Epic #1294)

Kurzdoku zum zweiten Provider „OpenAI Codex“ neben Claude Code. Die Regeln für
Git-Workflow, Epic-Modus und Review stehen in [`CLAUDE.md`](../CLAUDE.md) und
gelten für beide Provider unverändert; `AGENTS.md` (von Codex gelesen) legt der
Worker im Checkout als Symlink auf `CLAUDE.md` an und hält sie aus Git heraus.

## Voraussetzungen auf dem Worker-Host

- **Codex-CLI installiert** und im `PATH` (z. B. `npm i -g @openai/codex`), oder
  Pfad per `CODEX_CLI_BIN` (Default `codex`). Die Version ist nicht gepinnt, siehe
  „Offene Punkte“.
- `git` und `gh` wie für Claude (Commit, Push, Draft-PR laufen im Agent-Lauf).
- Ein OpenAI-API-Key (kein Abo-Login, siehe unten).

## API-Key

Auflösung (`resolve_openai_credential`):

1. persönlicher Key im Profil (verschlüsselt, write-only, nicht im Admin),
2. sonst `OPENAI_API_KEY` (Settings/Umgebung) als Host-Key,
3. sonst Fehler beim Einreihen – es gibt kein keyloses Fallback.

Mit `OPENAI_REQUIRE_USER_CREDENTIALS=true` ist nur der persönliche Key erlaubt.

## Settings

| Setting / Env | Bedeutung |
|---------------|-----------|
| `OPENAI_API_KEY` | Host-Key (Fallback) |
| `OPENAI_REQUIRE_USER_CREDENTIALS` | nur persönliche Keys zulassen (Default `false`) |
| `CODEX_CLI_BIN` | Pfad/Name der Codex-CLI (Default `codex`) |
| `CODEX_HOME_DIR` | isolierter `CODEX_HOME`; leer = Verzeichnis je Lauf. Verhindert, dass ein vorhandenes `~/.codex/auth.json` (ChatGPT-Login) den injizierten Key überschreibt |

## Provider-Wahl

- **Umsetzung:** `Item.implementation_provider` (Default `claude`) bzw. der
  Button „Umsetzung durch …“; die Wahl wird am Item gemerkt. Das Modell kommt aus
  den OpenAI-Modellen (`OpenAIQueueJobModel`, Default `gpt-6.2-sol`); ein Modell
  des anderen Providers wird durch den Default ersetzt.
- **Review:** `Item.review_provider`; leer = der **andere** Provider als bei der
  letzten sauberen Umsetzung (`provider_rule.effective_review_provider`). Details
  in [`CLAUDE_REVIEW_WORKFLOW.md`](CLAUDE_REVIEW_WORKFLOW.md).
- **Epic:** Der Epic-Knoten trägt den Provider; die Kette übernimmt ihn für alle
  Einträge (`create_sub_issue_job`). Gate, Merge und Stopp-Regeln sind
  providerunabhängig (siehe [`EPIC_BRANCH_WORKFLOW.md`](EPIC_BRANCH_WORKFLOW.md)).

## Offene Punkte und Einschränkungen (aus 1/7 bis 6/7)

- **Spike unverifiziert (1/7):** Die Messungen mit der echten Codex-CLI stehen
  aus ([`CODEX_CLI_SPIKE.md`](CODEX_CLI_SPIKE.md)). Event-Namen, Fehlertexte,
  Flags und die CLI-Version sind Annahmen; Stream-Parser und Fehlererkennung
  sind tolerant gebaut und nur über synthetische Streams getestet.
- **Sandbox (4/7):** Umsetzungsläufe nutzen
  `--dangerously-bypass-approvals-and-sandbox`, weil Commit, Push und `gh` im
  Lauf nötig sind; der Worker-Host ist die Isolationsgrenze. Review-Läufe
  laufen `read-only` (`-s read-only`, `approval_policy=never`).
- **Kosten ohne USD (4/7):** Codex meldet keine Kosten. Gespeichert werden
  Token-Zahlen (Summe über `turn.completed`) und Turns; `total_cost_usd` bleibt
  leer, es gibt bewusst keine Preistabelle.
- **Nur API-Key (3/7, 4/7):** Kein Abo/OAuth, daher kein Wechsel Abo → Key.
  Ein Limit (429) parkt den Job mit höchstens relativer Wartezeit;
  `insufficient_quota` (leeres Guthaben) ist ein Credential-/Billing-Fehler, kein
  Warten.
- **Classifier (3/7):** Der Modell-Classifier kennt nur Claude-Modelle; für
  `openai` gilt das Default-Codex-Modell.
- **Provider pro Epic (7/7):** Die Kette übernimmt den Provider des Epic-Knotens.
  Ein einzelner Sub-Issue-Lauf kann von Hand mit anderem Provider neu angestoßen
  werden und hängt sich wieder in die Kette; Gate und Merge ändern sich dadurch nicht.
- **Abnahme (7/7):** Die End-to-End-Abnahme „Umsetzung Claude + Review OpenAI und
  umgekehrt“ an je einem Test-Issue braucht Codex-CLI und Key und konnte im
  headless Lauf nicht ausgeführt werden. Sie ist von Hand durchzuführen
  (Checkliste unten); automatisiert sind Worker-/Orchestrierungs-Tests mit
  gemockter CLI abgedeckt.

## Abnahme-Checkliste (manuell)

1. Test-Issue A: Umsetzung durch Claude → Draft-PR, Status `Testing` nach Merge →
   Review (automatisch OpenAI) → Urteil und Bericht-Kommentar mit „Geurteilt von“.
2. Test-Issue B: Umsetzung durch OpenAI → Draft-PR → Review (automatisch Claude).
3. Epic mit zwei Sub-Issues: Kette läuft sequenziell, Merge in den Epic-Branch
   durch den Worker, Epic-PR als Draft.
