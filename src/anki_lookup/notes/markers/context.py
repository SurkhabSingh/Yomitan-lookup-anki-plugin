"""Everything a marker can read.

One object, assembled once per note, holding the lookup result plus the context the
popup captured around it. Markers are pure functions of this — they touch no
collection, no network, and no configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...dictionary.models import LookupEntry


@dataclass(frozen=True)
class Cloze:
    """A sentence partitioned around the scanned word.

    The invariant that makes this useful: ``prefix + body + suffix == sentence``,
    always. That is what lets a field like ``{cloze-prefix}<b>{cloze-body}</b>``
    ``{cloze-suffix}`` reassemble the sentence with the word emphasised.

    ``body`` is the surface form **as it appeared on the card** — 食べました, not the
    headword 食べる. Using the headword would produce a sentence that no longer says
    what the card said.
    """

    sentence: str = ""
    prefix: str = ""
    body: str = ""
    suffix: str = ""
    body_kana: str = ""


@dataclass(frozen=True)
class NoteContext:
    """The lookup, the card it came from, and anything resolved for it."""

    entry: LookupEntry
    #: Every entry from the same lookup, not just the chosen one. Frequency and pitch
    #: markers aggregate across dictionaries, so they need more than one entry.
    entries: tuple[LookupEntry, ...] = ()
    cloze: Cloze = field(default_factory=Cloze)
    #: The exact text the user scanned, before any deinflection.
    source_term: str = ""
    translation: str = ""
    source_deck: str = ""
    #: Media resolved before rendering, keyed by marker name. Empty unless a marker
    #: that needs it appeared in a field.
    media: tuple[tuple[str, str], ...] = ()

    def media_value(self, name: str) -> str:
        for key, value in self.media:
            if key == name:
                return value
        return ""

    @property
    def is_kanji(self) -> bool:
        return self.entry.entry_type == "kanji"

    def metadata_value(self, key: str) -> str:
        for name, value in self.entry.metadata:
            if name == key:
                return value
        return ""
