"""Map lookup values onto note fields.

**The mapping is a list, not a dictionary, and that is not a style choice.**

``config._merge_known`` only merges keys already present in ``DEFAULT_CONFIG``, and a
mapping keyed by the user's own field names has no keys we can predeclare. A
dict-shaped mapping would therefore be silently dropped on every config read — the
user would configure their fields, save, reopen, and find it reset, with nothing in any
log to explain it. A list of records survives the merge because the whole list is one
value of a predeclared key.

Each record is ``{"field": "Front", "value": "{expression}"}``. The value is freeform
text with ``{marker}`` tokens, so a field can be more than one thing:
``{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}``.
"""

from __future__ import annotations

from typing import Any

from .markers import MARKER_PATTERN

#: Cap on one field's value. Long enough for any real template, short enough that a
#: corrupted config cannot carry a novel into the editor.
MAX_VALUE_LENGTH = 1_000


def normalize_mapping(raw_mapping: object) -> list[dict[str, str]]:
    """Return a clean mapping, dropping anything malformed.

    Config is user-editable JSON, so every record here is untrusted. Records in the
    0.4.0 shape — ``{"field": ..., "source": "expression"}`` — are migrated to
    ``{"field": ..., "value": "{expression}"}`` on the way through, which is lossless:
    every old source name is a marker name.
    """

    if not isinstance(raw_mapping, list):
        return []

    mapping: list[dict[str, str]] = []
    seen_fields: set[str] = set()

    for record in raw_mapping:
        if not isinstance(record, dict):
            continue

        field = record.get("field")
        if not isinstance(field, str):
            continue
        field = field.strip()
        if not field or field in seen_fields:
            continue

        value = _value_of(record)
        if value is None:
            continue

        seen_fields.add(field)
        mapping.append({"field": field, "value": value[:MAX_VALUE_LENGTH]})

    return mapping


def _value_of(record: dict[Any, Any]) -> str | None:
    value = record.get("value")
    if isinstance(value, str):
        return value

    # 0.4.0 presets named a single source per field.
    source = record.get("source")
    if isinstance(source, str) and source:
        if source == "empty":
            return ""
        return f"{{{source}}}"

    return None


def mapped_fields(raw_mapping: object) -> list[str]:
    return [record["field"] for record in normalize_mapping(raw_mapping)]


def mapping_pairs(raw_mapping: object) -> tuple[tuple[str, str], ...]:
    """The mapping as ``(field, value)`` pairs, ready to render."""

    return tuple((record["field"], record["value"]) for record in normalize_mapping(raw_mapping))


def markers_used(raw_mapping: object) -> tuple[str, ...]:
    """Every marker the mapping mentions.

    Found by regex before anything renders, which is what lets the caller resolve the
    expensive markers — audio, sentence furigana — up front instead of discovering
    mid-render that it needs them.
    """

    seen: list[str] = []
    for record in normalize_mapping(raw_mapping):
        for match in MARKER_PATTERN.finditer(record["value"]):
            name = match.group(1)
            if name not in seen:
                seen.append(name)
    return tuple(seen)


def is_configured(preset: dict[str, Any]) -> bool:
    """Whether a preset can actually create a note.

    Checked before the popup offers an Add button: a half-configured preset should
    disable the button with an explanation, never fail mid-review.
    """

    if not isinstance(preset, dict):
        return False
    if not isinstance(preset.get("deck_id"), int) or preset["deck_id"] <= 0:
        return False
    if not isinstance(preset.get("notetype_id"), int) or preset["notetype_id"] <= 0:
        return False

    mapping = normalize_mapping(preset.get("field_mapping"))
    # A mapping of nothing but blank values would create an empty note.
    return any(record["value"].strip() for record in mapping)
