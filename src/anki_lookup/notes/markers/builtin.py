"""Every marker the add-on ships.

Each is a pure function of a :class:`NoteContext`. The preset editor's insert menu is
generated from this registry, so a marker cannot be offered without existing and
cannot exist without being offered.

Absent on purpose: screenshots, clipboard contents, page URLs and document titles.
The first two are image support, which this add-on does not do; the rest describe a
browser tab, and there isn't one.
"""

from __future__ import annotations

from ...dictionary.models import LookupEntry
from . import frequency as freq
from . import pitch as pitch_render
from .context import NoteContext
from .registry import (
    GROUP_CONTEXT,
    GROUP_FREQUENCY,
    GROUP_GLOSSARY,
    GROUP_IDENTITY,
    GROUP_KANJI,
    GROUP_PRONUNCIATION,
    GROUP_SENTENCE,
    KANJI,
    TERM,
    MarkerRegistry,
)

registry = MarkerRegistry()
register = registry.register


# -- identity -----------------------------------------------------------------


@register("expression", GROUP_IDENTITY, "The headword, as the dictionary spells it.")
def _expression(context: NoteContext) -> str:
    return context.entry.expression


@register("reading", GROUP_IDENTITY, "The headword's reading.", applies_to=(TERM,))
def _reading(context: NoteContext) -> str:
    return context.entry.reading


@register("dictionary", GROUP_IDENTITY, "Name of the dictionary the entry came from.")
def _dictionary(context: NoteContext) -> str:
    return context.entry.dictionary


@register("tags", GROUP_IDENTITY, "The entry's dictionary tags.")
def _tags(context: NoteContext) -> str:
    return " ".join(context.entry.term_tags)


@register(
    "part-of-speech",
    GROUP_IDENTITY,
    "Part-of-speech tags, where the dictionary supplies them.",
    applies_to=(TERM,),
)
def _part_of_speech(context: NoteContext) -> str:
    return " ".join(context.entry.definition_tags)


@register(
    "conjugation",
    GROUP_IDENTITY,
    "How the scanned form was derived, e.g. 食べました ← polite past.",
    applies_to=(TERM,),
)
def _conjugation(context: NoteContext) -> str:
    return " ← ".join(context.entry.inflection_reasons)


# -- glossary -----------------------------------------------------------------
#
# Eight variants of one idea, parameterised rather than copied: numbered or not,
# attributed or not, all senses or only the first.


def _glossary_text(
    entry: LookupEntry,
    numbered: bool,
    with_dictionary: bool,
    first_only: bool,
) -> str:
    definitions = entry.definitions[:1] if first_only else entry.definitions
    if not definitions:
        return ""

    if numbered and len(definitions) > 1:
        body = "\n".join(
            f"{index}. {definition}" for index, definition in enumerate(definitions, 1)
        )
    else:
        body = "\n".join(definitions)

    if with_dictionary and entry.dictionary:
        return f"({entry.dictionary}) {body}"
    return body


@register("glossary", GROUP_GLOSSARY, "All senses, numbered, attributed.")
def _glossary(context: NoteContext) -> str:
    return _glossary_text(context.entry, numbered=True, with_dictionary=True, first_only=False)


@register("glossary-no-dictionary", GROUP_GLOSSARY, "All senses, numbered, unattributed.")
def _glossary_no_dictionary(context: NoteContext) -> str:
    return _glossary_text(context.entry, numbered=True, with_dictionary=False, first_only=False)


@register("glossary-brief", GROUP_GLOSSARY, "All senses on one line.")
def _glossary_brief(context: NoteContext) -> str:
    return "; ".join(context.entry.definitions)


@register("glossary-plain", GROUP_GLOSSARY, "All senses, unnumbered, attributed.")
def _glossary_plain(context: NoteContext) -> str:
    return _glossary_text(context.entry, numbered=False, with_dictionary=True, first_only=False)


@register(
    "glossary-plain-no-dictionary",
    GROUP_GLOSSARY,
    "All senses, unnumbered, unattributed.",
)
def _glossary_plain_no_dictionary(context: NoteContext) -> str:
    return _glossary_text(context.entry, numbered=False, with_dictionary=False, first_only=False)


@register("glossary-first", GROUP_GLOSSARY, "The first sense only, attributed.")
def _glossary_first(context: NoteContext) -> str:
    return _glossary_text(context.entry, numbered=False, with_dictionary=True, first_only=True)


@register("glossary-first-brief", GROUP_GLOSSARY, "The first sense only, bare.")
def _glossary_first_brief(context: NoteContext) -> str:
    return context.entry.definitions[0] if context.entry.definitions else ""


@register(
    "glossary-first-no-dictionary",
    GROUP_GLOSSARY,
    "The first sense only, unattributed.",
)
def _glossary_first_no_dictionary(context: NoteContext) -> str:
    return _glossary_text(context.entry, numbered=False, with_dictionary=False, first_only=True)


# -- frequency ----------------------------------------------------------------


@register("frequencies", GROUP_FREQUENCY, "Every dictionary's frequency, attributed.")
def _frequencies(context: NoteContext) -> str:
    return freq.render_list(context.entry.frequencies)


@register(
    "frequency-harmonic-rank",
    GROUP_FREQUENCY,
    "Harmonic mean of rank-based frequencies. The best default for sorting.",
)
def _frequency_harmonic_rank(context: NoteContext) -> str:
    return freq.render_aggregate(context.entry.frequencies, freq.RANK_MODE, harmonic=True)


@register(
    "frequency-average-rank",
    GROUP_FREQUENCY,
    "Arithmetic mean of rank-based frequencies.",
)
def _frequency_average_rank(context: NoteContext) -> str:
    return freq.render_aggregate(context.entry.frequencies, freq.RANK_MODE, harmonic=False)


