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
        "debounce_ms": 90,
        "maximum_term_length": 200,
    },
    "appearance": {
        "theme": "system",
        "font_family": "",
        "font_size_px": 14,
        "popup_width_px": 360,
        "popup_max_height_px": 420,
    },
}

ALLOWED_MODIFIERS = {"Shift", "Control", "Alt", "Meta"}
ALLOWED_RELEASE_BEHAVIORS = {"close", "remain_open", "pin"}
ALLOWED_THEMES = {"system", "light", "dark", "high_contrast"}


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
    lookup["debounce_ms"] = _bounded_int(lookup["debounce_ms"], 30, 500, 90)
    lookup["maximum_term_length"] = _bounded_int(lookup["maximum_term_length"], 1, 500, 200)

    if appearance["theme"] not in ALLOWED_THEMES:
        appearance["theme"] = DEFAULT_CONFIG["appearance"]["theme"]
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
