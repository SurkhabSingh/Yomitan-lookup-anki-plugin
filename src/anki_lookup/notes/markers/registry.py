"""The marker registry.

**One registry, and the editor's menu is derived from it.** The obvious alternative —
a list of marker names for the menu, and the implementations somewhere else — drifts:
the reference implementation this design learned from offers a marker in its settings
UI that no longer renders anything, precisely because the two lists are maintained by
hand. Deriving the menu from the registry makes that impossible.

A marker is a plain function of a :class:`NoteContext`. There is no template engine
and nothing is evaluated: a field value is text with ``{marker}`` tokens in it, and
rendering substitutes them. That satisfies the roadmap's "do not allow arbitrary
executable CSS or JavaScript" by construction, and it means the set of markers a
preset uses can be found with a regex *before* rendering — which is what lets audio be
fetched up front instead of needing a render-collect-refetch-rerender protocol.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .context import NoteContext

MarkerFunc = Callable[[NoteContext], str]

#: Marker groups, in the order the preset editor should offer them.
GROUP_IDENTITY = "Identity"
GROUP_GLOSSARY = "Glossary"
GROUP_FREQUENCY = "Frequency"
GROUP_PRONUNCIATION = "Pronunciation"
GROUP_SENTENCE = "Sentence"
GROUP_CONTEXT = "Context"
GROUP_KANJI = "Kanji"

GROUP_ORDER = (
    GROUP_IDENTITY,
    GROUP_GLOSSARY,
    GROUP_FREQUENCY,
    GROUP_PRONUNCIATION,
    GROUP_SENTENCE,
    GROUP_CONTEXT,
    GROUP_KANJI,
)

#: Card kinds a marker can apply to.
TERM = "term"
KANJI = "kanji"


@dataclass(frozen=True)
class Marker:
    name: str
    group: str
    description: str
    render: MarkerFunc
    #: Which entry types this marker means anything for. A kanji entry has no
    #: conjugation and a term has no stroke count; offering them anyway would produce
    #: fields that are always empty.
    applies_to: tuple[str, ...] = (TERM, KANJI)
    #: True when the marker emits HTML we generate ourselves (ruby, an SVG pitch
    #: graph). Everything else is escaped — glossary text comes from a dictionary and
    #: is not ours to trust.
    emits_html: bool = False


class MarkerRegistry:
    """Holds the markers. Ordered, because the editor's menu reads from it."""

    def __init__(self) -> None:
        self._markers: dict[str, Marker] = {}

    def add(self, marker: Marker) -> None:
        if marker.name in self._markers:
            raise ValueError(f"Duplicate marker: {marker.name}")
        self._markers[marker.name] = marker

    def register(
        self,
        name: str,
        group: str,
        description: str,
        applies_to: tuple[str, ...] = (TERM, KANJI),
        emits_html: bool = False,
    ) -> Callable[[MarkerFunc], MarkerFunc]:
        """Decorator form, so a marker's name sits directly above its implementation."""

        def decorate(func: MarkerFunc) -> MarkerFunc:
            self.add(
                Marker(
                    name=name,
                    group=group,
                    description=description,
                    render=func,
                    applies_to=applies_to,
                    emits_html=emits_html,
                )
            )
            return func

        return decorate

    def get(self, name: str) -> Marker | None:
        return self._markers.get(name)

    def names(self) -> tuple[str, ...]:
        return tuple(self._markers)

    def all(self) -> tuple[Marker, ...]:
        return tuple(self._markers.values())

    def for_entry_type(self, entry_type: str) -> tuple[Marker, ...]:
        return tuple(marker for marker in self._markers.values() if entry_type in marker.applies_to)

    def grouped(self, entry_type: str) -> tuple[tuple[str, tuple[Marker, ...]], ...]:
        """Markers by group, for the preset editor's insert menu."""

        available = self.for_entry_type(entry_type)
        groups = []
        for group in GROUP_ORDER:
            members = tuple(marker for marker in available if marker.group == group)
            if members:
                groups.append((group, members))
        return tuple(groups)
