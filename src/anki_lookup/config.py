"""Validated add-on configuration for runtime injection."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .notes.duplicates import ALLOWED_SCOPES as ALLOWED_DUPLICATE_SCOPES
from .notes.field_mapping import is_configured, normalize_mapping
from .translation.languages import normalize_target_language, target_language_label
from .translation.models import ALLOWED_PROVIDERS

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
        "frequency_sort_dictionary_id": 0,
        "frequency_sort_order": "auto",
    },
    "appearance": {
        "theme": "system",
        "font_family": "",
        "font_size_px": 14,
        "popup_width_px": 360,
        "popup_max_height_px": 420,
        "dictionary_layout": "source_rail",
    },
    "notes": {
        "deck_id": 0,
        "notetype_id": 0,
        # A LIST, not a dict keyed by field name. _merge_known below only merges keys
        # already present here, and user-chosen field names cannot be predeclared — a
        # dict-shaped mapping would be silently erased on every config read, and would
        # present to the user as "my field mapping keeps resetting itself".
        "field_mapping": [],
        "tags": ["anki-lookup"],
        "duplicate_field": "",
        "check_duplicates": True,
        # Search the deck being added to, not the whole collection: a word saved in one
        # deck is not a duplicate of one being added to an unrelated deck.
        "duplicate_scope": "deck",
    },
    "translation": {
        "provider": "google-translate",
        "target_language": "en",
        # Off by default, and deliberately so. Turning this on binds port 8791, which
        # the Wonder of U desktop app also wants: whoever binds first wins, and the
        # browser extension has no way to be pointed at the loser. Defaulting to on
        # would mean installing this add-on could silently break translation in the
        # desktop app, with nothing but a log line to explain it.
        "bridge_enabled": False,
        "cache_ttl_hours": 168,
    },
}

ALLOWED_MODIFIERS = {"Shift", "Control", "Alt", "Meta"}
ALLOWED_RELEASE_BEHAVIORS = {"close", "remain_open"}
ALLOWED_FREQUENCY_SORT_ORDERS = {"auto", "ascending", "descending"}
ALLOWED_THEMES = {"system", "light", "dark", "high_contrast"}
ALLOWED_DICTIONARY_LAYOUTS = {"source_rail", "continuous"}

#: Maximum cache lifetime, in hours (one year). Zero turns caching off.
MAX_CACHE_TTL_HOURS = 8_760


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
    lookup["frequency_sort_dictionary_id"] = _bounded_int(
        lookup["frequency_sort_dictionary_id"],
        0,
        2_147_483_647,
        0,
    )
    if lookup["frequency_sort_order"] not in ALLOWED_FREQUENCY_SORT_ORDERS:
        lookup["frequency_sort_order"] = DEFAULT_CONFIG["lookup"]["frequency_sort_order"]
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

    _validate_translation(config["translation"])
    _validate_notes(config["notes"])

    return config


def _validate_notes(notes: dict[str, Any]) -> None:
    """Clamp the note preset in place."""

    defaults = DEFAULT_CONFIG["notes"]

    notes["deck_id"] = _bounded_int(notes["deck_id"], 0, 2**63 - 1, 0)
    notes["notetype_id"] = _bounded_int(notes["notetype_id"], 0, 2**63 - 1, 0)
    notes["field_mapping"] = normalize_mapping(notes["field_mapping"])

    if not isinstance(notes["duplicate_field"], str):
        notes["duplicate_field"] = defaults["duplicate_field"]
    notes["duplicate_field"] = notes["duplicate_field"][:200]

    if not isinstance(notes["check_duplicates"], bool):
        notes["check_duplicates"] = defaults["check_duplicates"]

    if notes["duplicate_scope"] not in ALLOWED_DUPLICATE_SCOPES:
        notes["duplicate_scope"] = defaults["duplicate_scope"]

    tags = notes["tags"]
    notes["tags"] = (
        [tag.strip()[:100] for tag in tags if isinstance(tag, str) and tag.strip()][:20]
        if isinstance(tags, list)
        else list(defaults["tags"])
    )

    # Derived, not persisted: lets the popup enable or disable its Add button without
    # knowing what makes a preset valid.
    notes["configured"] = is_configured(notes)


def _validate_translation(translation: dict[str, Any]) -> None:
    """Clamp the translation settings in place.

    The provider check is not cosmetic. The browser extension does **not** sanitize
    the ``provider`` field of a job: an unknown non-empty string is not coerced to a
    default, it fails the job outright with a confusing bridge error. This is the
    clamp that guarantees only ids the extension accepts ever reach the wire.
    """

    defaults = DEFAULT_CONFIG["translation"]

    if translation["provider"] not in ALLOWED_PROVIDERS:
        translation["provider"] = defaults["provider"]

    # Provider-aware, and re-checked in both directions rather than filtered: the two
    # target lists are not supersets of one another. Norwegian is "no" for Google and
    # "nb" for DeepL, so a code that is valid for one is rejected by the other.
    translation["target_language"] = normalize_target_language(
        translation["target_language"],
        translation["provider"],
    )

    translation["cache_ttl_hours"] = _bounded_int(
        translation["cache_ttl_hours"], 0, MAX_CACHE_TTL_HOURS, defaults["cache_ttl_hours"]
    )

    # Derived, not persisted: injected so the popup can name the target language
    # without shipping the language tables into JavaScript.
    translation["target_language_label"] = target_language_label(
        translation["target_language"],
        translation["provider"],
    )


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
