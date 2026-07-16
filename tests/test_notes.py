"""Note field mapping and duplicate policy tests."""

from __future__ import annotations

import unittest
from typing import ClassVar

from anki_lookup.config import DEFAULT_CONFIG, runtime_config
from anki_lookup.notes.duplicates import duplicate_field, should_check_duplicates
from anki_lookup.notes.field_mapping import (
    is_configured,
    mapped_fields,
    mapping_pairs,
    markers_used,
    normalize_mapping,
)

MAPPING = [
    {"field": "Front", "value": "{expression}"},
    {"field": "Reading", "value": "{reading}"},
    {"field": "Back", "value": "{glossary}"},
    {"field": "Sentence", "value": "{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}"},
]


class FieldMappingTests(unittest.TestCase):
    def test_keeps_field_values_verbatim(self) -> None:
        self.assertEqual(normalize_mapping(MAPPING), MAPPING)

    def test_reports_the_fields_it_maps(self) -> None:
        self.assertEqual(mapped_fields(MAPPING), ["Front", "Reading", "Back", "Sentence"])

    def test_renders_as_field_value_pairs(self) -> None:
        self.assertEqual(mapping_pairs(MAPPING)[0], ("Front", "{expression}"))

    def test_reports_every_marker_used(self) -> None:
        # Found by regex before anything renders, which is what lets the expensive
        # markers be resolved up front rather than mid-render.
        self.assertEqual(
            markers_used(MAPPING),
            ("expression", "reading", "glossary", "cloze-prefix", "cloze-body", "cloze-suffix"),
        )

    def test_malformed_records_are_dropped(self) -> None:
        mapping = normalize_mapping(
            [
                {"field": "Front", "value": "{expression}"},
                {"field": "", "value": "{reading}"},
                {"value": "{glossary}"},
                {"field": 7, "value": "{reading}"},
                {"field": "NoValue"},
                "nonsense",
                None,
            ]
        )

        self.assertEqual(mapping, [{"field": "Front", "value": "{expression}"}])

    def test_a_field_mapped_twice_keeps_the_first(self) -> None:
        mapping = normalize_mapping(
            [
                {"field": "Front", "value": "{expression}"},
                {"field": "Front", "value": "{reading}"},
            ]
        )

        self.assertEqual(mapping, [{"field": "Front", "value": "{expression}"}])

    def test_a_mapping_that_is_not_a_list_is_ignored(self) -> None:
        self.assertEqual(normalize_mapping({"Front": "{expression}"}), [])
        self.assertEqual(normalize_mapping(None), [])

    def test_an_overlong_value_is_capped(self) -> None:
        mapping = normalize_mapping([{"field": "Front", "value": "x" * 5000}])

        self.assertEqual(len(mapping[0]["value"]), 1_000)

    def test_a_field_may_be_deliberately_blank(self) -> None:
        # Different from unmapped: the user chose to fill this one in themselves.
        self.assertEqual(
            normalize_mapping([{"field": "Notes", "value": ""}]),
            [{"field": "Notes", "value": ""}],
        )


class MigrationTests(unittest.TestCase):
    """0.4.0 named one source per field. Every source name is now a marker name."""

    def test_a_source_becomes_a_marker(self) -> None:
        self.assertEqual(
            normalize_mapping([{"field": "Front", "source": "expression"}]),
            [{"field": "Front", "value": "{expression}"}],
        )

    def test_the_old_empty_source_becomes_a_blank_value(self) -> None:
        self.assertEqual(
            normalize_mapping([{"field": "Notes", "source": "empty"}]),
            [{"field": "Notes", "value": ""}],
        )

    def test_a_whole_0_4_0_preset_migrates(self) -> None:
        old = [
            {"field": "Front", "source": "expression"},
            {"field": "Reading", "source": "reading"},
            {"field": "Back", "source": "definition"},
            {"field": "Sentence", "source": "sentence"},
        ]

        self.assertEqual(
            normalize_mapping(old),
            [
                {"field": "Front", "value": "{expression}"},
                {"field": "Reading", "value": "{reading}"},
                {"field": "Back", "value": "{definition}"},
                {"field": "Sentence", "value": "{sentence}"},
            ],
        )

    def test_a_new_value_wins_over_an_old_source(self) -> None:
        self.assertEqual(
            normalize_mapping([{"field": "Front", "value": "{glossary}", "source": "expression"}]),
            [{"field": "Front", "value": "{glossary}"}],
        )


