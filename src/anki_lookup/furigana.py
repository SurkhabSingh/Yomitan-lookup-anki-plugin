"""Furigana rendering backed by imported dictionary readings."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from .dictionary.models import LookupEntry
from .dictionary.normalization import normalize_term
from .dictionary.service import DictionaryService

MAX_TERM_LENGTH = 20
FURIGANA_HOVER_STYLE = (
    "<style>"
    ".wonder-of-u-furigana ruby{cursor:help;}"
    ".wonder-of-u-furigana rt{visibility:hidden;opacity:0;transition:opacity 120ms ease;}"
    ".wonder-of-u-furigana ruby:hover rt,"
    ".wonder-of-u-furigana ruby:focus-within rt{visibility:visible;opacity:1;}"
    "@media (hover:none){.wonder-of-u-furigana ruby:active rt{visibility:visible;opacity:1;}}"
    "</style>"
)


@dataclass(frozen=True)
class FuriganaSegment:
    """A run of text, with the reading that belongs over it.

    An empty ``reading`` means plain text carrying no ruby. Segments exist so the one
    alignment pass can be rendered three ways — hover HTML for the desktop app, plain
    ruby for a note, and Anki's own ``食[た]べる`` bracket syntax — without three
    copies of the matching logic.
    """

    text: str
    reading: str = ""


def furigana_segments(text: str, service: DictionaryService) -> tuple[FuriganaSegment, ...]:
    """Align ``text`` against dictionary readings.

    Intentionally conservative: only exact dictionary expression matches containing
    kanji are annotated. Unknown text is passed through rather than guessed at.
    """

    if not text:
        return ()

    characters = list(text)
    exact_matches = _exact_matches_for_text(characters, service)
    segments: list[FuriganaSegment] = []
    index = 0

    while index < len(characters):
        if not _is_japanese_character(characters[index]):
            _append_plain(segments, characters[index])
            index += 1
            continue

        match = _longest_match_at(characters, index, exact_matches)
        if match is None:
            _append_plain(segments, characters[index])
            index += 1
            continue

        expression, reading = match
        segments.extend(_segments_for_expression(expression, reading))
        index += len(expression)

    return tuple(segments)


def render_furigana_html(text: str, service: DictionaryService) -> str:
    """Ruby HTML with the hover-to-reveal wrapper.

    The shape the desktop app's furigana bridge on 8766 consumes. Unchanged.
    """

    segments = furigana_segments(text, service)
    html, has_furigana = _render_ruby(segments)
    if not has_furigana:
        return html

    return f'{FURIGANA_HOVER_STYLE}<span class="wonder-of-u-furigana">{html}</span>'


def render_furigana_ruby(text: str, service: DictionaryService) -> str:
    """Ruby HTML for a note field.

    No hover wrapper: hiding the reading until moused over is right for reading along
    in the app, and wrong for a card whose whole purpose is to show it.
    """

    html, _ = _render_ruby(furigana_segments(text, service))
    return html


def render_furigana_plain(text: str, service: DictionaryService) -> str:
    """Anki's own furigana syntax: ``食[た]べる``.

    What ``{{furigana:Field}}`` in a card template reads, which means the card decides
    how to present it rather than having our markup baked in.
    """

    return _render_plain(furigana_segments(text, service))


def _append_plain(segments: list[FuriganaSegment], character: str) -> None:
    """Merge consecutive unannotated characters into one segment."""

    if segments and not segments[-1].reading:
        segments[-1] = FuriganaSegment(segments[-1].text + character)
        return
    segments.append(FuriganaSegment(character))


def _render_ruby(segments: tuple[FuriganaSegment, ...]) -> tuple[str, bool]:
    parts: list[str] = []
    has_furigana = False

    for segment in segments:
        if segment.reading:
            parts.append(_ruby_tag(segment.text, segment.reading))
            has_furigana = True
        else:
            parts.extend(_escape_plain_character(char) for char in segment.text)

    return "".join(parts), has_furigana


def _render_plain(segments: tuple[FuriganaSegment, ...]) -> str:
    """Render Anki bracket syntax.

    A reading applies to the text back to the previous space, so an annotated run needs
    a space in front of it to stop it swallowing whatever preceded it. The leading one
    is trimmed.
    """

    parts: list[str] = []
    for segment in segments:
        if segment.reading:
            parts.append(f" {segment.text}[{segment.reading}]")
        else:
            parts.append(segment.text)
    return "".join(parts).lstrip()


def _exact_matches_for_text(
    characters: list[str], service: DictionaryService
) -> dict[str, list[LookupEntry]]:
    candidates: list[str] = []
    seen: set[str] = set()

    for index, character in enumerate(characters):
        if not _is_japanese_character(character):
            continue

        for candidate in _japanese_candidates_at(characters, index):
            normalized = normalize_term(candidate)
            if normalized and normalized not in seen:
                candidates.append(candidate)
                seen.add(normalized)

    if not candidates:
        return {}

    return service.repository.search_exact_many(
        tuple(candidates), limit_per_term=5, include_kanji=False
    )


def _japanese_candidates_at(characters: list[str], start: int) -> tuple[str, ...]:
    end = start
    while end < len(characters) and _is_japanese_character(characters[end]):
        end += 1

    limit = min(MAX_TERM_LENGTH, end - start)
    return tuple("".join(characters[start : start + length]) for length in range(limit, 0, -1))


def _longest_match_at(
    characters: list[str], start: int, exact_matches: dict[str, list[LookupEntry]]
) -> tuple[str, str] | None:
    for candidate in _japanese_candidates_at(characters, start):
        if not _contains_kanji(candidate):
            continue

        for entry in exact_matches.get(normalize_term(candidate), []):
            if _usable_reading(candidate, entry):
                return candidate, entry.reading

    return None


def _usable_reading(expression: str, entry: LookupEntry) -> bool:
    return (
        normalize_term(entry.expression) == normalize_term(expression)
        and bool(entry.reading)
        and normalize_term(entry.reading) != normalize_term(expression)
        and _contains_kana(entry.reading)
    )


def _segments_for_expression(expression: str, reading: str) -> tuple[FuriganaSegment, ...]:
    """Trim shared kana off both ends so the ruby sits only over the kanji.

    食べる read たべる annotates 食 with た, not the whole word with the whole reading:
    the trailing べる is already written out, and repeating it above is noise.
    """

    prefix_length = _matching_kana_prefix_length(expression, reading)
    suffix_length = _matching_kana_suffix_length(expression, reading, prefix_length)

    expression_core_end = len(expression) - suffix_length
    reading_core_end = len(reading) - suffix_length
    expression_core = expression[prefix_length:expression_core_end]
    reading_core = reading[prefix_length:reading_core_end]

    if not expression_core or not reading_core or not _contains_kanji(expression_core):
        return (FuriganaSegment(expression, reading),)

    segments: list[FuriganaSegment] = []
    if prefix_length:
        segments.append(FuriganaSegment(expression[:prefix_length]))
    segments.append(FuriganaSegment(expression_core, reading_core))
    if expression[expression_core_end:]:
        segments.append(FuriganaSegment(expression[expression_core_end:]))
    return tuple(segments)


def _ruby_tag(expression: str, reading: str) -> str:
    return f"<ruby>{escape(expression)}<rt>{escape(reading)}</rt></ruby>"


def _matching_kana_prefix_length(expression: str, reading: str) -> int:
    length = 0
    while (
        length < len(expression)
        and length < len(reading)
        and _is_kana(expression[length])
        and expression[length] == reading[length]
    ):
        length += 1
    return length


def _matching_kana_suffix_length(expression: str, reading: str, prefix_length: int) -> int:
    length = 0
    max_length = min(len(expression), len(reading)) - prefix_length
    while (
        length < max_length
        and _is_kana(expression[len(expression) - length - 1])
        and expression[len(expression) - length - 1] == reading[len(reading) - length - 1]
    ):
        length += 1
    return length


def _escape_plain_character(character: str) -> str:
    return "<br>" if character == "\n" else escape(character)


def _is_japanese_character(character: str) -> bool:
    return _is_kana(character) or _is_kanji(character) or character in {"々", "〆", "ヶ", "ー"}


def _contains_kanji(value: str) -> bool:
    return any(_is_kanji(character) for character in value)


def _contains_kana(value: str) -> bool:
    return any(_is_kana(character) for character in value)


def _is_kana(character: str) -> bool:
    if not character:
        return False
    codepoint = ord(character)
    return 0x3040 <= codepoint <= 0x30FF


def _is_kanji(character: str) -> bool:
    if not character:
        return False
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )
