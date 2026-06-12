"""Validated add-on configuration for runtime injection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DEFAULT_CONFIG: dict[str, Any] = {
    "config_version": 1,
    "lookup": {
        "modifier": "Shift",
        "release_behavior": "remain_open",
        "selection_shortcut": "Ctrl+Shift+L",
        "pin_shortcut": "Ctrl+Shift+K",
        "debounce_ms": 20,
        "maximum_term_length": 200,
        "allow_nested_popups": True,
        "maximum_popup_depth": 4,
    },
    "appearance": {
        "theme": "system",
        "font_family": "",
        "font_size_px": 14,
        "popup_width_px": 360,
        "popup_max_height_px": 420,
        "dictionary_layout": "source_rail",
    },
}

ALLOWED_MODIFIERS = {"Shift", "Control", "Alt", "Meta"}
ALLOWED_RELEASE_BEHAVIORS = {"close", "remain_open"}
ALLOWED_THEMES = {"system", "light", "dark", "high_contrast"}
ALLOWED_DICTIONARY_LAYOUTS = {"source_rail", "continuous"}


def runtime_config(raw_config: object) -> dict[str, Any]:
    """Return a safe, complete configuration suitable for JavaScript."""

    config = deepcopy(DEFAULT_CONFIG)
    if isinstance(raw_config, dict):
        _merge_known(config, raw_config)

    lookup = config["lookup"]
    appearance = config["appearance"]

    if lookup["modifier"] not in ALLOWED_MODIFIERS:
        lookup["modifier"] = DEFAULT_CONFIG["lookup"]["modifier"]
    if lookup["release_behavior"] not in ALLOWED_RELEASE_BEHAVIORS:
        lookup["release_behavior"] = DEFAULT_CONFIG["lookup"]["release_behavior"]
    lookup["debounce_ms"] = _bounded_int(lookup["debounce_ms"], 0, 250, 20)
    lookup["maximum_term_length"] = _bounded_int(lookup["maximum_term_length"], 1, 500, 200)
    lookup["maximum_popup_depth"] = _bounded_int(lookup["maximum_popup_depth"], 1, 8, 4)
    lookup["selection_shortcut"] = validated_shortcut(
        lookup["selection_shortcut"],
        DEFAULT_CONFIG["lookup"]["selection_shortcut"],
    )
    lookup["pin_shortcut"] = validated_shortcut(
        lookup["pin_shortcut"],
        DEFAULT_CONFIG["lookup"]["pin_shortcut"],
    )
    if lookup["pin_shortcut"] == lookup["selection_shortcut"]:
        lookup["pin_shortcut"] = DEFAULT_CONFIG["lookup"]["pin_shortcut"]

    if appearance["theme"] not in ALLOWED_THEMES:
        appearance["theme"] = DEFAULT_CONFIG["appearance"]["theme"]
    if appearance["dictionary_layout"] not in ALLOWED_DICTIONARY_LAYOUTS:
        appearance["dictionary_layout"] = DEFAULT_CONFIG["appearance"]["dictionary_layout"]
    appearance["font_family"] = str(appearance["font_family"])[:200]
    appearance["font_size_px"] = _bounded_int(appearance["font_size_px"], 10, 32, 14)
    appearance["popup_width_px"] = _bounded_int(appearance["popup_width_px"], 240, 720, 360)
    appearance["popup_max_height_px"] = _bounded_int(
        appearance["popup_max_height_px"], 180, 800, 420
    )

    return config


def _merge_known(target: dict[str, Any], source: dict[object, object]) -> None:
    for key, target_value in target.items():
        source_value = source.get(key)
        if isinstance(target_value, dict) and isinstance(source_value, dict):
            _merge_known(target_value, source_value)
        elif source_value is not None and isinstance(source_value, type(target_value)):
            target[key] = source_value


def _bounded_int(value: object, minimum: int, maximum: int, fallback: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return fallback
    return min(maximum, max(minimum, value))


def validated_shortcut(value: object, fallback: str) -> str:
    if not isinstance(value, str):
        return fallback
    parts = [part.strip() for part in value.split("+") if part.strip()]
    if len(parts) < 2:
        return fallback
    modifiers = {"ctrl": "Ctrl", "shift": "Shift", "alt": "Alt", "meta": "Meta"}
    normalized_modifiers = []
    for part in parts[:-1]:
        modifier = modifiers.get(part.casefold())
        if modifier is None or modifier in normalized_modifiers:
            return fallback
        normalized_modifiers.append(modifier)
    key = parts[-1]
    if len(key) != 1 or not key.isalnum():
        return fallback
    return "+".join([*normalized_modifiers, key.upper()])
