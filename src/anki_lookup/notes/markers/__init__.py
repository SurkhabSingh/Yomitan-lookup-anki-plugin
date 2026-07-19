"""Marker-based note fields.

A field value is text with ``{marker}`` tokens. Rendering substitutes them and passes
everything else through, so ``{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}`` gives
the card's own sentence with the scanned word bolded.
"""

from __future__ import annotations

import re

from ...dictionary.models import LookupEntry
from .builtin import registry as builtin_registry
from .context import Cloze, NoteContext
from .registry import (
    GROUP_GLOSSARY,
    TERM,
    Marker,
    MarkerFunc,
    MarkerRegistry,
)
from .render import MARKER_PATTERN, render_field, render_fields, used_markers

__all__ = [
    "MARKER_PATTERN",
    "Cloze",
    "Marker",
    "MarkerFunc",
    "MarkerRegistry",
    "NoteContext",
    "build_registry",
    "kebab_case",
    "render_field",
    "render_fields",
    "used_markers",
]

#: Anything that is not a letter or a digit becomes a separator — including ``_``,
#: which would otherwise survive into a name where a hyphen is meant. Unicode-aware,
#: so CJK titles keep their characters instead of reducing to nothing.
_NON_MARKER_CHARS = re.compile(r"[\W_]+", re.UNICODE)


def kebab_case(value: str) -> str:
    """Turn a dictionary title into a marker name.

    ``旺文社国語辞典 第十一版`` becomes ``旺文社国語辞典-第十一版``, which is what makes
    ``{single-glossary-旺文社国語辞典-第十一版}`` addressable. An earlier ASCII-only
    version reduced every CJK title to an empty string, and :func:`build_registry`
    then skipped it — so a Japanese dictionary library got no per-dictionary markers
    whatsoever.

    Still lossy: two titles differing only in punctuation collapse together, so
    :func:`build_registry` refuses a collision rather than letting one dictionary's
    marker quietly resolve to another's entries.
    """

    return _NON_MARKER_CHARS.sub("-", value.casefold()).strip("-")


def _single_glossary(dictionary: str) -> MarkerFunc:
    """A marker bound to one dictionary.

    A closure over the name, **not** generated marker text with the name interpolated
    into it. The reference design builds template source by string concatenation and
    needs an escaping function to stop a dictionary called ``foo'}}{{evil`` breaking
    out of the quoted literal it lands in. A function that closes over the string has
    no such boundary to get wrong.
    """

    def render(context: NoteContext) -> str:
        entries = context.entries or (context.entry,)
        definitions: list[str] = []
        for entry in entries:
            if entry.dictionary != dictionary:
                continue
            definitions.extend(entry.definitions)
        if not definitions:
            return ""
        if len(definitions) == 1:
            return definitions[0]
        return "\n".join(
            f"{index}. {definition}" for index, definition in enumerate(definitions, 1)
        )

    return render


def build_registry(dictionary_titles: tuple[str, ...] = ()) -> MarkerRegistry:
    """The built-in markers, plus one per installed dictionary.

    ``single-glossary-<name>`` lets a field take its definition from one dictionary
    regardless of which entry the user pressed Add on.
    """

    registry = MarkerRegistry()
    for marker in builtin_registry.all():
        registry.add(marker)

    for title in dictionary_titles:
        slug = kebab_case(title)
        if not slug:
            # Nothing usable survived — a CJK-only title, say. Better no marker than
            # one named `single-glossary-` that shadows the next such dictionary.
            continue
        name = f"single-glossary-{slug}"
        if registry.get(name) is not None:
            continue
        registry.add(
            Marker(
                name=name,
                group=GROUP_GLOSSARY,
                description=f"Definitions from {title} only.",
                render=_single_glossary(title),
                applies_to=(TERM,),
            )
        )

    return registry


def context_for(
    entry: LookupEntry,
    entries: tuple[LookupEntry, ...] = (),
    cloze: Cloze | None = None,
    source_term: str = "",
    translation: str = "",
    source_deck: str = "",
    media: tuple[tuple[str, str], ...] = (),
) -> NoteContext:
    """Build a marker context, guaranteeing the selected entry is among ``entries``.

    Aggregating markers such as ``{single-glossary-<dict>}`` and ``{frequencies}`` read
    ``entries``, while ``{glossary}`` reads ``entry``. If the two disagree — the entry
    the user chose is absent from the aggregate list — a field can render empty while
    the popup showed content. So the entry is always a member here: markers cannot see
    a narrower world than the entry the note is being built from.
    """

    complete = entries if entry in entries else (*entries, entry)
    return NoteContext(
        entry=entry,
        entries=complete,
        cloze=cloze or Cloze(),
        source_term=source_term,
        translation=translation,
        source_deck=source_deck,
        media=media,
    )
