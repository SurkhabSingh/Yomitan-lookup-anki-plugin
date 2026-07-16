"""Partition a sentence around the word that was scanned.

The invariant, and the only thing that matters here:

    prefix + body + suffix == sentence

That is what makes ``{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}`` reassemble the
card's own sentence with the word emphasised. Anything clever that breaks it produces
a card that quietly misquotes its source.
"""

from __future__ import annotations

from .context import Cloze


def build_cloze(sentence: str, offset: int, source_term: str) -> Cloze:
    """Split ``sentence`` around ``source_term`` at ``offset``.

    ``source_term`` is the surface form as it appeared on the card — 食べました, not
    the headword 食べる. The headword is what the dictionary matched; the sentence
    said something else, and the sentence is what we are quoting.

    Sliced by **codepoint**, not by Python's default string indexing over a str that
    the caller measured elsewhere: the offset arrives from JavaScript, where string
    indices are UTF-16 code units. Any character outside the BMP — an emoji, a rare
    kanji — is two units there and one here, so an offset computed in the popup and
    applied naively in Python would land mid-character and split the sentence in the
    wrong place. The caller converts; this function works in codepoints throughout.
    """

    if not sentence:
        return Cloze()

    characters = list(sentence)
    length = len(characters)

    start = max(0, min(offset, length))
    end = max(start, min(start + len(list(source_term)), length))

    return Cloze(
        sentence=sentence,
        prefix="".join(characters[:start]),
        body="".join(characters[start:end]),
        suffix="".join(characters[end:]),
    )


def utf16_offset_to_codepoint(sentence: str, utf16_offset: int) -> int:
    """Convert a JavaScript string index into a Python one.

    JavaScript measures strings in UTF-16 code units; Python measures them in
    codepoints. They agree until a character outside the BMP shows up, and then they
    drift by one per such character. The popup counts in the former and we slice in
    the latter, so somebody has to convert, and it is cheaper and safer to do it once
    here than to make every caller remember.
    """

    if utf16_offset <= 0:
        return 0

    units = 0
    for index, character in enumerate(sentence):
        if units >= utf16_offset:
            return index
        units += 2 if ord(character) > 0xFFFF else 1
    return len(sentence)
