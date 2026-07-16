"""Turn a field value into a note field.

A field value is text with ``{marker}`` tokens: ``{cloze-prefix}<b>{cloze-body}</b>``
``{cloze-suffix}`` renders the sentence with the scanned word bolded. Text between
markers is passed through untouched — it is the user's own HTML, typed into their own
preset.

**Escaping is the trust boundary here.** Glossary text comes out of a dictionary file
somebody downloaded; a sentence comes off a card. Neither is ours, and both land in a
note as HTML. So every marker's output is escaped unless the marker is one we wrote to
emit markup — ruby, an SVG pitch graph — from our own generator.
"""

from __future__ import annotations

import re
from html import escape

from .context import NoteContext
from .registry import MarkerRegistry

#: Marker names are word characters and hyphens, and **Unicode-aware**: a dictionary
#: called 旺文社国語辞典 第十一版 has to be nameable, and it gets the marker
#: ``{single-glossary-旺文社国語辞典-第十一版}``. An ASCII-only pattern silently
#: excluded every CJK-titled dictionary from having a marker at all — which is most of
#: a Japanese library.
#:
#: Matching a stray ``{食べる}`` in a field costs nothing: an unregistered marker is
#: left exactly as typed (see :func:`render_field`), because it may well be an Anki
#: template reference or simply a brace the user wanted.
MARKER_PATTERN = re.compile(r"\{([\w-]+)\}", re.UNICODE)

#: Rendered when a marker exists but blows up. Better in the field than a half-written
#: note or an exception mid-review — the user can see which marker to look at.
ERROR_TEMPLATE = "{{{name}-error}}"


def used_markers(field_values: tuple[str, ...]) -> tuple[str, ...]:
    """Every marker name a preset mentions, in first-seen order.

    Knowable statically, because markers are tokens rather than a template language
    with conditionals in it. That is what lets the caller resolve expensive things —
    audio — before rendering rather than discovering mid-render that it needs them.
    """

    seen: list[str] = []
    for value in field_values:
        for match in MARKER_PATTERN.finditer(value):
            name = match.group(1)
            if name not in seen:
                seen.append(name)
    return tuple(seen)


def render_field(value: str, context: NoteContext, registry: MarkerRegistry) -> str:
    """Substitute every known marker in one field value."""

    def substitute(match: re.Match[str]) -> str:
        name = match.group(1)
        marker = registry.get(name)
        if marker is None:
            # Not ours. Leave it exactly as typed: it may be an Anki template
            # reference, or simply a brace the user wanted.
            return match.group(0)
        if context.entry.entry_type not in marker.applies_to:
            return ""
        try:
            rendered = marker.render(context)
        except Exception:
            return ERROR_TEMPLATE.format(name=name)
        if marker.emits_html:
            return rendered
        return escape_for_field(rendered)

    return MARKER_PATTERN.sub(substitute, value)


def escape_for_field(text: str) -> str:
    """Escape plain text for a note field, keeping its line structure.

    **A note field is HTML**, and HTML collapses a newline to a space. Markers produce
    plain text with real newlines in it — a dictionary entry arrives as a headword
    line, then a numbered sense per line — so escaping alone flattens a whole entry
    onto one line. The user sees the headword and nothing else, and has to click into
    the field to discover the rest is even there.

    So line breaks become ``<br>``: the text is escaped first, meaning the tag we
    insert afterwards is the only markup that can reach the field.
    """

    escaped = escape(text, quote=False)
    return escaped.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def render_fields(
    mapping: tuple[tuple[str, str], ...],
    context: NoteContext,
    registry: MarkerRegistry,
) -> dict[str, str]:
    """Render ``(field name, field value)`` pairs into note fields."""

    return {field: render_field(value, context, registry) for field, value in mapping}