class PresetValidityTests(unittest.TestCase):
    def _preset(self, **overrides: object) -> dict[str, object]:
        preset: dict[str, object] = {
            "deck_id": 1,
            "notetype_id": 2,
            "field_mapping": MAPPING,
        }
        preset.update(overrides)
        return preset

    def test_a_complete_preset_is_configured(self) -> None:
        self.assertTrue(is_configured(self._preset()))

    def test_an_incomplete_preset_is_not(self) -> None:
        # The popup disables Add on this rather than failing mid-review.
        self.assertFalse(is_configured(self._preset(deck_id=0)))
        self.assertFalse(is_configured(self._preset(notetype_id=0)))
        self.assertFalse(is_configured(self._preset(field_mapping=[])))
        self.assertFalse(is_configured(self._preset(deck_id="1")))
        self.assertFalse(is_configured({}))
        self.assertFalse(is_configured(None))

    def test_a_preset_of_only_blank_values_would_make_an_empty_note(self) -> None:
        self.assertFalse(is_configured(self._preset(field_mapping=[{"field": "F", "value": ""}])))


class DuplicatePolicyTests(unittest.TestCase):
    FIELDS: ClassVar[list[str]] = ["Front", "Back", "Sentence"]

    def test_defaults_to_the_first_field(self) -> None:
        # Anki's own definition of a duplicate, and what the browser's indicator uses.
        self.assertEqual(duplicate_field({}, self.FIELDS), "Front")

    def test_a_configured_field_wins(self) -> None:
        self.assertEqual(duplicate_field({"duplicate_field": "Back"}, self.FIELDS), "Back")

    def test_a_field_the_notetype_no_longer_has_falls_back(self) -> None:
        # Notetypes get edited. A preset naming a field that is gone should fall back,
        # not silently check nothing.
        self.assertEqual(duplicate_field({"duplicate_field": "Removed"}, self.FIELDS), "Front")

    def test_a_notetype_without_fields_has_nothing_to_check(self) -> None:
        self.assertEqual(duplicate_field({}, []), "")

    def test_an_empty_value_is_not_a_duplicate(self) -> None:
        # It would match every other note with an empty first field. That is an empty
        # note, which is a different problem.
        self.assertFalse(should_check_duplicates({}, ""))
        self.assertFalse(should_check_duplicates({}, "   "))

    def test_checking_can_be_turned_off(self) -> None:
        self.assertFalse(should_check_duplicates({"check_duplicates": False}, "食べる"))
        self.assertTrue(should_check_duplicates({"check_duplicates": True}, "食べる"))
        self.assertTrue(should_check_duplicates({}, "食べる"))


class NotesConfigTests(unittest.TestCase):
    def test_a_list_shaped_mapping_survives_a_config_round_trip(self) -> None:
        # THE regression guard for this feature. config._merge_known only merges keys
        # already in DEFAULT_CONFIG, and user-chosen field names cannot be predeclared.
        # A dict-shaped mapping would be erased here, and the user would experience it
        # as "my field mapping keeps resetting itself".
        config = runtime_config({"notes": {"field_mapping": MAPPING}})

        self.assertEqual(config["notes"]["field_mapping"], MAPPING)

    def test_a_dict_shaped_mapping_is_rejected_rather_than_half_kept(self) -> None:
        config = runtime_config({"notes": {"field_mapping": {"Front": "{expression}"}}})

        self.assertEqual(config["notes"]["field_mapping"], [])

    def test_a_0_4_0_preset_migrates_through_the_config(self) -> None:
        config = runtime_config(
            {
                "notes": {
                    "deck_id": 3,
                    "notetype_id": 4,
                    "field_mapping": [{"field": "Front", "source": "expression"}],
                }
            }
        )

        self.assertEqual(
            config["notes"]["field_mapping"], [{"field": "Front", "value": "{expression}"}]
        )
        self.assertTrue(config["notes"]["configured"])

    def test_the_default_preset_is_unconfigured(self) -> None:
        self.assertFalse(runtime_config({})["notes"]["configured"])

    def test_a_complete_preset_is_reported_configured_to_the_popup(self) -> None:
        config = runtime_config(
            {"notes": {"deck_id": 3, "notetype_id": 4, "field_mapping": MAPPING}}
        )

        self.assertTrue(config["notes"]["configured"])

    def test_identifiers_are_clamped(self) -> None:
        config = runtime_config({"notes": {"deck_id": -1, "notetype_id": "abc"}})

        self.assertEqual(config["notes"]["deck_id"], 0)
        self.assertEqual(config["notes"]["notetype_id"], 0)

    def test_tags_are_bounded_and_cleaned(self) -> None:
        config = runtime_config(
            {"notes": {"tags": ["  keep  ", "", "   ", 7, None, "x" * 500] + ["t"] * 40}}
        )

        tags = config["notes"]["tags"]
        self.assertEqual(tags[0], "keep")
        self.assertLessEqual(len(tags), 20)
        self.assertTrue(all(len(tag) <= 100 for tag in tags))

    def test_tags_that_are_not_a_list_fall_back(self) -> None:
        config = runtime_config({"notes": {"tags": "single"}})

        self.assertEqual(config["notes"]["tags"], DEFAULT_CONFIG["notes"]["tags"])

    def test_a_non_boolean_duplicate_flag_falls_back(self) -> None:
        config = runtime_config({"notes": {"check_duplicates": "yes"}})

        self.assertTrue(config["notes"]["check_duplicates"])


if __name__ == "__main__":
    unittest.main()
