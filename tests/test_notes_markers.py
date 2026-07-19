"""Marker rendering tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from anki_lookup.dictionary.models import FrequencyInfo, IpaInfo, LookupEntry, PitchAccentInfo
from anki_lookup.notes.markers import build_registry, context_for, kebab_case
from anki_lookup.notes.markers.cloze import build_cloze, utf16_offset_to_codepoint
from anki_lookup.notes.markers.context import Cloze
from anki_lookup.notes.markers.frequency import (
    NO_OCCURRENCE,
    NO_RANK,
    average_mean,
    frequency_numbers,
    harmonic_mean,
)
from anki_lookup.notes.markers.pitch import (
    japanese_morae,
    pitch_category,
    pitch_levels,
    render_graph,
)
from anki_lookup.notes.markers.registry import KANJI, TERM
from anki_lookup.notes.markers.render import render_field, used_markers

REGISTRY = build_registry()


def _term(**overrides: Any) -> LookupEntry:
    values: dict[str, Any] = {
        "expression": "食べる",
        "reading": "たべる",
        "dictionary": "JMdict",
        "term_tags": ("ichi", "news"),
        "definition_tags": ("v1", "vt"),
        "definitions": ("to eat", "to live on"),
        "match_type": "exact",
        "score": 1.0,
    }
    values.update(overrides)
    return LookupEntry(**values)


def _kanji(**overrides: Any) -> LookupEntry:
    values: dict[str, Any] = {
        "expression": "食",
        "reading": "ショク / く.う",
        "dictionary": "KANJIDIC",
        "term_tags": ("jouyou",),
        "definition_tags": (),
        "definitions": ("eat", "food"),
        "match_type": "kanji",
        "score": 0.0,
        "entry_type": "kanji",
        "metadata": (("strokes", "9"), ("grade", "3")),
        "onyomi": ("ショク", "ジキ"),
        "kunyomi": ("く.う", "た.べる"),
    }
    values.update(overrides)
    return LookupEntry(**values)


def _render(value: str, entry: LookupEntry | None = None, **kwargs: Any) -> str:
    context = context_for(entry or _term(), **kwargs)
    return render_field(value, context, REGISTRY)


class UsedMarkerTests(unittest.TestCase):
    def test_finds_every_marker_a_preset_mentions(self) -> None:
        # Knowable before rendering, because markers are tokens rather than a template
        # language. That is what lets audio be fetched up front.
        self.assertEqual(
            used_markers(("{expression} - {reading}", "{cloze-prefix}<b>{cloze-body}</b>")),
            ("expression", "reading", "cloze-prefix", "cloze-body"),
        )

    def test_reports_each_marker_once(self) -> None:
        self.assertEqual(used_markers(("{expression}", "{expression}")), ("expression",))

    def test_ignores_text_that_is_not_a_marker(self) -> None:
        self.assertEqual(used_markers(("plain text", "{{Anki Field}}", "{}")), ())

    def test_finds_a_marker_named_after_a_japanese_dictionary(self) -> None:
        # The pattern must be Unicode-aware or a dictionary called 旺文社国語辞典 is
        # simply unnameable, and most of a Japanese library gets no marker at all.
        self.assertEqual(
            used_markers(("{single-glossary-旺文社国語辞典-第十一版}",)),
            ("single-glossary-旺文社国語辞典-第十一版",),
        )

    def test_japanese_text_in_braces_is_harmless(self) -> None:
        # It matches the pattern, and that costs nothing: an unregistered marker is
        # left exactly as typed. This was the fear that drove an ASCII-only pattern,
        # and it was unfounded.
        self.assertEqual(_render("{食べる}"), "{食べる}")


class RenderTests(unittest.TestCase):
    def test_substitutes_a_marker(self) -> None:
        self.assertEqual(_render("{expression}"), "食べる")

    def test_literal_text_between_markers_survives(self) -> None:
        # The whole point of the format: this is how a card bolds the scanned word.
        cloze = Cloze(
            sentence="毎朝パンを食べました。",
            prefix="毎朝パンを",
            body="食べました",
            suffix="。",
        )

        self.assertEqual(
            _render("{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}", cloze=cloze),
            "毎朝パンを<b>食べました</b>。",
        )

    def test_an_unknown_marker_is_left_alone(self) -> None:
        # It may be an Anki template reference, or a brace the user wanted.
        self.assertEqual(_render("{not-a-marker}"), "{not-a-marker}")

    def test_dictionary_text_is_escaped(self) -> None:
        # Glossary text comes from a file somebody downloaded and lands in a note as
        # HTML. It is not ours to trust.
        entry = _term(definitions=("<script>alert(1)</script>",))

        rendered = _render("{glossary-first-brief}", entry)

        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_a_sentence_from_a_card_is_escaped(self) -> None:
        cloze = Cloze(sentence="<img src=x onerror=alert(1)>", prefix="", body="", suffix="")

        rendered = _render("{sentence}", cloze=cloze)

        self.assertNotIn("<img", rendered)

    def test_our_own_markup_is_not_escaped(self) -> None:
        # Only markers we wrote to emit HTML, from our own generator, pass through.
        entry = _term(pitch_accents=(PitchAccentInfo("NHK", "たべる", 2),))

        rendered = _render("{pitch-accent-graphs}", entry)

        self.assertIn("<svg", rendered)
        self.assertNotIn("&lt;svg", rendered)

    def test_a_marker_that_raises_names_itself_rather_than_failing_the_note(self) -> None:
        registry = build_registry()
        marker = registry.get("expression")
        assert marker is not None

        def explode(context: Any) -> str:
            raise RuntimeError("boom")

        registry._markers["expression"] = type(marker)(
            name=marker.name,
            group=marker.group,
            description=marker.description,
            render=explode,
        )

        rendered = render_field("{expression}", context_for(_term()), registry)

        self.assertEqual(rendered, "{expression-error}")

    def test_a_marker_that_does_not_apply_renders_empty(self) -> None:
        # A kanji has no conjugation. Better blank than an error in the field.
        self.assertEqual(_render("{conjugation}", _kanji()), "")

    def test_line_breaks_survive_into_the_field(self) -> None:
        # A note field is HTML, and HTML collapses a newline to a space. A monolingual
        # entry arrives as a headword line then a sense per line; escaping alone
        # flattened the lot onto one line, so the user saw the headword, thought the
        # marker had returned the word, and had to click into the field to find the
        # rest was even there.
        entry = _term(
            definitions=("た・べる【食べる】\n① 口に入れた食物をかむ。\n② 暮らしを立てる。",)
        )

        rendered = _render("{glossary-first-brief}", entry)

        self.assertIn("<br>", rendered)
        self.assertNotIn("\n", rendered)
        self.assertTrue(rendered.startswith("た・べる【食べる】<br>"))

    def test_numbered_senses_are_broken_onto_their_own_lines(self) -> None:
        rendered = _render("{glossary}")

        self.assertEqual(rendered, "(JMdict) 1. to eat<br>2. to live on")

    def test_carriage_returns_are_normalised_before_breaking(self) -> None:
        entry = _term(definitions=("first\r\nsecond\rthird",))

        rendered = _render("{glossary-first-brief}", entry)

        self.assertEqual(rendered, "first<br>second<br>third")

    def test_a_break_cannot_be_smuggled_in_through_dictionary_text(self) -> None:
        # The text is escaped first, so the <br> we insert afterwards is the only
        # markup that reaches the field.
        entry = _term(definitions=("<br>evil<script>alert(1)</script>",))

        rendered = _render("{glossary-first-brief}", entry)

        self.assertNotIn("<script>", rendered)
        self.assertEqual(rendered.count("<br>"), 0)
        self.assertIn("&lt;br&gt;", rendered)


class GlossaryTests(unittest.TestCase):
    def test_numbers_multiple_senses_and_attributes_them(self) -> None:
        # <br>, not a newline: the destination is a note field, which is HTML.
        self.assertEqual(_render("{glossary}"), "(JMdict) 1. to eat<br>2. to live on")

    def test_a_single_sense_is_not_numbered(self) -> None:
        self.assertEqual(_render("{glossary}", _term(definitions=("to eat",))), "(JMdict) to eat")

    def test_variants_differ_as_advertised(self) -> None:
        self.assertEqual(_render("{glossary-brief}"), "to eat; to live on")
        self.assertEqual(_render("{glossary-no-dictionary}"), "1. to eat<br>2. to live on")
        self.assertEqual(_render("{glossary-plain}"), "(JMdict) to eat<br>to live on")
        self.assertEqual(_render("{glossary-plain-no-dictionary}"), "to eat<br>to live on")
        self.assertEqual(_render("{glossary-first}"), "(JMdict) to eat")
        self.assertEqual(_render("{glossary-first-brief}"), "to eat")
        self.assertEqual(_render("{glossary-first-no-dictionary}"), "to eat")

    def test_an_entry_without_definitions_renders_empty(self) -> None:
        self.assertEqual(_render("{glossary}", _term(definitions=())), "")


class PerDictionaryMarkerTests(unittest.TestCase):
    def test_a_marker_is_registered_per_dictionary(self) -> None:
        registry = build_registry(("JMdict", "Daijirin"))

        self.assertIsNotNone(registry.get("single-glossary-jmdict"))
        self.assertIsNotNone(registry.get("single-glossary-daijirin"))

    def test_it_takes_definitions_from_that_dictionary_only(self) -> None:
        registry = build_registry(("JMdict", "Daijirin"))
        jmdict = _term(dictionary="JMdict", definitions=("to eat",))
        daijirin = _term(dictionary="Daijirin", definitions=("たべる の意",))
        context = context_for(jmdict, entries=(jmdict, daijirin))

        self.assertEqual(
            render_field("{single-glossary-daijirin}", context, registry), "たべる の意"
        )
        self.assertEqual(render_field("{single-glossary-jmdict}", context, registry), "to eat")

    def test_the_selected_entry_is_always_visible_to_aggregating_markers(self) -> None:
        # The single-glossary bug: note creation re-resolved by the segmenter fragment
        # (アンフ), which returned an unrelated dictionary's entries, while the entry
        # the user chose (アンフェア from 旺文社) was passed separately. single-glossary
        # iterated the re-resolved list, did not find 旺文社, and rendered empty — even
        # though the popup showed it. context_for now guarantees the chosen entry is in
        # the list, so the marker sees it whatever the re-resolve returned.
        registry = build_registry(("旺文社", "Pixiv"))
        chosen = _term(dictionary="旺文社", definitions=("アンフェア <unfair>",))
        unrelated = _term(dictionary="Pixiv", definitions=("a Pixiv tag",))
        context = context_for(chosen, entries=(unrelated,))

        self.assertIn(chosen, context.entries)
        # The angle brackets are escaped for the field, as all dictionary text is.
        self.assertEqual(
            render_field("{single-glossary-旺文社}", context, registry),
            "アンフェア &lt;unfair&gt;",
        )

    def test_a_dictionary_that_contributed_nothing_renders_empty(self) -> None:
        registry = build_registry(("JMdict", "Daijirin"))
        entry = _term(dictionary="JMdict")

        self.assertEqual(
            render_field("{single-glossary-daijirin}", context_for(entry), registry), ""
        )


class ContextInvariantTests(unittest.TestCase):
    def test_the_entry_is_in_entries_when_the_list_omits_it(self) -> None:
        entry = _term(dictionary="旺文社")
        context = context_for(entry, entries=(_term(dictionary="Pixiv"),))

        self.assertIn(entry, context.entries)

    def test_the_entry_is_not_duplicated_when_already_present(self) -> None:
        entry = _term(dictionary="旺文社")
        other = _term(dictionary="Pixiv")
        context = context_for(entry, entries=(other, entry))

        self.assertEqual(context.entries, (other, entry))

    def test_an_empty_list_becomes_just_the_entry(self) -> None:
        entry = _term()

        self.assertEqual(context_for(entry).entries, (entry,))

    def test_a_japanese_dictionary_gets_a_marker(self) -> None:
        # The bug this replaces: kebab_case was ASCII-only, so every CJK title reduced
        # to an empty string and build_registry skipped it. A Japanese library ended
        # up with no per-dictionary markers whatsoever.
        registry = build_registry(("旺文社国語辞典 第十一版", "大辞林", "JMdict"))

        self.assertEqual(kebab_case("旺文社国語辞典 第十一版"), "旺文社国語辞典-第十一版")
        self.assertEqual(kebab_case("大辞林"), "大辞林")
        self.assertIsNotNone(registry.get("single-glossary-旺文社国語辞典-第十一版"))
        self.assertIsNotNone(registry.get("single-glossary-大辞林"))
        self.assertIsNotNone(registry.get("single-glossary-jmdict"))

    def test_a_japanese_marker_renders_that_dictionarys_definitions(self) -> None:
        title = "旺文社国語辞典 第十一版"
        registry = build_registry((title, "JMdict"))
        ou = _term(dictionary=title, definitions=("物を口に入れてかむ。",))
        jmdict = _term(dictionary="JMdict", definitions=("to eat",))
        context = context_for(ou, entries=(ou, jmdict))

        self.assertEqual(
            render_field("{single-glossary-旺文社国語辞典-第十一版}", context, registry),
            "物を口に入れてかむ。",
        )

    def test_a_title_of_only_punctuation_is_skipped(self) -> None:
        # Nothing survives to name it with. Better no marker than one called
        # `single-glossary-` that the next such dictionary would collide with.
        registry = build_registry(("!!!", "JMdict"))

        self.assertEqual(kebab_case("!!!"), "")
        self.assertIsNone(registry.get("single-glossary-"))
        self.assertIsNotNone(registry.get("single-glossary-jmdict"))

    def test_underscores_and_ideographic_spaces_become_hyphens(self) -> None:
        self.assertEqual(kebab_case("My_Dict"), "my-dict")
        self.assertEqual(kebab_case("大辞泉　改訂版"), "大辞泉-改訂版")

    def test_titles_that_slugify_alike_do_not_overwrite_each_other(self) -> None:
        registry = build_registry(("My Dict", "my-dict"))

        self.assertEqual(len([n for n in registry.names() if n.startswith("single-glossary-")]), 1)

    def test_a_hostile_title_cannot_escape_into_the_marker_name(self) -> None:
        # A closure over the title has no quoting boundary to break out of, unlike
        # generating marker text with the title interpolated into it.
        registry = build_registry(("foo'}}{{evil",))

        self.assertIsNotNone(registry.get("single-glossary-foo-evil"))


class FrequencyTests(unittest.TestCase):
    def _freq(self, dictionary: str, value: float, mode: str, display: str = "") -> FrequencyInfo:
        return FrequencyInfo(dictionary, value, display, mode)

    def test_the_first_figure_per_dictionary_wins(self) -> None:
        # A dictionary listing one figure per reading would otherwise outweigh the
        # others purely for being more detailed.
        frequencies = (
            self._freq("A", 100, "rank-based"),
            self._freq("A", 900, "rank-based"),
            self._freq("B", 200, "rank-based"),
        )

        self.assertEqual(frequency_numbers(frequencies, "rank-based"), (100.0, 200.0))

    def test_modes_are_never_mixed(self) -> None:
        frequencies = (
            self._freq("A", 100, "rank-based"),
            self._freq("B", 5000, "occurrence-based"),
        )

        self.assertEqual(frequency_numbers(frequencies, "rank-based"), (100.0,))
        self.assertEqual(frequency_numbers(frequencies, "occurrence-based"), (5000.0,))

    def test_a_leading_number_in_the_display_value_is_preferred(self) -> None:
        frequencies = (self._freq("A", 99, "rank-based", "1234 (common)"),)

        self.assertEqual(frequency_numbers(frequencies, "rank-based"), (1234.0,))

    def test_harmonic_is_dominated_by_the_smallest_rank(self) -> None:
        # Why it is the default: if any dictionary says a word is common, it is. An
        # average lets one obscure dictionary bury an everyday word.
        numbers = (10.0, 50000.0)

        self.assertLess(harmonic_mean(numbers), 25.0)
        self.assertGreater(average_mean(numbers), 24000)

    def test_empty_input_reports_no_data(self) -> None:
        self.assertEqual(harmonic_mean(()), -1)
        self.assertEqual(average_mean(()), -1)

    def test_missing_data_sorts_last_in_both_directions(self) -> None:
        # Anki sorts fields as text. An empty field would sort first and put every
        # unknown word at the front of a frequency-ordered deck.
        entry = _term(frequencies=())

        self.assertEqual(_render("{frequency-harmonic-rank}", entry), NO_RANK)
        self.assertEqual(_render("{frequency-harmonic-occurrence}", entry), NO_OCCURRENCE)

    def test_renders_each_dictionary_attributed_on_its_own_line(self) -> None:
        entry = _term(
            frequencies=(
                FrequencyInfo("Innocent", 1204.0, "1204", "rank-based"),
                FrequencyInfo("BCCWJ", 5.0, "", "occurrence-based"),
            )
        )

        self.assertEqual(_render("{frequencies}", entry), "Innocent: 1204<br>BCCWJ: 5")


class PitchFixtureTests(unittest.TestCase):
    """Driven by the fixture the JavaScript implementation also reads.

    The popup renders pitch in the browser and note fields render it here. Two
    implementations of one algorithm; this is what holds them together.
    """

    def setUp(self) -> None:
        path = Path(__file__).parent / "fixtures" / "pitch_accents.json"
        self.fixture = json.loads(path.read_text(encoding="utf-8"))

    def test_morae_match_the_shared_fixture(self) -> None:
        for case in self.fixture["morae"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(list(japanese_morae(case["reading"])), case["expected"])

    def test_levels_match_the_shared_fixture(self) -> None:
        for case in self.fixture["levels"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    list(pitch_levels(case["moraCount"], case["position"])),
                    case["expected"],
                )

    def test_categories_match_the_shared_fixture(self) -> None:
        for case in self.fixture["categories"]:
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    pitch_category(case["moraCount"], case["position"]),
                    case["expected"],
                )

    def test_levels_always_cover_every_mora_plus_the_particle(self) -> None:
        # The particle is where heiban and odaka actually differ, so it is not
        # optional.
        for case in self.fixture["levels"]:
            with self.subTest(case=case["name"]):
                levels = pitch_levels(case["moraCount"], case["position"])
                self.assertEqual(len(levels), case["moraCount"] + 1)


class PitchRenderTests(unittest.TestCase):
    def test_the_graph_is_self_contained(self) -> None:
        # Anki has none of popup.css, so anything class-based would arrive unstyled.
        entry = _term(pitch_accents=(PitchAccentInfo("NHK", "たべる", 2),))

        svg = _render("{pitch-accent-graphs}", entry)

        self.assertIn("<svg", svg)
        self.assertIn("currentColor", svg)
        self.assertNotIn("class=", svg)

    def test_a_graph_is_drawn_per_accent(self) -> None:
        entry = _term(
            pitch_accents=(
                PitchAccentInfo("NHK", "たべる", 2),
                PitchAccentInfo("Daijisen", "たべる", 0),
            )
        )

        self.assertEqual(_render("{pitch-accent-graphs}", entry).count("<svg"), 2)

    def test_no_pitch_data_renders_nothing(self) -> None:
        self.assertEqual(render_graph(()), "")
        self.assertEqual(_render("{pitch-accent-positions}", _term()), "")

    def test_positions_and_categories_deduplicate(self) -> None:
        entry = _term(
            pitch_accents=(
                PitchAccentInfo("NHK", "たべる", 2),
                PitchAccentInfo("Daijisen", "たべる", 2),
            )
        )

        self.assertEqual(_render("{pitch-accent-positions}", entry), "2")
        self.assertEqual(_render("{pitch-accent-categories}", entry), "nakadaka")

    def test_a_reading_in_the_graph_is_escaped(self) -> None:
        entry = _term(pitch_accents=(PitchAccentInfo("X", "<b>", 1),))

        self.assertNotIn("<b>", _render("{pitch-accent-graphs}", entry))

    def test_ipa_renders(self) -> None:
        entry = _term(ipa=(IpaInfo("Wiktionary", "たべる", "ta̠be̞ɾɯ̟", ()),))

        self.assertEqual(_render("{phonetic-transcriptions}", entry), "ta̠be̞ɾɯ̟")


class ClozeTests(unittest.TestCase):
    def test_the_partition_always_reassembles_the_sentence(self) -> None:
        # The invariant. Break it and the card misquotes its own source.
        cases = [
            ("毎朝パンを食べました。", 5, "食べました"),
            ("I ate bread.", 2, "ate"),
            ("食べる", 0, "食べる"),
            ("なにも", 0, ""),
        ]
        for sentence, offset, term in cases:
            with self.subTest(sentence=sentence):
                cloze = build_cloze(sentence, offset, term)

                self.assertEqual(cloze.prefix + cloze.body + cloze.suffix, sentence)

    def test_the_body_is_the_form_that_appeared_not_the_headword(self) -> None:
        # 食べました was scanned; 食べる is what the dictionary matched. Quoting the
        # headword would make the sentence say something it did not.
        cloze = build_cloze("毎朝パンを食べました。", 5, "食べました")

        self.assertEqual(cloze.prefix, "毎朝パンを")
        self.assertEqual(cloze.body, "食べました")
        self.assertEqual(cloze.suffix, "。")

    def test_an_offset_past_the_end_does_not_raise(self) -> None:
        cloze = build_cloze("短い", 99, "x")

        self.assertEqual(cloze.prefix + cloze.body + cloze.suffix, "短い")

    def test_no_sentence_gives_empty_parts(self) -> None:
        cloze = build_cloze("", 0, "食べる")

        self.assertEqual((cloze.prefix, cloze.body, cloze.suffix), ("", "", ""))

    def test_astral_characters_do_not_corrupt_the_partition(self) -> None:
        # JavaScript counts UTF-16 units and Python counts codepoints. An emoji is two
        # units and one codepoint, so an unconverted offset lands mid-character.
        sentence = "🍞を食べる"
        utf16_offset = 3  # after "🍞を" in JavaScript terms

        codepoint_offset = utf16_offset_to_codepoint(sentence, utf16_offset)
        cloze = build_cloze(sentence, codepoint_offset, "食べる")

        self.assertEqual(codepoint_offset, 2)
        self.assertEqual(cloze.prefix, "🍞を")
        self.assertEqual(cloze.body, "食べる")
        self.assertEqual(cloze.prefix + cloze.body + cloze.suffix, sentence)

    def test_offset_conversion_agrees_with_python_for_plain_text(self) -> None:
        # No astral characters means the two measures agree, and conversion is a no-op.
        for offset in range(0, 5):
            self.assertEqual(utf16_offset_to_codepoint("hello", offset), offset)


class KanjiMarkerTests(unittest.TestCase):
    def test_kanji_readings_render_separately(self) -> None:
        self.assertEqual(_render("{onyomi}", _kanji()), "ショク ジキ")
        self.assertEqual(_render("{kunyomi}", _kanji()), "く.う た.べる")

    def test_character_and_stroke_count_render(self) -> None:
        self.assertEqual(_render("{character}", _kanji()), "食")
        self.assertEqual(_render("{stroke-count}", _kanji()), "9")

    def test_a_missing_stat_renders_empty(self) -> None:
        self.assertEqual(_render("{stroke-count}", _kanji(metadata=())), "")


class RegistryTests(unittest.TestCase):
    def test_the_menu_is_derived_from_the_registry(self) -> None:
        # The failure this prevents: a marker offered in the settings UI that renders
        # nothing, because the menu list and the implementations drifted apart.
        for marker in REGISTRY.all():
            with self.subTest(marker=marker.name):
                self.assertIsNotNone(REGISTRY.get(marker.name))

    def test_markers_are_grouped_for_the_editor(self) -> None:
        groups = dict(REGISTRY.grouped(TERM))

        self.assertIn("Glossary", groups)
        self.assertIn("Pronunciation", groups)

    def test_kanji_markers_are_not_offered_for_terms(self) -> None:
        term_markers = {marker.name for marker in REGISTRY.for_entry_type(TERM)}
        kanji_markers = {marker.name for marker in REGISTRY.for_entry_type(KANJI)}

        self.assertNotIn("stroke-count", term_markers)
        self.assertNotIn("onyomi", term_markers)
        self.assertNotIn("conjugation", kanji_markers)
        self.assertNotIn("pitch-accent-graphs", kanji_markers)

    def test_a_duplicate_marker_is_refused(self) -> None:
        registry = build_registry()
        marker = registry.get("expression")
        assert marker is not None

        with self.assertRaises(ValueError):
            registry.add(marker)

    def test_every_marker_has_a_description_for_the_menu(self) -> None:
        for marker in REGISTRY.all():
            with self.subTest(marker=marker.name):
                self.assertTrue(marker.description.strip())

    def test_no_image_or_browser_markers_are_offered(self) -> None:
        # Excluded on purpose: image support is out of scope, and the rest describe a
        # browser tab that does not exist inside Anki.
        names = set(REGISTRY.names())

        for absent in ("screenshot", "clipboard-image", "clipboard-text", "url", "document-title"):
            self.assertNotIn(absent, names)


if __name__ == "__main__":
    unittest.main()
