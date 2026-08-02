"""
Generic inline field-update service for Items (Issue #996).

Replaces the per-field HTMX save views (item_update_intern / item_update_parent /
item_update_release) and adds inline editing for further fields with a single,
field-agnostic routine:

- A server-side **whitelist** (`FIELD_SPECS`) — only explicitly listed fields may be
  saved this way. ``status`` and ``description`` are intentionally excluded (status is
  workflow-driven, description has an explicit editor).
- Per-field type/validation/FK-resolution rules.
- Activity logging (old -> new) via the existing ``ActivityService``.

Model-level side effects are preserved because the resolvers set attributes and the
caller calls ``item.save()``: e.g. changing ``requester`` auto-updates ``organisation``
to the requester's primary organisation (``Item.save()``).

The service is deliberate about NOT performing view-layer side effects (e.g. sending the
responsible-changed e-mail). It returns a :class:`FieldUpdateResult` describing what
changed so the view can trigger those side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import Any, Callable, Optional

from django.core.exceptions import ValidationError
from django.db.models import Model

from core.models import (
    Item,
    ItemStatus,
    ItemType,
    Organisation,
    Release,
    User,
    UserRole,
)
from core.services.activity import ActivityService


class FieldUpdateError(Exception):
    """Raised when an inline field update is rejected (not whitelisted, invalid value,
    or a permission/validation problem). The message is safe to show at the field."""


def _default_display(value: Any) -> str:
    return str(value) if value is not None else "None"


@dataclass
class FieldSpec:
    """Describes how one whitelisted item field is validated, resolved and logged."""

    attr: str
    kind: str  # 'text' | 'bool' | 'fk'
    # resolver(item, raw_value) -> resolved value to assign to ``item.<attr>``.
    # May raise FieldUpdateError / ValidationError. Must NOT mutate the item itself.
    resolve: Callable[[Item, str], Any]
    # display(value) -> human readable string for the activity log.
    display: Callable[[Any], str] = _default_display
    verb: str = "item.field_changed"
    label: Optional[str] = None  # human label used in the activity summary


@dataclass
class FieldUpdateResult:
    field: str
    changed: bool
    old_value: Any
    new_value: Any
    old_display: str
    new_display: str
    activity: Any = None
    extra: dict = dataclass_field(default_factory=dict)


# ---------------------------------------------------------------------------
# Resolvers / helpers
# ---------------------------------------------------------------------------

_TRUE_VALUES = {"true", "on", "1", "yes"}


def _resolve_bool(_item: Item, raw: str) -> bool:
    return str(raw).strip().lower() in _TRUE_VALUES


def _resolve_required_text(_item: Item, raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise FieldUpdateError("Dieses Feld darf nicht leer sein.")
    return value


def _resolve_optional_text(_item: Item, raw: str) -> str:
    return (raw or "").strip()


def _resolve_fk(model: type[Model], raw: str, *, nullable: bool, label: str):
    """Resolve a FK id to an instance. Empty string -> None (if nullable)."""
    raw = (raw or "").strip()
    if not raw:
        if nullable:
            return None
        raise FieldUpdateError(f"{label} ist erforderlich.")
    try:
        return model.objects.get(pk=raw)
    except (model.DoesNotExist, ValueError, TypeError):
        raise FieldUpdateError(f"Ausgewählte(r) {label} existiert nicht.")


def _resolve_type(_item: Item, raw: str) -> ItemType:
    return _resolve_fk(ItemType, raw, nullable=False, label="Typ")


def _resolve_organisation(_item: Item, raw: str) -> Optional[Organisation]:
    return _resolve_fk(Organisation, raw, nullable=True, label="Organisation")


def _resolve_user(_item: Item, raw: str, *, label: str) -> Optional[User]:
    return _resolve_fk(User, raw, nullable=True, label=label)


def _resolve_requester(item: Item, raw: str) -> Optional[User]:
    return _resolve_user(item, raw, label="Requester")


def _resolve_assigned_to(item: Item, raw: str) -> Optional[User]:
    return _resolve_user(item, raw, label="Assigned To")


def _resolve_responsible(item: Item, raw: str) -> Optional[User]:
    user = _resolve_user(item, raw, label="Responsible")
    if user is not None and user.role != UserRole.AGENT:
        raise FieldUpdateError('Verantwortliche(r) muss die Rolle "Agent" haben.')
    return user


def _resolve_parent(item: Item, raw: str) -> Optional[Item]:
    parent = _resolve_fk(Item, raw, nullable=True, label="Parent Item")
    if parent is None:
        return None
    if parent.id == item.id:
        raise FieldUpdateError("Ein Item kann nicht sein eigenes Parent sein.")
    if parent.status == ItemStatus.CLOSED:
        raise FieldUpdateError("Ein geschlossenes Item kann nicht als Parent gesetzt werden.")
    return parent


def _resolve_release(_item: Item, raw: str) -> Optional[Release]:
    return _resolve_fk(Release, raw, nullable=True, label="Release")


def _user_display(user: Optional[User]) -> str:
    return user.name if user else "None"


# ---------------------------------------------------------------------------
# Whitelist
# ---------------------------------------------------------------------------

FIELD_SPECS: dict[str, FieldSpec] = {
    "title": FieldSpec("title", "text", _resolve_required_text, label="Titel"),
    "short_description": FieldSpec(
        "short_description", "text", _resolve_optional_text, label="Kurzbeschreibung"
    ),
    "intern": FieldSpec(
        "intern", "bool", _resolve_bool, display=lambda v: str(bool(v)), label="Intern"
    ),
    "type": FieldSpec(
        "type", "fk", _resolve_type, display=lambda v: v.name if v else "None", label="Typ"
    ),
    "organisation": FieldSpec(
        "organisation", "fk", _resolve_organisation,
        display=lambda v: v.name if v else "None", label="Organisation",
    ),
    "requester": FieldSpec(
        "requester", "fk", _resolve_requester, display=_user_display, label="Requester"
    ),
    "assigned_to": FieldSpec(
        "assigned_to", "fk", _resolve_assigned_to, display=_user_display, label="Assigned To"
    ),
    "responsible": FieldSpec(
        "responsible", "fk", _resolve_responsible, display=_user_display,
        verb="item.responsible_changed", label="Responsible",
    ),
    "parent": FieldSpec(
        "parent", "fk", _resolve_parent,
        display=lambda v: v.title if v else "None", label="Parent Item",
    ),
    "solution_release": FieldSpec(
        "solution_release", "fk", _resolve_release,
        display=lambda v: v.version if v else "None", label="Release",
    ),
}

# Explicitly excluded (documented for clarity / defense in depth).
EXCLUDED_FIELDS = frozenset({"status", "description"})


def is_editable_field(field_name: str) -> bool:
    return field_name in FIELD_SPECS


def apply_field_update(item: Item, field_name: str, raw_value: str, actor=None) -> FieldUpdateResult:
    """Validate and persist a single whitelisted field change on ``item``.

    Raises :class:`FieldUpdateError` for a non-whitelisted field or an invalid value.
    Django ``ValidationError`` raised by resolvers is re-wrapped into ``FieldUpdateError``.
    On success the item is saved and an activity entry is logged. The caller is
    responsible for any view-layer side effects (e.g. e-mail) using the returned result.
    """
    spec = FIELD_SPECS.get(field_name)
    if spec is None:
        raise FieldUpdateError(f'Feld "{field_name}" kann nicht inline gespeichert werden.')

    old_value = getattr(item, spec.attr)
    old_display = spec.display(old_value)

    try:
        new_value = spec.resolve(item, raw_value)
    except ValidationError as exc:
        # Normalise Django validation errors to a single readable message.
        messages = exc.messages if hasattr(exc, "messages") else [str(exc)]
        raise FieldUpdateError(" ".join(messages))

    changed = old_value != new_value
    setattr(item, spec.attr, new_value)
    item.save()

    new_display = spec.display(getattr(item, spec.attr))

    activity = None
    if changed:
        label = spec.label or field_name
        activity = ActivityService().log(
            verb=spec.verb,
            target=item,
            actor=actor,
            summary=f"Changed {label} from {old_display} to {new_display}",
        )

    return FieldUpdateResult(
        field=field_name,
        changed=changed,
        old_value=old_value,
        new_value=new_value,
        old_display=old_display,
        new_display=new_display,
        activity=activity,
    )
