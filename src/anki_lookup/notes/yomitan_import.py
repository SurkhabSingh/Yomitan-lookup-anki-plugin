"""Read a Yomitan settings backup and turn it into note presets.

Pure parsing — no Anki, no filesystem. The UI hands us the file's text and turns the
result into the editor's controls; everything here is testable in isolation.

A Yomitan backup is one JSON file wrapping the whole options tree. The Anki config
lives at ``options.profiles[profileCurrent].options.anki`` and has taken three shapes
over the years; all three are handled:

* **v64+** - ``anki.cardFormats[]``: one entry per note preset, typed term or kanji.
* **v59 to 63** - ``anki.terms`` / ``anki.kanji``: a fixed pair, fields are objects.
* **before v59** - the same pair, but field values are plain strings.

Deck and model are stored as **names**, and field values use the same single-brace
``{marker}`` syntax we do, so most markers pass through unchanged. The ones we do not
implement are stripped and reported rather than left to print as literal text on every
card.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .markers import MARKER_PATTERN, kebab_case

#: Yomitan markers that map to ours unchanged. Same spelling on both sides, so the
#: value passes through untouched. Kept explicit rather than "anything the registry
#: knows" because the registry also holds per-dictionary markers, which need the
#: resolve check below.
MAPPABLE_MARKERS = frozenset(
    {
        "expression",
        "reading",
        "furigana",
        "furigana-plain",
        "dictionary",
        "tags",
        "part-of-speech",
        "conjugation",
        "glossary",
        "glossary-brief",
        "glossary-no-dictionary",
        "glossary-plain",
        "glossary-plain-no-dictionary",
        "glossary-first",
        "glossary-first-brief",
        "glossary-first-no-dictionary",
        "frequencies",
        "frequency-harmonic-rank",
        "frequency-harmonic-occurrence",
        "frequency-average-rank",
        "frequency-average-occurrence",
        "pitch-accents",
        "pitch-accent-graphs",
        "pitch-accent-positions",
        "pitch-accent-categories",
        "phonetic-transcriptions",
        "sentence",
        "sentence-furigana",
        "cloze-prefix",
        "cloze-body",
        "cloze-body-kana",
        "cloze-suffix",
        "translation",
        "character",
        "onyomi",
        "kunyomi",
        "stroke-count",
    }
)

#: Yomitan markers we deliberately do not implement — image and browser-tab things,
#: plus a couple of alternate renderings. Named so the report can explain each rather
#: than leaving a mystery ``{marker}`` on the card.
UNSUPPORTED_MARKERS = frozenset(
    {
        "audio",
        "screenshot",
        "clipboard-image",
        "clipboard-text",
        "popup-selection-text",
        "selection-text",
        "url",
        "url-plain",
        "document-title",
        "search-query",
        "dictionary-alias",
        "onyomi-hiragana",
        "pitch-accent-graphs-jj",
        "sentence-furigana-plain",
    }
)

#: Yomitan's duplicate scopes → ours. ``deck-root`` has no exact analogue; ``deck`` is
#: the closest, and the safer direction (a narrower search than the user had).
_DUPLICATE_SCOPES = {"collection": "collection", "deck": "deck", "deck-root": "deck"}


class YomitanImportError(ValueError):
    """The file is not a Yomitan backup we can read."""


@dataclass
class ImportedPreset:
    """One note format lifted from a Yomitan backup, ready to fill the editor.

    Deck and model are names, exactly as Yomitan stored them; the UI resolves them to
    ids. ``field_mapping`` is already in our ``{"field", "value"}`` list shape.
    """

    name: str
    note_type: str  # "term" or "kanji"
    deck_name: str
    model_name: str
    field_mapping: list[dict[str, str]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    duplicate_scope: str = "deck"
    check_duplicates: bool = True
    #: Markers found in the source that we do not implement, one entry per
    #: (field, marker), so the UI can tell the user exactly what was dropped.
    dropped_markers: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class ImportResult:
    presets: list[ImportedPreset]
    profile_name: str


def parse_backup(text: str) -> ImportResult:
    """Parse a Yomitan backup's text into importable presets.

    Fails soft: anything we cannot make sense of raises :class:`YomitanImportError`
    with a message a user can act on, never a half-built preset.
    """

    try:
        data = json.loads(text)
    except (ValueError, TypeError) as error:
        raise YomitanImportError("This is not a valid JSON file.") from error

    options = _options_of(data)
    profile = _current_profile(options)
    anki = _anki_of(profile)

    presets = _presets_of(anki)
    if not presets:
        raise YomitanImportError(
            "No Anki note formats were found in this backup. Configure Anki in Yomitan "
            "first, then export again."
        )

    return ImportResult(presets=presets, profile_name=str(profile.get("name", "")))


def _options_of(data: Any) -> dict[str, Any]:
    """Reach the options tree in either a full backup or a bare options export."""

    if not isinstance(data, dict):
        raise YomitanImportError("This file does not look like a Yomitan backup.")

    # A settings backup wraps the options; an older/bare export may be the tree itself.
    options = data.get("options", data)
    if not isinstance(options, dict) or "profiles" not in options:
        raise YomitanImportError(
            "This file does not contain Yomitan profiles. Export your settings from "
            "Yomitan's Backup page."
        )
    return options


def _current_profile(options: dict[str, Any]) -> dict[str, Any]:
    profiles = options.get("profiles")
    if not isinstance(profiles, list) or not profiles:
        raise YomitanImportError("The backup has no profiles.")

    index = options.get("profileCurrent", 0)
    if not isinstance(index, int) or not 0 <= index < len(profiles):
        index = 0

    profile = profiles[index]
    if not isinstance(profile, dict):
        raise YomitanImportError("The backup's current profile is malformed.")
    return profile


def _anki_of(profile: dict[str, Any]) -> dict[str, Any]:
    options = profile.get("options")
    anki = options.get("anki") if isinstance(options, dict) else None
    if not isinstance(anki, dict):
        raise YomitanImportError("The profile has no Anki settings.")
    return anki


def _presets_of(anki: dict[str, Any]) -> list[ImportedPreset]:
    scope = _DUPLICATE_SCOPES.get(str(anki.get("duplicateScope", "")), "deck")
    check = anki.get("checkForDuplicates")
    check_duplicates = check if isinstance(check, bool) else True
    tags = _string_list(anki.get("tags"))

    card_formats = anki.get("cardFormats")
    if isinstance(card_formats, list):
        # v64+: one preset per card format.
        return [
            preset
            for card_format in card_formats
            if isinstance(card_format, dict)
            for preset in [_from_card_format(card_format, tags, scope, check_duplicates)]
            if preset is not None
        ]

    # Older: a fixed terms/kanji pair.
    presets: list[ImportedPreset] = []
    for note_type in ("terms", "kanji"):
        section = anki.get(note_type)
        if isinstance(section, dict):
            preset = _from_legacy_section(note_type, section, tags, scope, check_duplicates)
            if preset is not None:
                presets.append(preset)
    return presets


def _from_card_format(
    card_format: dict[str, Any],
    tags: list[str],
    scope: str,
    check_duplicates: bool,
) -> ImportedPreset | None:
    note_type = "kanji" if card_format.get("type") == "kanji" else "term"
    mapping, dropped = _translate_fields(card_format.get("fields"))
    if not mapping:
        return None

    return ImportedPreset(
        name=str(card_format.get("name") or note_type.title()),
        note_type=note_type,
        deck_name=str(card_format.get("deck", "")),
        model_name=str(card_format.get("model", "")),
        field_mapping=mapping,
        tags=list(tags),
        duplicate_scope=scope,
        check_duplicates=check_duplicates,
        dropped_markers=dropped,
    )


def _from_legacy_section(
    note_type: str,
    section: dict[str, Any],
    tags: list[str],
    scope: str,
    check_duplicates: bool,
) -> ImportedPreset | None:
    mapping, dropped = _translate_fields(section.get("fields"))
    if not mapping:
        return None

    kind = "kanji" if note_type == "kanji" else "term"
    return ImportedPreset(
        name="Kanji" if kind == "kanji" else "Terms",
        note_type=kind,
        deck_name=str(section.get("deck", "")),
        model_name=str(section.get("model", "")),
        field_mapping=mapping,
        tags=list(tags),
        duplicate_scope=scope,
        check_duplicates=check_duplicates,
        dropped_markers=dropped,
    )


def _translate_fields(
    fields: Any,
) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    """Convert Yomitan's fields to our mapping, dropping markers we do not implement.

    A field value is text with ``{marker}`` tokens. An unsupported marker is removed
    from the value and recorded, so the field keeps its supported markers and its
    literal text but never carries a marker that would print as ``{audio}`` on a card.
    """

    if not isinstance(fields, dict):
        return [], []

    mapping: list[dict[str, str]] = []
    dropped: list[tuple[str, str]] = []

    for field_name, raw_value in fields.items():
        if not isinstance(field_name, str):
            continue
        value = _field_value(raw_value)
        cleaned, field_dropped = _strip_unsupported(value)
        for marker in field_dropped:
            dropped.append((field_name, marker))
        mapping.append({"field": field_name, "value": cleaned})

    return mapping, dropped


def _field_value(raw_value: Any) -> str:
    """A field value is either a plain string (<v59) or ``{value, overwriteMode}``."""

    if isinstance(raw_value, str):
        return raw_value
    if isinstance(raw_value, dict):
        value = raw_value.get("value")
        if isinstance(value, str):
            return value
    return ""


def _strip_unsupported(value: str) -> tuple[str, list[str]]:
    """Remove tokens we do not implement, returning the cleaned value and their names.

    A ``single-glossary-<dict>`` token is kept only when it resolves to a marker name
    we would register — the kebab form matches ours, so a token whose dictionary the
    user also has here will work; one we cannot resolve is dropped like any other
    unsupported marker rather than left to render blank.
    """

    dropped: list[str] = []

    def replace(match: re.Match[str]) -> str:
        marker = match.group(1)
        if _is_supported(marker):
            return match.group(0)
        dropped.append(marker)
        return ""

    cleaned = MARKER_PATTERN.sub(replace, value)
    # Tidy the gaps a removed token leaves: collapse runs of spaces, then trim the
    # ends. Leading and trailing whitespace has no effect in an Anki field template,
    # so trimming it is safe and avoids a value like "{glossary} " after a drop.
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()
    return cleaned, dropped


def _is_supported(marker: str) -> bool:
    if marker in MAPPABLE_MARKERS:
        return True
    if marker in UNSUPPORTED_MARKERS:
        return False
    if marker.startswith("single-glossary-"):
        # Kept only if it is a plain single-glossary token (no -brief/-plain variants,
        # which we do not offer per dictionary). The name itself is trusted to resolve
        # against whatever dictionaries the user has installed here.
        return _is_plain_single_glossary(marker)
    # An unknown marker is most likely an Anki template reference the user put in the
    # field on purpose; leave it, as the renderer does.
    return True


def _is_plain_single_glossary(marker: str) -> bool:
    suffix = marker[len("single-glossary-") :]
    if not suffix:
        return False
    for variant in ("-no-dictionary", "-plain-no-dictionary", "-plain", "-brief"):
        if suffix.endswith(variant):
            return False
    # Round-trip through our slugger: if it does not survive, it cannot be a marker we
    # would register.
    return bool(kebab_case(suffix))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item.strip()]