@register(
    "frequency-harmonic-occurrence",
    GROUP_FREQUENCY,
    "Harmonic mean of occurrence-based frequencies.",
)
def _frequency_harmonic_occurrence(context: NoteContext) -> str:
    return freq.render_aggregate(context.entry.frequencies, freq.OCCURRENCE_MODE, harmonic=True)


@register(
    "frequency-average-occurrence",
    GROUP_FREQUENCY,
    "Arithmetic mean of occurrence-based frequencies.",
)
def _frequency_average_occurrence(context: NoteContext) -> str:
    return freq.render_aggregate(context.entry.frequencies, freq.OCCURRENCE_MODE, harmonic=False)


# -- pronunciation ------------------------------------------------------------


@register(
    "pitch-accents",
    GROUP_PRONUNCIATION,
    "Pitch as marked-up text.",
    applies_to=(TERM,),
    emits_html=True,
)
def _pitch_accents(context: NoteContext) -> str:
    return pitch_render.render_text(context.entry.pitch_accents)


@register(
    "pitch-accent-graphs",
    GROUP_PRONUNCIATION,
    "Pitch as an SVG contour.",
    applies_to=(TERM,),
    emits_html=True,
)
def _pitch_accent_graphs(context: NoteContext) -> str:
    return pitch_render.render_graph(context.entry.pitch_accents)


@register(
    "pitch-accent-positions",
    GROUP_PRONUNCIATION,
    "Downstep numbers only.",
    applies_to=(TERM,),
)
def _pitch_accent_positions(context: NoteContext) -> str:
    return pitch_render.render_positions(context.entry.pitch_accents)


@register(
    "pitch-accent-categories",
    GROUP_PRONUNCIATION,
    "heiban / atamadaka / nakadaka / odaka. Useful as a tag or for styling.",
    applies_to=(TERM,),
)
def _pitch_accent_categories(context: NoteContext) -> str:
    return pitch_render.render_categories(context.entry.pitch_accents)


@register(
    "phonetic-transcriptions",
    GROUP_PRONUNCIATION,
    "IPA, where a dictionary supplies it.",
    applies_to=(TERM,),
)
def _phonetic_transcriptions(context: NoteContext) -> str:
    return pitch_render.render_ipa(tuple(item.transcription for item in context.entry.ipa))


# -- sentence and cloze -------------------------------------------------------


@register("sentence", GROUP_SENTENCE, "The sentence the word appeared in.")
def _sentence(context: NoteContext) -> str:
    return context.cloze.sentence


@register(
    "cloze-prefix",
    GROUP_SENTENCE,
    "The sentence before the scanned word.",
)
def _cloze_prefix(context: NoteContext) -> str:
    return context.cloze.prefix


@register(
    "cloze-body",
    GROUP_SENTENCE,
    "The scanned word as it appeared, e.g. 食べました rather than 食べる.",
)
def _cloze_body(context: NoteContext) -> str:
    return context.cloze.body


@register("cloze-suffix", GROUP_SENTENCE, "The sentence after the scanned word.")
def _cloze_suffix(context: NoteContext) -> str:
    return context.cloze.suffix


@register(
    "cloze-body-kana",
    GROUP_SENTENCE,
    "The scanned word in kana, where a reading is known.",
    applies_to=(TERM,),
)
def _cloze_body_kana(context: NoteContext) -> str:
    return context.cloze.body_kana or context.cloze.body


@register(
    "furigana",
    GROUP_SENTENCE,
    "The headword with ruby over the kanji.",
    applies_to=(TERM,),
    emits_html=True,
)
def _furigana(context: NoteContext) -> str:
    return context.media_value("furigana")


@register(
    "furigana-plain",
    GROUP_SENTENCE,
    "The headword in Anki's own 食[た]べる syntax, for {{furigana:Field}}.",
    applies_to=(TERM,),
)
def _furigana_plain(context: NoteContext) -> str:
    return context.media_value("furigana-plain")


@register(
    "sentence-furigana",
    GROUP_SENTENCE,
    "The whole sentence with ruby over its kanji.",
    emits_html=True,
)
def _sentence_furigana(context: NoteContext) -> str:
    return context.media_value("sentence-furigana")


# -- context ------------------------------------------------------------------


@register("selected-text", GROUP_CONTEXT, "Exactly what was scanned, before lookup.")
def _selected_text(context: NoteContext) -> str:
    return context.source_term or context.entry.expression


@register("translation", GROUP_CONTEXT, "The sentence's translation, if one was fetched.")
def _translation(context: NoteContext) -> str:
    return context.translation


@register("source-deck", GROUP_CONTEXT, "The deck being reviewed when the note was made.")
def _source_deck(context: NoteContext) -> str:
    return context.source_deck


# -- kanji --------------------------------------------------------------------


@register("character", GROUP_KANJI, "The kanji itself.", applies_to=(KANJI,))
def _character(context: NoteContext) -> str:
    return context.entry.expression


@register("onyomi", GROUP_KANJI, "On'yomi readings.", applies_to=(KANJI,))
def _onyomi(context: NoteContext) -> str:
    return " ".join(context.entry.onyomi)


@register("kunyomi", GROUP_KANJI, "Kun'yomi readings.", applies_to=(KANJI,))
def _kunyomi(context: NoteContext) -> str:
    return " ".join(context.entry.kunyomi)


@register(
    "stroke-count",
    GROUP_KANJI,
    "Stroke count, where the dictionary supplies it.",
    applies_to=(KANJI,),
)
def _stroke_count(context: NoteContext) -> str:
    return context.metadata_value("strokes")
