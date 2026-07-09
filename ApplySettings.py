# Copyright (c) 2026 Rafael
# The single choke point between "what the AI suggested" and the live Cura
# profile. Nothing from AIClient.SettingChange reaches the container stack
# except through validate() -> apply() here.

from dataclasses import dataclass, field
from typing import Any, List, Optional, Set

from . import SettingsSchema
from .AIClient import SettingChange

STATUS_OK = "OK"
STATUS_CLAMPED = "CLAMPED"
STATUS_REJECTED_UNKNOWN_KEY = "REJECTED_UNKNOWN_KEY"
STATUS_REJECTED_TYPE = "REJECTED_TYPE"
STATUS_REJECTED_ENUM = "REJECTED_ENUM"


@dataclass
class ValidatedChange:
    key: str
    reasoning: str
    original_proposed_value: Any
    resolved_value: Any
    status: str
    bounds: Optional[dict] = field(default=None)
    note: str = ""


def _coerce_numeric(value: Any, setting_type: str) -> Any:
    if setting_type == "float":
        return float(value)
    if setting_type == "int":
        # AI may send a float-looking number for an int setting -- round it
        # rather than reject, since the intent is clear.
        return int(round(float(value)))
    raise ValueError(f"Not a numeric type: {setting_type}")


def _coerce_bool(value: Any) -> bool:
    # Values arrive as strings (see AIClient.RESPONSE_SCHEMA) -- bool(value)
    # on a string is a classic trap, since bool("false") is True in Python
    # (any non-empty string is truthy). Parse the text explicitly instead.
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def validate(global_stack, changes: List[SettingChange], enabled_keys: List[str]) -> List[ValidatedChange]:
    """Check every proposed change against the setting's *live* bounds.

    Never raises -- always returns one ValidatedChange per input, tagged
    with a status the review UI can render (OK / CLAMPED / REJECTED_*).
    Out-of-range numeric values are clamped, not silently accepted, so a
    hallucinated or out-of-bounds AI suggestion can never bypass the
    machine's/material's real limits.

    enabled_keys is the user's *currently configured* whitelist (see
    SettingsSchema.get_enabled_keys) -- checked here, not against the full
    CATALOG, so disabling a setting in the whitelist editor genuinely
    prevents the AI from changing it, even if a stale suggestion mentions it.
    """
    results: List[ValidatedChange] = []
    enabled_set = set(enabled_keys)

    for change in changes:
        if change.key not in enabled_set:
            results.append(ValidatedChange(
                key=change.key, reasoning=change.reasoning,
                original_proposed_value=change.proposed_value,
                resolved_value=None, status=STATUS_REJECTED_UNKNOWN_KEY,
                note="Not in the allowed settings whitelist.",
            ))
            continue

        bounds = SettingsSchema.get_bounds(global_stack, change.key)
        setting_type = bounds["type"]
        value = change.proposed_value
        status = STATUS_OK
        note = ""

        if setting_type == "enum":
            options = bounds["options"] or {}
            if value not in options:
                results.append(ValidatedChange(
                    key=change.key, reasoning=change.reasoning,
                    original_proposed_value=change.proposed_value,
                    resolved_value=None, status=STATUS_REJECTED_ENUM, bounds=bounds,
                    note=f"'{value}' is not one of the allowed options.",
                ))
                continue

        elif setting_type in ("float", "int"):
            try:
                value = _coerce_numeric(value, setting_type)
            except (TypeError, ValueError):
                results.append(ValidatedChange(
                    key=change.key, reasoning=change.reasoning,
                    original_proposed_value=change.proposed_value,
                    resolved_value=None, status=STATUS_REJECTED_TYPE, bounds=bounds,
                    note=f"Expected a {setting_type}, got {value!r}.",
                ))
                continue

            minimum_value = bounds["minimum_value"]
            maximum_value = bounds["maximum_value"]
            if minimum_value is not None and value < minimum_value:
                value = minimum_value
                status = STATUS_CLAMPED
                note = f"Clamped up to the minimum allowed value ({minimum_value})."
            if maximum_value is not None and value > maximum_value:
                value = maximum_value
                status = STATUS_CLAMPED
                note = f"Clamped down to the maximum allowed value ({maximum_value})."

        elif setting_type == "bool":
            value = _coerce_bool(value)

        results.append(ValidatedChange(
            key=change.key, reasoning=change.reasoning,
            original_proposed_value=change.proposed_value,
            resolved_value=value, status=status, bounds=bounds, note=note,
        ))

    return results


def apply(global_stack, validated_changes: List[ValidatedChange], approved_keys: Set[str]) -> List[str]:
    """Write the approved, non-rejected changes to the user-settings
    container (stack.userChanges -- container index 0, the same "user"
    layer read/written by hand as .cfg files throughout this project).
    Returns the list of keys actually written.

    Does NOT trigger a slice itself -- Cura already re-slices automatically
    on a settings change if auto-slice is on, and leaving the explicit
    "Slice" button to the user avoids forcing a slice at a moment the rest
    of Cura's UI/state isn't expecting it.
    """
    applied_keys: List[str] = []

    for vc in validated_changes:
        if vc.key not in approved_keys:
            continue
        if vc.status.startswith("REJECTED"):
            continue

        stack, _ = SettingsSchema.get_setting_scope(global_stack, vc.key)
        stack.userChanges.setProperty(vc.key, "value", vc.resolved_value)
        applied_keys.append(vc.key)

    return applied_keys
