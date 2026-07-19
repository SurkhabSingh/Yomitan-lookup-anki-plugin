"""Recommended note type tests.

The mapping table and idempotency policy are pure; the Anki create call is covered by
a fake collection standing in for ``col.models`` so it stays out of the Anki-dependent
gate. The real create is exercised manually against Anki 25.9.4.
"""

from __future__ import annotations

import unittest
from typing import Any

from anki_lookup.notes.field_mapping import normalize_mapping
from anki_lookup.notes.markers import build_registry
from anki_lookup.notes.recommended import (
    FIELD_NAMES,
    NOTE_TYPE_NAME,
    ensure_note_type,
    preset_field_mapping,
)


class MappingTests(unittest.TestCase):
    def test_every_field_maps_to_a_known_marker_or_is_blank(self) -> None:
        # A field value that names a marker we do not have would print the literal
        # token on the card. Audio is the one deliberately-blank field.
        registry = build_registry()
        for record in preset_field_mapping():
            with self.subTest(field=record["field"]):
                if record["field"] == "Audio":
                    self.assertEqual(record["value"], "")
                    continue
                # The value may combine markers and literals (Sentence does); every
                # marker token in it must resolve.
                import re

                for marker in re.findall(r"\{([\w-]+)\}", record["value"]):
                    self.assertIsNotNone(
                        registry.get(marker), f"{record['field']} uses unknown {{{marker}}}"
                    )

    def test_the_mapping_survives_normalisation(self) -> None:
        # It goes through the same validator a hand-edited preset does.
        mapping = preset_field_mapping()

        self.assertEqual(normalize_mapping(mapping), mapping)

    def test_the_mapping_fields_match_the_note_type_fields(self) -> None:
        self.assertEqual([r["field"] for r in preset_field_mapping()], list(FIELD_NAMES))

    def test_the_mapping_is_configured(self) -> None:
        from anki_lookup.notes.field_mapping import is_configured

        preset = {"deck_id": 1, "notetype_id": 2, "field_mapping": preset_field_mapping()}
        self.assertTrue(is_configured(preset))


class _FakeField(dict):  # type: ignore[type-arg]
    pass


class _FakeModels:
    """The slice of ModelManager ensure_note_type touches."""

    def __init__(self) -> None:
        self._by_name: dict[str, dict[str, Any]] = {}
        self._next_id = 1000
        self.add_calls = 0

    def id_for_name(self, name: str) -> int | None:
        nt = self._by_name.get(name)
        return nt["id"] if nt else None

    def by_name(self, name: str) -> dict[str, Any] | None:
        return self._by_name.get(name)

    def new(self, name: str) -> dict[str, Any]:
        return {"name": name, "flds": [], "tmpls": [], "css": ""}

    def new_field(self, name: str) -> dict[str, Any]:
        return {"name": name}

    def add_field(self, notetype: dict[str, Any], field: dict[str, Any]) -> None:
        notetype["flds"].append(field)

    def new_template(self, name: str) -> dict[str, Any]:
        return {"name": name, "qfmt": "", "afmt": ""}

    def add_template(self, notetype: dict[str, Any], template: dict[str, Any]) -> None:
        notetype["tmpls"].append(template)

    def add(self, notetype: dict[str, Any]) -> Any:
        self.add_calls += 1
        self._next_id += 1
        notetype["id"] = self._next_id
        self._by_name[notetype["name"]] = notetype
        return type("OpChangesWithId", (), {"id": self._next_id})()


class _FakeCol:
    def __init__(self) -> None:
        self.models = _FakeModels()


class CreationTests(unittest.TestCase):
    def test_it_creates_the_note_type_with_the_expected_fields(self) -> None:
        col = _FakeCol()

        note_type_id = ensure_note_type(col)

        nt = col.models.by_name(NOTE_TYPE_NAME)
        assert nt is not None
        self.assertEqual(nt["id"], note_type_id)
        self.assertEqual([f["name"] for f in nt["flds"]], list(FIELD_NAMES))
        self.assertEqual(len(nt["tmpls"]), 1)
        self.assertTrue(nt["css"])
        self.assertIn("{{Expression}}", nt["tmpls"][0]["qfmt"])
        self.assertIn("{{furigana:Furigana}}", nt["tmpls"][0]["afmt"])

    def test_a_second_call_reuses_the_existing_note_type(self) -> None:
        # Anki does not enforce unique note-type names; the guard is ours.
        col = _FakeCol()

        first = ensure_note_type(col)
        second = ensure_note_type(col)

        self.assertEqual(first, second)
        self.assertEqual(col.models.add_calls, 1)

    def test_empty_fields_collapse_via_guards(self) -> None:
        col = _FakeCol()
        ensure_note_type(col)
        back = col.models.by_name(NOTE_TYPE_NAME)["tmpls"][0]["afmt"]

        # Every optional field is wrapped in a {{#Field}}…{{/Field}} conditional so a
        # note made without it does not leave a labelled blank.
        for field in ("Reading", "Furigana", "Pitch", "Translation", "Audio"):
            self.assertIn(f"{{{{#{field}}}}}", back)
            self.assertIn(f"{{{{/{field}}}}}", back)


if __name__ == "__main__":
    unittest.main()
