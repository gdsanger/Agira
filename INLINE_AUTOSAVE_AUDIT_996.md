# Audit – Inline-Editing / Autosave im Item-DetailView (Issue #996, Teil A)

Bestandsaufnahme vor der Konsolidierung auf eine generische HTMX-Save-Routine.
Stand: Branch `fix/inline-autosave-fur-alle-geeigneten-item-felder-vi-996`.

## 1. Ergebnis in einem Satz

Die Vermutung stimmt: Es gibt **pro Feld eine eigene View + eigene URL** (Wildwuchs).
Aktuell speichern nur **3 Felder** autosave-on-change via HTMX (`intern`, `parent`,
`solution_release`); `responsible` hat zwei weitere dedizierte JSON-Endpoints mit
E-Mail-Nebenwirkung. `organisation`, `requester`, `assigned_to`, `title`,
`short_description`, `type` sind im DetailView **nur Anzeige** und nur über das
separate Edit-Formular (`item_update`) änderbar.

## 2. Felder, die HEUTE inline per HTMX speichern

Muster identisch: `<select|input hx-post=… hx-trigger="change" hx-swap="none" hx-indicator="#…">`,
Server gibt `HttpResponse(status=200/400)` (leerer Body) zurück, JS-Indikator „Gespeichert".

| Feld | URL-Name | View (`core/views.py`) | Template (`item_detail.html`) | Besonderheiten |
|------|----------|------------------------|-------------------------------|----------------|
| `intern` (bool) | `item-update-intern` | `item_update_intern` (Z. 1171) | Z. 635–655 | Checkbox → `'on'/'true'`; Activity `item.field_changed` |
| `parent` (FK Item) | `item-update-parent` | `item_update_parent` (Z. 1123) | Z. 746–776 | Validierung: kein Closed-Item, nicht self; Activity `item.field_changed` |
| `solution_release` (FK) | `item-update-release` | `item_update_release` (Z. 1086) | Z. 780–814 | FK-Auflösung Release; Activity `item.field_changed` |

## 3. `responsible` – Sonderfall (zwei dedizierte JSON-Endpoints, kein reines Autosave)

| Aktion | URL-Name | View | UI | Besonderheiten |
|--------|----------|------|----|----------------|
| „Take over" | `item-take-over-responsible` | `item_take_over_responsible` (Z. 1204) | Dropdown, `takeOverResponsible()` JS, Z. 1390 | nur `role == AGENT`; **E-Mail** `_send_responsible_notification`; `no_change`-Kurzschluss; Activity `item.responsible_changed`; JSON |
| „Assign" (Modal) | `item-assign-responsible` | `item_assign_responsible` (Z. 1306) | Modal `#assignResponsibleModal`, Z. 2229 | Ziel muss `role == AGENT`; **E-Mail**; Activity `item.responsible_changed`; JSON; Seiten-Reload |

Wichtig: Beide senden **E-Mail-Benachrichtigungen** und liefern JSON + eigene UI-Texte,
nicht das leere 200/400-Muster der Autosave-Felder. Reine Konsolidierung würde diese
Nebenwirkung/Contract brechen.

## 4. Felder, die im DetailView NUR angezeigt werden (Ziel: inline editierbar machen)

| Feld | Template-Stelle | Aktuell | Anmerkung |
|------|-----------------|---------|-----------|
| `organisation` (FK) | Z. 680–683 | Text | Ziel: Select/Autocomplete |
| `requester` (FK User) | Z. 684–701 | Text + „Quick Create User"-Modal | **Nebenwirkung im Model** (s. §6) |
| `assigned_to` (FK User) | Z. 706–709 | Text | Ziel: Select |
| `responsible` (FK User) | Z. 702–705 | Text (+ Aktionen §3) | Sonderfall E-Mail/Agent |
| `type` (FK ItemType) | Z. 739–742 | Text | evtl. editierbar |
| `title` (Text) | Header Z. 136 | `<h3>` read-only | Header-Umbau #995 beachten |
| `short_description` | Description-Tab Z. 591 | Text | evtl. editierbar |
| `project` | Z. 736–738 | Text (+ Move-Modal) | **nicht** trivial (eigener Move-Flow) |

## 5. Bewusste Ausnahmen (kein generisches Autosave)

- **`status`** – workflow-gesteuert über `ItemWorkflowGuard().transition()` in
  `item_change_status` (Z. 3587) + Mail-Trigger + Apply-Button/`handleStatusChange()`.
  Bleibt unverändert.
- **`description`** – expliziter Editor/Toast-Editor-Save (`saveActiveDetailTab`), kein
  Change-Autosave. Bleibt unverändert.
