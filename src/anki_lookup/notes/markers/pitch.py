"""Japanese pitch accent, rendered for a note field.

A second implementation of logic that already exists in ``web/scanner-core.js``, and
that is a real cost. It is paid because the alternative is worse: the popup renders
pitch in the browser, but a note field has to be built in Python, and asking the
webview to hand us HTML would mean trusting markup from the page and shipping it into
the user's collection.

``tests/fixtures/pitch_accents.json`` drives both implementations. It is the only
thing keeping them in step, and it is not optional.

Everything here carries **inline styles**. Anki has none of ``popup.css``, so anything
relying on a class would arrive unstyled in the user's cards.
"""

from __future__ import annotations

import re
from html import escape

from ...dictionary.models import PitchAccentInfo

#: Small kana attach to the preceding mora: きょ is one mora, not two. Pitch is defined
#: over morae, so this is what the graph counts.
SMALL_KANA = "ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ"

_HL_PATTERN = re.compile(r"^[HL]+$")

# Pitch categories, the classical taxonomy.
HEIBAN = "heiban"
ATAMADAKA = "atamadaka"
NAKADAKA = "nakadaka"
ODAKA = "odaka"


def japanese_morae(reading: str) -> tuple[str, ...]:
    """Split a reading into morae. Mirrors ``japaneseMorae`` in scanner-core.js."""

    morae: list[str] = []
    for character in reading or "":
        if character in SMALL_KANA and morae:
            morae[-1] += character
        else:
            morae.append(character)
    return tuple(morae)


def pitch_levels(mora_count: int, position: int | str) -> tuple[bool, ...]:
    """High/low for each mora plus the following particle.

    Mirrors ``pitchLevels`` in scanner-core.js. Returns ``mora_count + 1`` values: the
    last is the particle after the word, which is where a word's accent actually
    becomes audible — odaka and heiban are identical across the word itself and differ
    only there.

    ``position`` is either an explicit pattern like ``"LHHH"`` or a downstep index.
    """

    count = max(0, mora_count)

    if isinstance(position, str) and _HL_PATTERN.match(position):
        values = [level == "H" for level in position]
        while len(values) < count + 1:
            values.append(values[-1] if values else False)
        return tuple(values[: count + 1])

    downstep = position if isinstance(position, int) and not isinstance(position, bool) else 0
    downstep = max(0, downstep)

    levels: list[bool] = []
    for index in range(count + 1):
        if downstep == 0:
            levels.append(index > 0)
        elif downstep == 1:
            levels.append(index == 0)
        else:
            levels.append(0 < index < downstep)
    return tuple(levels)


def pitch_category(mora_count: int, position: int | str) -> str:
    """Classify an accent. Empty when the pattern is not a plain downstep."""

    if not isinstance(position, int) or isinstance(position, bool):
        return ""
    if position == 0:
        return HEIBAN
    if position == 1:
        return ATAMADAKA
    if position >= mora_count:
        return ODAKA
    return NAKADAKA


def render_positions(pitch_accents: tuple[PitchAccentInfo, ...]) -> str:
    """Just the downstep numbers, deduplicated."""

    seen: list[str] = []
    for item in pitch_accents:
        if not isinstance(item.position, int) or isinstance(item.position, bool):
            continue
        value = str(item.position)
        if value not in seen:
            seen.append(value)
    return ", ".join(seen)


def render_categories(pitch_accents: tuple[PitchAccentInfo, ...]) -> str:
    """Category names, deduplicated. Useful as note tags or for styling a card."""

    seen: list[str] = []
    for item in pitch_accents:
        category = pitch_category(len(japanese_morae(item.reading)), item.position)
        if category and category not in seen:
            seen.append(category)
    return ", ".join(seen)


def render_text(pitch_accents: tuple[PitchAccentInfo, ...]) -> str:
    """The reading with an overline over the high morae and a downstep mark.

    Inline-styled spans rather than an SVG: it copies as text, scales with the card's
    font, and needs nothing from a stylesheet.
    """

    parts: list[str] = []
    for item in pitch_accents:
        rendered = _render_one_text(item)
        if rendered:
            parts.append(rendered)
    return "".join(f"<div>{part}</div>" for part in parts)


def _render_one_text(item: PitchAccentInfo) -> str:
    morae = japanese_morae(item.reading)
    if not morae:
        return ""
    levels = pitch_levels(len(morae), item.position)

    spans: list[str] = []
    for index, mora in enumerate(morae):
        high = levels[index]
        drops = high and not levels[index + 1]
        style = "display:inline-block;"
        if high:
            style += "border-top:1px solid currentColor;"
        if drops:
            style += "border-right:1px solid currentColor;"
        spans.append(f'<span style="{style}">{escape(mora)}</span>')

    return "".join(spans)


def render_graph(pitch_accents: tuple[PitchAccentInfo, ...]) -> str:
    """An SVG pitch contour per accent."""

    graphs = [_render_one_graph(item) for item in pitch_accents]
    return "".join(graph for graph in graphs if graph)


def _render_one_graph(item: PitchAccentInfo) -> str:
    morae = japanese_morae(item.reading)
    if not morae:
        return ""

    levels = pitch_levels(len(morae), item.position)
    step = 35
    width = step * (len(morae) + 1)
    height = 60
    high_y = 16
    low_y = 40

    def y_for(index: int) -> int:
        return high_y if levels[index] else low_y

    points = [(step // 2 + step * index, y_for(index)) for index in range(len(levels))]

    line = " ".join(f"{x},{y}" for x, y in points)
    parts = [
        f'<svg viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'xmlns="http://www.w3.org/2000/svg" style="vertical-align:middle;">',
        f'<polyline points="{line}" fill="none" stroke="currentColor" stroke-width="1.5" />',
    ]

    for index, (x, y) in enumerate(points):
        # The final dot is the particle after the word, not part of it: drawn hollow
        # because it is where the accent is heard rather than something the word says.
        particle = index == len(points) - 1
        fill = "none" if particle else "currentColor"
        parts.append(
            f'<circle cx="{x}" cy="{y}" r="4" fill="{fill}" stroke="currentColor" '
            f'stroke-width="1.5" />'
        )
        if not particle:
            parts.append(
                f'<text x="{x}" y="{height - 4}" text-anchor="middle" '
                f'font-size="15" fill="currentColor">{escape(morae[index])}</text>'
            )

    parts.append("</svg>")
    return "".join(parts)


def render_ipa(reading_items: tuple[str, ...]) -> str:
    return ", ".join(item for item in reading_items if item)
