"""Furigana rendering backed by imported dictionary readings."""

from __future__ import annotations

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


def render_furigana_html(text: str, service: DictionaryService) -> str:
    """Return HTML with Japanese dictionary matches wrapped in ruby markup.

    This intentionally stays conservative: only exact dictionary expression
    matches containing kanji are annotated. Unknown text is escaped and left
    unchanged instead of guessing readings.
    """

    if not text:
        return ""

    characters = list(text)
    exact_matches = _exact_matches_for_text(characters, service)
    rendered: list[str] = []
    has_furigana = False
    index = 0

    while index < len(characters):
        if not _is_japanese_character(characters[index]):
            rendered.append(_escape_plain_character(characters[index]))
            index += 1
            continue

        match = _longest_match_at(characters, index, exact_matches)
        if match is None:
            rendered.append(_escape_plain_character(characters[index]))
            index += 1
            continue

        expression, reading = match
        rendered.append(_ruby_for_expression(expression, reading))
        has_furigana = True
        index += len(expression)

    html = "".join(rendered)
    if not has_furigana:
        return html

    return f'{FURIGANA_HOVER_STYLE}<span class="wonder-of-u-furigana">{html}</span>'


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

    return service.repository.search_exact_many(candidates, limit_per_term=5, include_kanji=False)


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


def _ruby_for_expression(expression: str, reading: str) -> str:
    prefix_length = _matching_kana_prefix_length(expression, reading)
    suffix_length = _matching_kana_suffix_length(expression, reading, prefix_length)

    expression_core_end = len(expression) - suffix_length
    reading_core_end = len(reading) - suffix_length
    expression_core = expression[prefix_length:expression_core_end]
    reading_core = reading[prefix_length:reading_core_end]

    if not expression_core or not reading_core or not _contains_kanji(expression_core):
        return _ruby_tag(expression, reading)

    return (
        escape(expression[:prefix_length])
        + _ruby_tag(expression_core, reading_core)
        + escape(expression[expression_core_end:])
    )


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