- Das große Edit-Formular **`item_update`** (Z. 4856, `items/<id>/update/`, JSON) bleibt
  als Vollformular bestehen (setzt viele Felder gleichzeitig, Follower, Node-Breadcrumb,
  Mail-Trigger). Es ist **kein** Ziel der Konsolidierung, dient aber als Referenz für die
  Feld-/FK-Logik.

## 6. Business-Regeln, die die generische Routine bewahren MUSS

Diese liegen teils im **Model** (`core/models.py`), greifen also unabhängig vom Endpoint,
teils nur in Views:

1. **Requester → Organisation Auto-Update** (`Item.save()`, Z. 770–786): Ändert sich der
   Requester, wird `organisation` automatisch auf dessen Primär-Organisation gesetzt.
   → Getestet in `test_item_requester_organisation.py`. Muss beim Inline-Save erhalten bleiben.
2. **Requester-Mitgliedschaft** (`Item.clean()`, Z. 678–680): Requester muss Mitglied der
   gewählten Organisation sein. *Aktuell nur in `clean()`, nicht bei `save()` erzwungen* –
   bestehende Autosave-Endpoints rufen `full_clean()` nicht auf.
3. **Responsible = Agent** (`Item.clean()` Z. 683 + View-Checks): `responsible` muss Rolle
   `AGENT` haben.
4. **Parent-Validierung**: kein Closed-Item, nicht self (heute in `item_update_parent`).
5. **E-Mail bei Responsible-Wechsel** (`_send_responsible_notification`).
6. **Activity-Logging**: jede Änderung erzeugt heute einen Activity-Eintrag
   (`ActivityService().log(verb=…, target=item, actor=…, summary='… from X to Y')`).
   Signatur: `log(verb, target=None, actor=None, summary=None)` – **kein** strukturiertes
   old/new-Feld, nur Freitext-`summary`.

## 7. Berechtigungen (Ist-Zustand)

Es gibt **kein** feingranulares Item-Permission-System. Alle Endpoints nutzen
`@login_required`. Feldspezifische Checks: `responsible` erfordert `AGENT`-Rolle
(Take-over-Aktion nur durch Agent selbst). Rollen: `User, Agent, Approver, ISB,
Management, Info, Development` (`UserRole`). Für die generische Routine bedeutet
„Permission prüfen" v. a.: Login + feldspezifische Regeln (Agent-Rolle), keine bestehende
`can_edit_item()`-Helper vorhanden.

## 8. Konsolidierungs-Vorschlag (Teil B/C)

**Teil B – eine generische View** `item_update_field(request, item_id)`
(`items/<id>/field/`), die:
- `field` + Wert aus POST liest,
- gegen eine **Whitelist** prüft: `{title, short_description, intern, type, organisation,
  requester, assigned_to, parent, solution_release}` (bei Bedarf `responsible`, s. u.);
  `status`/`description` sind ausgeschlossen,
- pro Feld Typ/FK-Auflösung + Validierung anwendet (Registry: Feld → Handler),
- speichert (Model-`save()` erhält Requester→Org-Regel automatisch),
- Activity `item.field_changed` mit alt→neu loggt,
- ein **kleines HTML-Fragment** mit Erfolg/Fehler-Status am Feld zurückgibt,
- danach `item_update_intern/parent/release` ersetzt und entfernt.

**`responsible`**: Empfehlung – als Feld in die Whitelist mit **Post-Save-Hook**
(E-Mail + Agent-Validierung) aufnehmen; die dedizierten Take-over-/Assign-Modal-Aktionen
können als Komfort-Aktionen bleiben oder ebenfalls über die generische Route posten. Muss
mit User geklärt werden (E-Mail-Nebenwirkung + Test-Contract `test_item_responsible.py`).

**Teil C – einheitliches Inline-Pattern**: gemeinsames Template-Include/Partial pro
Feldtyp (Text, Select/FK, Checkbox, Datum) mit einheitlichem „Gespeichert"/​Fehler-Feedback;
`organisation`/`requester`/`assigned_to` als Inline-Selects; konsistent mit #990/#991/#995.

## 9. Scope-Einschätzung

Mittel–groß, aber gut abgrenzbar. Teil B (generische View + Migration der 3 Autosave-Felder
+ Whitelist + Tests) ist in diesem PR gut machbar. Teil C (neue Inline-Felder org/requester/
assigned_to + einheitliches Feedback) ist der größere UI-Anteil. `responsible` (E-Mail) und
`title` im #995-Header sind die Haupt-Risiken. Empfehlung zur Klärung siehe Chat.
