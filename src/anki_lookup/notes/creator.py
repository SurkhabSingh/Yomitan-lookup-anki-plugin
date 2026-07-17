"""Create notes through Anki's supported, undoable collection operations.

The only module here that imports Anki, and it does so inside functions — the same
convention ``ui/*.py`` follows, so metadata and packaging tests stay independent of
Anki's bundled Python.

Two rules the roadmap sets and this enforces:

* **Undoable.** Notes go through ``aqt.operations.note.add_note``, the stock
  ``CollectionOp``, which gives undo, progress, and change broadcast for free. Calling
  ``col.add_note`` directly would work and leave no undo entry — the user would add a
  note mid-review and find Ctrl+Z does nothing.
* **Never touch the card under review.** Nothing here reads or writes
  ``reviewer.card``. Adding a note is strictly additive.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .duplicates import SCOPE_DECK, duplicate_field, duplicate_scope, should_check_duplicates
from .field_mapping import is_configured, mapping_pairs
from .markers import MarkerRegistry, NoteContext, render_fields

logger = logging.getLogger(__name__)

ADDED = "added"
DUPLICATE = "duplicate"
ERROR = "error"
NOT_CONFIGURED = "not_configured"
QUEUED = "queued"

NOT_CONFIGURED_MESSAGE = "Configure a note preset in Tools > Anki Lookup > Note Preset."


class NoteCreationError(RuntimeError):
    """Raised when a note cannot be built from the current preset."""


def preview_fields(
    context: NoteContext,
    preset: dict[str, Any],
    registry: MarkerRegistry,
) -> dict[str, str]:
    """Return the fields a note would be created with. No collection access."""

    return render_fields(mapping_pairs(preset.get("field_mapping")), context, registry)


def find_duplicate(
    context: NoteContext,
    preset: dict[str, Any],
    registry: MarkerRegistry,
) -> int:
    """Return the id of an existing note with the same key field, or 0.

    Scoped to the deck the note is going into unless the preset says otherwise. A
    collection-wide search reported a word saved in one deck as a duplicate when adding
    it to an unrelated one — the second deck does not have that note, and the add is
    legitimate.

    Escaping is Anki's: ``build_search_string`` turns arbitrary text into a literal
    search term, so a definition containing quotes or ``OR``, or a deck named
    ``a OR b``, cannot alter the query. It also leaves ``::`` structural, so a subdeck
    name still addresses the hierarchy rather than a deck literally called that.
    """

    from anki.collection import SearchNode
    from aqt import mw

    if mw is None or mw.col is None:
        return 0

    notetype = mw.col.models.get(preset["notetype_id"])
    if notetype is None:
        return 0

    field_names = [field["name"] for field in notetype["flds"]]
    key_field = duplicate_field(preset, field_names)
    if not key_field:
        return 0

    fields = preview_fields(context, preset, registry)
    value = fields.get(key_field, "")
    if not should_check_duplicates(preset, value):
        return 0

    nodes = [
        SearchNode(note=notetype["name"]),
        SearchNode(field=SearchNode.Field(field_name=key_field, text=value)),
    ]

    if duplicate_scope(preset) == SCOPE_DECK:
        deck_name = _target_deck_name(preset)
        if not deck_name:
            # The deck was deleted between saving the preset and this lookup, so there
            # is no scope to search. Report no duplicate: add_note_from_lookup checks
            # the deck exists before reaching here, and for a direct caller a
            # recoverable duplicate beats blocking a legitimate add.
            return 0
        nodes.append(SearchNode(deck=deck_name))

    note_ids = mw.col.find_notes(mw.col.build_search_string(*nodes))
    return int(note_ids[0]) if note_ids else 0


def _target_deck_name(preset: dict[str, Any]) -> str:
    """The name of the deck a note would be added to, for a search node.

    ``decks.get`` rather than ``decks.name``: the latter answers ``"[no deck]"`` for an
    id that no longer exists, which would silently search a deck by that name instead
    of telling us the deck is gone.
    """

    from aqt import mw

    if mw is None or mw.col is None:
        return ""
    deck = mw.col.decks.get(preset["deck_id"])
    return str(deck.get("name", "")) if deck else ""


def add_note_from_lookup(
    context: NoteContext,
    preset: dict[str, Any],
    registry: MarkerRegistry,
    on_done: Callable[[str, int, str], None],
    allow_duplicate: bool = False,
) -> tuple[str, int]:
    """Queue a note creation. Returns ``(status, note_id)`` for the immediate answer.

    A successful add is reported only through ``on_done``: the collection operation runs
    off the caller's stack, so this returns ``QUEUED`` and the callback carries the
    outcome. Everything knowable now — an unconfigured preset, a duplicate — comes back
    directly, so the popup can react without waiting for a round trip.
    """

    from anki.notes import Note
    from aqt import mw
    from aqt.operations.note import add_note

    if not is_configured(preset):
        return (NOT_CONFIGURED, 0)

    if mw is None or mw.col is None:
        raise NoteCreationError("Anki is not available.")

    notetype = mw.col.models.get(preset["notetype_id"])
    if notetype is None:
        raise NoteCreationError("The configured note type no longer exists.")

    if mw.col.decks.get(preset["deck_id"]) is None:
        raise NoteCreationError("The configured deck no longer exists.")

    if not allow_duplicate:
        duplicate_id = find_duplicate(context, preset, registry)
        if duplicate_id:
            return (DUPLICATE, duplicate_id)

    note = Note(mw.col, notetype)
    fields = preview_fields(context, preset, registry)
    available = set(note.keys())
    for field_name, value in fields.items():
        # A preset can outlive a notetype edit. Skip fields that are gone rather than
        # raising KeyError halfway through a review.
        if field_name in available:
            note[field_name] = value

    tags = preset.get("tags")
    if isinstance(tags, list):
        note.tags = [str(tag) for tag in tags if isinstance(tag, str) and tag.strip()]

    def _on_success(changes: Any) -> None:
        on_done(ADDED, int(note.id), "")

    def _on_failure(error: Exception) -> None:
        logger.exception("Anki Lookup could not add a note", exc_info=error)
        on_done(ERROR, 0, str(error))

    operation = add_note(parent=mw, note=note, target_deck_id=preset["deck_id"])
    operation.success(_on_success).failure(_on_failure).run_in_background()
    return (QUEUED, 0)


def open_note_in_browser(note_id: int) -> None:
    """Show an existing note, so a duplicate offers something better than a dead end."""

    import aqt
    from aqt import mw

    if mw is None:
        return
    browser = aqt.dialogs.open("Browser", mw)
    browser.search_for(f"nid:{note_id}")
