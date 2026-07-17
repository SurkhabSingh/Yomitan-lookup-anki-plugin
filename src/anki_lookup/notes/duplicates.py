"""Duplicate-check policy.

Deliberately does **not** escape Anki search syntax by hand. Anki ships
``col.build_search_string(SearchNode(...))``, which escapes quotes, wildcards, colons,
backslashes and stray boolean keywords correctly; a hand-written escaper looks right
until the day a definition contains ``"`` or ``OR`` and silently searches for something
else. The escaping lives in ``creator.py``, next to the Anki import it needs.

What is here is the part worth testing without Anki: *which* field to check, and
whether a value is worth checking at all.
"""

from __future__ import annotations

from typing import Any

#: Where to look for an existing note.
#:
#: ``deck`` searches the deck the note is being added to, and — following Anki's own
#: ``deck:`` semantics — its subdecks. ``collection`` searches everywhere.
SCOPE_DECK = "deck"
SCOPE_COLLECTION = "collection"

ALLOWED_SCOPES = (SCOPE_DECK, SCOPE_COLLECTION)


def duplicate_scope(preset: dict[str, Any]) -> str:
    """Return where to look for a duplicate.

    Defaults to the deck being added to. Searching the whole collection means a word
    saved in one deck blocks adding it to an unrelated one, which is wrong for anyone
    keeping separate decks: the second deck genuinely does not have that note.
    """

    configured = preset.get("duplicate_scope")
    if configured in ALLOWED_SCOPES:
        return str(configured)
    return SCOPE_DECK


def duplicate_field(preset: dict[str, Any], field_names: list[str]) -> str:
    """Return the field to check for duplicates.

    Defaults to the notetype's first field, which is Anki's own definition of a
    duplicate and what the card browser's duplicate indicator uses. A configured field
    wins, but only if the notetype actually still has it: notetypes get edited, and a
    preset naming a field that no longer exists should fall back rather than silently
    check nothing.
    """

    if not field_names:
        return ""

    configured = preset.get("duplicate_field")
    if isinstance(configured, str) and configured in field_names:
        return configured
    return field_names[0]


def should_check_duplicates(preset: dict[str, Any], value: str) -> bool:
    """Whether a duplicate check is worth running.

    An empty value matches every other note with an empty first field, which is not a
    duplicate in any useful sense — it is an empty note, and that is a different
    problem.
    """

    if preset.get("check_duplicates") is False:
        return False
    return bool(value.strip())
