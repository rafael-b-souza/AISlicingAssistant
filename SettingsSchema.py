# Copyright (c) 2026 Rafael
# Catalog of Cura print settings the AI assistant *can* be allowed to see and
# suggest changes for, plus the generic global-vs-per-extruder scoping and
# live bounds lookup that keeps this correct without hardcoding per key.
#
# IMPORTANT: minimum_value/maximum_value in Cura's setting definitions are
# frequently formula strings evaluated against the live stack (e.g.
# speed_print's maximum_value is "sqrt(machine_max_feedrate_x**2 + ...)"),
# not fixed numbers. Never parse the .def.json files directly for bounds --
# always go through get_bounds() below, which uses getProperty() on the live,
# running container stack so Cura's own SettingFunction machinery resolves
# the formula against current machine/material/nozzle values.

import json
from typing import Optional, Tuple, Any, Dict, List

# The full set of settings the user can choose to enable/disable from the
# assistant's whitelist editor, grouped for display. This is a curated
# superset -- still not the full ~400 Cura exposes, but wider than the
# original fixed set so advanced users have real room to customize.
CATALOG: Dict[str, List[str]] = {
    "Shell": [
        "layer_height", "layer_height_0", "wall_line_count", "wall_thickness",
        "top_bottom_thickness", "top_layers", "bottom_layers",
        "wall_line_width_0", "wall_line_width_x",
    ],
    "Infill": [
        "infill_sparse_density", "infill_pattern", "infill_line_distance",
        "gradual_infill_steps",
    ],
    "Supports": [
        "support_enable", "support_structure", "support_angle",
        "support_infill_rate", "support_interface_enable",
        "support_xy_distance", "support_z_distance",
    ],
    "Adhesion": [
        "adhesion_type", "brim_width", "brim_line_count", "skirt_line_count",
        "raft_airgap",
    ],
    "Speed": [
        "speed_print", "speed_infill", "speed_wall", "speed_wall_0",
        "speed_topbottom", "speed_travel", "speed_layer_0",
    ],
    "Temperature": [
        "material_print_temperature", "material_print_temperature_layer_0",
        "material_bed_temperature", "material_bed_temperature_layer_0",
        "material_standby_temperature",
    ],
    "Retraction": [
        "retraction_amount", "retraction_speed", "retraction_hop_enabled",
        "retraction_hop",
    ],
    "Cooling": [
        "cool_fan_speed", "cool_min_layer_time",
    ],
    "Finish": [
        "ironing_enabled", "ironing_pattern",
    ],
}

# Flattened view of everything in CATALOG, for quick membership checks.
ALL_CATALOG_KEYS: List[str] = [key for keys in CATALOG.values() for key in keys]

# What ships enabled out of the box -- the original curated set from v1,
# still a reasonable default for most users who don't touch the whitelist
# editor at all.
DEFAULT_WHITELIST: List[str] = [
    "layer_height", "layer_height_0", "wall_line_count", "wall_thickness",
    "top_bottom_thickness",
    "infill_sparse_density", "infill_pattern", "infill_line_distance",
    "support_enable", "support_structure", "support_angle", "support_infill_rate",
    "adhesion_type", "brim_width", "skirt_line_count",
    "speed_print", "speed_infill", "speed_wall", "speed_travel",
    "material_print_temperature", "material_bed_temperature",
    "retraction_amount", "retraction_speed",
    "cool_fan_speed",
]

PREFERENCE_ENABLED_KEYS = "ai_slicing_assistant/enabled_keys"


def get_enabled_keys(preferences) -> List[str]:
    """Read the user's configured whitelist from Preferences, falling back
    to DEFAULT_WHITELIST if unset, corrupted, or empty. Unknown keys (e.g.
    from an older catalog version) are dropped rather than kept around."""
    raw = preferences.getValue(PREFERENCE_ENABLED_KEYS)
    try:
        keys = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        keys = None

    if not isinstance(keys, list) or not keys:
        return list(DEFAULT_WHITELIST)

    valid = [key for key in keys if key in ALL_CATALOG_KEYS]
    return valid if valid else list(DEFAULT_WHITELIST)


def set_enabled_keys(preferences, keys: List[str]) -> None:
    valid = [key for key in keys if key in ALL_CATALOG_KEYS]
    preferences.setValue(PREFERENCE_ENABLED_KEYS, json.dumps(valid if valid else DEFAULT_WHITELIST))


def get_setting_scope(global_stack, key: str) -> Tuple[Any, Optional[int]]:
    """Return (target_stack, extruder_index_or_None) to read/write `key` on.

    Never hardcode which settings are "global" vs "per extruder" -- ask the
    live stack, exactly like Cura's own MachineManager does when migrating
    settings between containers. Some settings (layer_height,
    material_bed_temperature, adhesion_type, support_structure, ...) are
    settable_per_extruder == False and must be set on the global stack; the
    rest live on extruderList[n].
    """
    settable_per_extruder = global_stack.getProperty(key, "settable_per_extruder")
    if not settable_per_extruder:
        return global_stack, None

    limit_to_extruder = global_stack.getProperty(key, "limit_to_extruder")
    try:
        extruder_index = int(limit_to_extruder)
    except (TypeError, ValueError):
        extruder_index = -1
    if extruder_index < 0:
        extruder_index = 0  # v1: single-extruder assumption, see plan punt list

    try:
        return global_stack.extruderList[extruder_index], extruder_index
    except IndexError:
        return global_stack.extruderList[0], 0


def get_bounds(global_stack, key: str) -> Dict[str, Any]:
    """Single source of truth for a setting's live-resolved metadata.

    Everything here comes from getProperty() on the *live* stack -- never
    from parsing a .def.json file, since bounds are often formula strings
    resolved against current machine/material/nozzle state.
    """
    stack, _ = get_setting_scope(global_stack, key)
    setting_type = stack.getProperty(key, "type")

    return {
        "key": key,
        "label": stack.getProperty(key, "label"),
        "description": stack.getProperty(key, "description"),
        "type": setting_type,
        "unit": stack.getProperty(key, "unit"),
        "current_value": stack.getProperty(key, "value"),
        "minimum_value": stack.getProperty(key, "minimum_value"),
        "maximum_value": stack.getProperty(key, "maximum_value"),
        "minimum_value_warning": stack.getProperty(key, "minimum_value_warning"),
        "maximum_value_warning": stack.getProperty(key, "maximum_value_warning"),
        "options": stack.getProperty(key, "options") if setting_type == "enum" else None,
    }


def get_all_bounds(global_stack, enabled_keys: List[str]) -> List[Dict[str, Any]]:
    """get_bounds() for every currently-enabled key -- this is what gets
    embedded in the AI request as the settings_context (see AIClient.py)."""
    return [get_bounds(global_stack, key) for key in enabled_keys]


def get_catalog_for_ui(global_stack, enabled_keys: List[str]) -> List[Dict[str, Any]]:
    """Grouped view of the full catalog with live labels and each key's
    current enabled/disabled state, for the whitelist editor in the UI."""
    enabled_set = set(enabled_keys)
    groups = []
    for category, keys in CATALOG.items():
        entries = []
        for key in keys:
            label = global_stack.getProperty(key, "label") or key
            entries.append({"key": key, "label": label, "enabled": key in enabled_set})
        groups.append({"category": category, "settings": entries})
    return groups
