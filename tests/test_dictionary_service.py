import unittest
from pathlib import Path
from zipfile import ZipFile

from dictionary_helpers import artifact_path, write_dictionary

from anki_lookup.dictionary.models import FrequencySortPolicy
from anki_lookup.dictionary.service import DictionaryService


class DictionaryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = artifact_path("service.sqlite3")
        self.valid_archive = artifact_path("service-valid.zip")
        self.invalid_archive = artifact_path("service-invalid.zip")
        self.metadata_archive = artifact_path("service-metadata.zip")
        _remove_database(self.database_path)
        self.valid_archive.unlink(missing_ok=True)
        self.invalid_archive.unlink(missing_ok=True)
        self.metadata_archive.unlink(missing_ok=True)

    def tearDown(self) -> None:
        _remove_database(self.database_path)
        self.valid_archive.unlink(missing_ok=True)
        self.invalid_archive.unlink(missing_ok=True)
        self.metadata_archive.unlink(missing_ok=True)

    def test_batch_import_keeps_successes_and_reports_failures(self) -> None:
        write_dictionary(self.valid_archive, title="Valid")
        with ZipFile(self.invalid_archive, "w") as archive:
            archive.writestr("not-index.json", "{}")
        service = DictionaryService(self.database_path)

        result = service.import_archives([self.invalid_archive, self.valid_archive])

        self.assertEqual([item.dictionary.title for item in result.imported], ["Valid"])
        self.assertEqual([item.filename for item in result.failed], ["service-invalid.zip"])
        self.assertFalse(result.cancelled)
        self.assertEqual([item.title for item in service.list_dictionaries()], ["Valid"])

    def test_batch_import_stops_before_next_archive_when_cancelled(self) -> None:
        write_dictionary(self.valid_archive, title="Valid")
        service = DictionaryService(self.database_path)

        result = service.import_archives([self.valid_archive], should_cancel=lambda: True)

        self.assertTrue(result.cancelled)
        self.assertEqual(result.imported, ())
        self.assertEqual(service.list_dictionaries(), [])

    def test_lookup_candidates_returns_longest_exact_match(self) -> None:
        write_dictionary(
            self.valid_archive,
            title="Japanese",
            terms=[
                ["くるま", "", "", "", 0, ["car"], 1, ""],
                ["くる", "", "", "", 0, ["come"], 2, ""],
            ],
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)

        matched_term, entries = service.lookup_candidates(
            ("くるま", "くる", "く"),
            "くる",
        )

        self.assertEqual(matched_term, "くるま")
        self.assertEqual(entries[0].definitions, ("car",))

    def test_lookup_candidates_deinflects_japanese_continuative_form(self) -> None:
        write_dictionary(
            self.valid_archive,
            title="Japanese",
            terms=[
                ["剥がす", "はがす", "", "v5s", 0, ["to peel off"], 1, ""],
            ],
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)

        matched_term, entries = service.lookup_candidates(("はがし",), "はがし")

        self.assertEqual(matched_term, "はがし")
        self.assertEqual(entries[0].expression, "剥がす")
        self.assertEqual(entries[0].match_type, "deinflected")
        self.assertEqual(entries[0].inflection_reasons, ("continuative",))

    def test_lookup_candidates_returns_complete_japanese_inflection_chain(self) -> None:
        write_dictionary(
            self.valid_archive,
            title="Japanese",
            terms=[
                ["食べる", "たべる", "", "v1", 0, ["to eat"], 1, ""],
            ],
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)

        matched_term, entries = service.lookup_candidates(("食べていた",), "食べていた")

        self.assertEqual(matched_term, "食べていた")
        self.assertEqual(entries[0].expression, "食べる")
        self.assertEqual(entries[0].match_type, "deinflected")
        self.assertEqual(entries[0].inflection_reasons, ("-て", "-いる", "-た"))

    def test_deinflected_lookup_includes_base_headword_metadata(self) -> None:
        write_dictionary(
            self.valid_archive,
            title="Japanese",
            terms=[
                ["食べる", "たべる", "", "v1", 0, ["to eat"], 1, ""],
            ],
        )
        write_dictionary(
            self.metadata_archive,
            title="Pitch",
            terms=[],
            extra_files={
                "term_meta_bank_1.json": [
                    [
                        "食べる",
                        "pitch",
                        {
                            "reading": "たべる",
                            "pitches": [{"position": 2}],
                        },
                    ]
                ]
            },
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)
        service.import_archive(self.metadata_archive)

        _, entries = service.lookup_candidates(("食べていた",), "食べていた")

        self.assertEqual(entries[0].expression, "食べる")
        self.assertEqual(entries[0].pitch_accents[0].position, 2)

    def test_lookup_candidates_applies_frequency_sorting(self) -> None:
        write_dictionary(
            self.valid_archive,
            title="Terms",
            terms=[
                ["less-common", "shared", "", "", 100, ["less common"], 1, ""],
                ["common", "shared", "", "", 10, ["common"], 2, ""],
                ["unknown", "shared", "", "", 200, ["unknown"], 3, ""],
            ],
        )
        write_dictionary(
            self.metadata_archive,
            title="Frequency",
            terms=[],
            index_extra={"frequencyMode": "rank-based"},
            extra_files={
                "term_meta_bank_1.json": [
                    ["less-common", "freq", 500],
                    ["common", "freq", 10],
                ]
            },
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)
        frequency = service.import_archive(self.metadata_archive).dictionary

        _, entries = service.lookup_candidates(
            ("shared",),
            "shared",
            frequency_sort=FrequencySortPolicy(frequency.id),
        )

        self.assertEqual(
            [entry.expression for entry in entries],
            ["common", "less-common", "unknown"],
        )

    def test_lookup_candidates_accepts_special_godan_dictionary_rules(self) -> None:
        write_dictionary(
            self.valid_archive,
            title="Japanese",
            terms=[
                ["行く", "いく", "", "v5k-s", 0, ["to go"], 1, ""],
                ["行う", "おこなう", "", "v5u", 0, ["to perform"], 2, ""],
            ],
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)

        _, entries = service.lookup_candidates(("行っていた",), "行っていた")

        self.assertEqual(entries[0].expression, "行く")
        self.assertEqual(entries[0].inflection_reasons, ("-て", "-いる", "-た"))

    def test_lookup_candidates_keeps_metadata_free_lemma_and_shorter_kanji_term(
        self,
    ) -> None:
        write_dictionary(
            self.valid_archive,
            title="Japanese monolingual",
            terms=[
                ["食べる", "たべる", "", "", 20, ["to eat"], 1, ""],
                ["食", "しょく", "", "", 10, ["food"], 2, ""],
            ],
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)

        _, entries = service.lookup_candidates(
            ("食べていた", "食べてい", "食べて", "食べ", "食"),
            "食べていた",
        )

        self.assertEqual([entry.expression for entry in entries], ["食べる", "食"])
        self.assertEqual(entries[0].inflection_reasons, ("-て", "-いる", "-た"))
        self.assertEqual(entries[1].inflection_reasons, ())

    def test_lookup_candidates_uses_english_lemma_for_reverse_lookup(self) -> None:
        write_dictionary(
            self.valid_archive,
            title="Japanese",
            terms=[
                ["車", "くるま", "", "n", 0, ["car"], 1, ""],
            ],
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)

        matched_term, entries = service.lookup_candidates(("cars",), "cars")

        self.assertEqual(matched_term, "cars")
        self.assertEqual(entries[0].expression, "車")
        self.assertEqual(entries[0].match_type, "definition")

    def test_lookup_candidates_keeps_exact_phrase_and_shorter_japanese_match(self) -> None:
        write_dictionary(
            self.valid_archive,
            title="Japanese",
            terms=[
                ["自分の", "じぶんの", "", "", 20, ["one's own"], 1, ""],
                ["自分", "じぶん", "", "", 10, ["oneself"], 2, ""],
            ],
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)

        matched_term, entries = service.lookup_candidates(
            ("自分の", "自分", "自"),
            "自分の",
        )

        self.assertEqual(matched_term, "自分の")
        self.assertEqual([entry.expression for entry in entries], ["自分の", "自分"])

    def test_lookup_candidates_keeps_shorter_match_when_longest_fills_limit(self) -> None:
        long_matches = [
            ["自分の", "じぶんの", "", "", 100 - index, [f"phrase {index}"], index, ""]
            for index in range(1, 22)
        ]
        write_dictionary(
            self.valid_archive,
            title="Japanese",
            terms=[
                *long_matches,
                ["自分", "じぶん", "", "", 1, ["oneself"], 100, ""],
            ],
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)

        _, entries = service.lookup_candidates(
            ("自分の", "自分", "自"),
            "自分の",
            limit=20,
        )

        self.assertEqual(len(entries), 20)
        self.assertEqual(entries[-1].expression, "自分")

    def test_lookup_candidates_progressively_shortens_non_japanese_phrases(self) -> None:
        write_dictionary(
            self.valid_archive,
            title="English",
            terms=[
                ["take off", "", "", "", 20, ["depart"], 1, ""],
                ["take", "", "", "", 10, ["grasp"], 2, ""],
            ],
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.valid_archive)

        matched_term, entries = service.lookup_candidates(
            ("take off quickly", "take off", "take"),
            "take",
        )

        self.assertEqual(matched_term, "take off")
        self.assertEqual(
            [entry.expression for entry in entries if entry.match_type == "exact"],
            ["take off", "take"],
        )


def _remove_database(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
