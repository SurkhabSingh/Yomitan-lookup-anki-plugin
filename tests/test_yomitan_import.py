"""Yomitan settings import tests.

Driven by hand-written fixture backups for each format era. Pure — no Anki.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from anki_lookup.notes.yomitan_import import (
    YomitanImportError,
    parse_backup,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ModernBackupTests(unittest.TestCase):
    """v64+ cardFormats."""

    def setUp(self) -> None:
        self.result = parse_backup(_load("yomitan_backup_v64.json"))

    def test_a_preset_is_produced_per_card_format(self) -> None:
        self.assertEqual([p.name for p in self.result.presets], ["Japanese vocab", "Kanji cards"])
        self.assertEqual([p.note_type for p in self.result.presets], ["term", "kanji"])

    def test_deck_and_model_come_across_as_names(self) -> None:
        vocab = self.result.presets[0]

        self.assertEqual(vocab.deck_name, "Mining::Japanese")
        self.assertEqual(vocab.model_name, "Lapis")

    def test_supported_fields_are_mapped_in_our_list_shape(self) -> None:
        vocab = self.result.presets[0]
        mapping = {r["field"]: r["value"] for r in vocab.field_mapping}

        self.assertEqual(mapping["Expression"], "{expression}")
        self.assertEqual(mapping["Sentence"], "{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}")

    def test_unsupported_markers_are_stripped_and_reported(self) -> None:
        # {audio}, {screenshot}, {url} have no marker here. Leaving them would print
        # the literal text on every card.
        vocab = self.result.presets[0]
        mapping = {r["field"]: r["value"] for r in vocab.field_mapping}

        self.assertEqual(mapping["Audio"], "")
        self.assertEqual(mapping["Screenshot"], "")
        # A supported marker beside an unsupported one keeps the supported one.
        self.assertEqual(mapping["Frequency"], "freq: {frequency-harmonic-rank}")

        dropped = {marker for _, marker in vocab.dropped_markers}
        self.assertEqual(dropped, {"audio", "screenshot", "url"})

    def test_duplicate_and_tag_settings_carry_across(self) -> None:
        vocab = self.result.presets[0]

        self.assertEqual(vocab.duplicate_scope, "deck")
        self.assertTrue(vocab.check_duplicates)
        self.assertEqual(vocab.tags, ["yomitan", "mined"])

    def test_kanji_fields_map(self) -> None:
        kanji = self.result.presets[1]
        mapping = {r["field"]: r["value"] for r in kanji.field_mapping}

        self.assertEqual(mapping["Onyomi"], "{onyomi}")
        self.assertEqual(mapping["Kunyomi"], "{kunyomi}")


class MidEraBackupTests(unittest.TestCase):
    """v59-63 terms/kanji with object fields."""

    def setUp(self) -> None:
        self.result = parse_backup(_load("yomitan_backup_v60.json"))

    def test_terms_and_kanji_both_become_presets(self) -> None:
        self.assertEqual([p.note_type for p in self.result.presets], ["term", "kanji"])

    def test_deck_model_and_fields_map(self) -> None:
        terms = self.result.presets[0]

        self.assertEqual(terms.deck_name, "Japanese")
        self.assertEqual(terms.model_name, "Basic")
        self.assertEqual(
            {r["field"]: r["value"] for r in terms.field_mapping}["Front"], "{expression}"
        )

    def test_check_for_duplicates_false_carries_across(self) -> None:
        self.assertFalse(self.result.presets[0].check_duplicates)


class OldBackupTests(unittest.TestCase):
    """Pre-v59: plain-string fields, and a non-zero profileCurrent."""

    def setUp(self) -> None:
        self.result = parse_backup(_load("yomitan_backup_v50.json"))

    def test_the_current_profile_is_used_not_the_first(self) -> None:
        # profileCurrent is 1; the first profile has the wrong deck.
        self.assertEqual(self.result.profile_name, "Active")
        self.assertEqual(self.result.presets[0].deck_name, "Vocab")

    def test_plain_string_field_values_are_read(self) -> None:
        terms = self.result.presets[0]
        mapping = {r["field"]: r["value"] for r in terms.field_mapping}

        self.assertEqual(mapping["Expression"], "{expression}")
        self.assertEqual(mapping["Reading"], "{reading}")

    def test_an_unsupported_marker_in_a_plain_string_is_stripped(self) -> None:
        terms = self.result.presets[0]
        mapping = {r["field"]: r["value"] for r in terms.field_mapping}

        self.assertEqual(mapping["Meaning"], "{glossary}")
        self.assertIn(("Meaning", "clipboard-text"), terms.dropped_markers)

    def test_deck_root_scope_maps_to_deck(self) -> None:
        # We have no deck-root; deck is the closest and the safer direction.
        self.assertEqual(self.result.presets[0].duplicate_scope, "deck")


class ErrorHandlingTests(unittest.TestCase):
    def test_invalid_json_is_rejected_clearly(self) -> None:
        with self.assertRaises(YomitanImportError) as caught:
            parse_backup("{ not json")
        self.assertIn("JSON", str(caught.exception))

    def test_a_non_yomitan_file_is_rejected(self) -> None:
        with self.assertRaises(YomitanImportError):
            parse_backup(json.dumps({"something": "else"}))

    def test_a_backup_with_no_anki_config_is_rejected(self) -> None:
        backup = {
            "options": {
                "profileCurrent": 0,
                "profiles": [{"name": "P", "options": {}}],
            }
        }
        with self.assertRaises(YomitanImportError):
            parse_backup(json.dumps(backup))

    def test_a_backup_with_anki_but_no_formats_is_rejected(self) -> None:
        backup = {
            "options": {
                "profileCurrent": 0,
                "profiles": [{"name": "P", "options": {"anki": {"cardFormats": []}}}],
            }
        }
        with self.assertRaises(YomitanImportError) as caught:
            parse_backup(json.dumps(backup))
        self.assertIn("note format", str(caught.exception).lower())

    def test_an_out_of_range_profile_index_falls_back_to_the_first(self) -> None:
        backup = {
            "options": {
                "profileCurrent": 99,
                "profiles": [
                    {
                        "name": "Only",
                        "options": {
                            "anki": {
                                "terms": {
                                    "deck": "D",
                                    "model": "M",
                                    "fields": {"Front": "{expression}"},
                                }
                            }
                        },
                    }
                ],
            }
        }
        result = parse_backup(json.dumps(backup))
        self.assertEqual(result.profile_name, "Only")


class SingleGlossaryTranslationTests(unittest.TestCase):
    def _parse_field(self, value: str) -> tuple[str, list[str]]:
        backup = {
            "options": {
                "profileCurrent": 0,
                "profiles": [
                    {
                        "name": "P",
                        "options": {
                            "anki": {
                                "terms": {
                                    "deck": "D",
                                    "model": "M",
                                    "fields": {"F": value},
                                }
                            }
                        },
                    }
                ],
            }
        }
        preset = parse_backup(json.dumps(backup)).presets[0]
        mapped = {r["field"]: r["value"] for r in preset.field_mapping}["F"]
        dropped = [m for f, m in preset.dropped_markers if f == "F"]
        return mapped, dropped

    def test_a_plain_single_glossary_marker_is_kept(self) -> None:
        value, dropped = self._parse_field("{single-glossary-daijirin}")

        self.assertEqual(value, "{single-glossary-daijirin}")
        self.assertEqual(dropped, [])

    def test_a_single_glossary_variant_we_do_not_offer_is_dropped(self) -> None:
        # We register only the plain per-dictionary marker, not -brief/-plain.
        value, dropped = self._parse_field("{single-glossary-daijirin-brief}")

        self.assertEqual(value, "")
        self.assertIn("single-glossary-daijirin-brief", dropped)

    def test_a_cjk_named_single_glossary_marker_is_kept(self) -> None:
        value, _ = self._parse_field("{single-glossary-旺文社国語辞典-第十一版}")

        self.assertEqual(value, "{single-glossary-旺文社国語辞典-第十一版}")


if __name__ == "__main__":
    unittest.main()
