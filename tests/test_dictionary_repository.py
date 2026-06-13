import unittest
from pathlib import Path

from dictionary_helpers import artifact_path, write_dictionary

from anki_lookup.dictionary.importer import import_dictionary
from anki_lookup.dictionary.models import FrequencySortPolicy
from anki_lookup.dictionary.repository import DictionaryRepository


class DictionaryRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = artifact_path("repository.sqlite3")
        _remove_database(self.database_path)

    def tearDown(self) -> None:
        _remove_database(self.database_path)
        for name in ("first.zip", "second.zip", "third.zip", "metadata.zip"):
            artifact_path(name).unlink(missing_ok=True)

    def test_lookup_keeps_exact_matches_ahead_of_reverse_definition_matches(self) -> None:
        archive = artifact_path("first.zip")
        write_dictionary(
            archive,
            terms=[
                ["cat", "", "", "", 1, ["Exact"], 1, ""],
                ["catalog", "", "", "", 100, ["Prefix"], 2, ""],
                ["猫", "ねこ", "", "", 50, ["cat; feline"], 3, ""],
            ],
        )
        import_dictionary(self.database_path, archive)

        entries = DictionaryRepository(self.database_path).search("cat")

        self.assertEqual([entry.expression for entry in entries], ["cat", "猫"])
        self.assertEqual(entries[0].match_type, "exact")
        self.assertEqual(entries[1].match_type, "definition")

    def test_reverse_lookup_matches_complete_english_tokens(self) -> None:
        archive = artifact_path("first.zip")
        write_dictionary(
            archive,
            terms=[
                ["車", "くるま", "", "", 1, ["car\nautomobile"], 1, ""],
                ["運ぶ", "はこぶ", "", "", 1, ["to carry"], 2, ""],
                ["パトカー", "ぱとかー", "", "", 10, ["police car"], 3, ""],
            ],
        )
        import_dictionary(self.database_path, archive)
        repository = DictionaryRepository(self.database_path)

        self.assertEqual(
            [entry.expression for entry in repository.search("car")],
            ["車", "パトカー"],
        )
        self.assertEqual(repository.search("carpet"), [])

    def test_bulk_exact_lookup_groups_progressively_shorter_terms(self) -> None:
        archive = artifact_path("first.zip")
        write_dictionary(
            archive,
            terms=[
                ["自分の", "じぶんの", "", "", 10, ["one's own"], 1, ""],
                ["自分", "じぶん", "", "", 20, ["oneself"], 2, ""],
            ],
        )
        import_dictionary(self.database_path, archive)

        results = DictionaryRepository(self.database_path).search_exact_many(
            ("自分の", "自分", "自")
        )

        self.assertEqual([entry.expression for entry in results["自分の"]], ["自分の"])
        self.assertEqual([entry.expression for entry in results["自分"]], ["自分"])
        self.assertEqual(results["自"], [])

    def test_bulk_deinflection_rejects_entries_without_compatible_rules(self) -> None:
        archive = artifact_path("first.zip")
        write_dictionary(
            archive,
            terms=[
                ["剥がす", "はがす", "", "", 20, ["untyped"], 1, ""],
                ["剥がす", "はがす", "", "v5s", 10, ["typed"], 2, ""],
            ],
        )
        import_dictionary(self.database_path, archive)

        results = DictionaryRepository(self.database_path).search_exact_many(
            ("はがす",),
            required_rules={"はがす": frozenset({"v5s"})},
            direct_match_type="deinflected",
            include_kanji=False,
        )

        self.assertEqual([entry.definitions for entry in results["はがす"]], [("typed",)])

    def test_bulk_deinflection_accepts_compatible_rule_subtypes(self) -> None:
        archive = artifact_path("first.zip")
        write_dictionary(
            archive,
            terms=[
                ["行く", "いく", "", "v5k-s", 20, ["to go"], 1, ""],
                ["行く", "ゆく", "", "", 10, ["untyped"], 2, ""],
            ],
        )
        import_dictionary(self.database_path, archive)

        results = DictionaryRepository(self.database_path).search_exact_many(
            ("行く",),
            required_rules={"行く": frozenset({"v5k"})},
            direct_match_type="deinflected",
            include_kanji=False,
        )

        self.assertEqual([entry.definitions for entry in results["行く"]], [("to go",)])

    def test_bulk_deinflection_accepts_metadata_free_dictionaries(self) -> None:
        archive = artifact_path("first.zip")
        write_dictionary(
            archive,
            terms=[
                ["食べる", "たべる", "", "", 20, ["to eat"], 1, ""],
            ],
        )
        import_dictionary(self.database_path, archive)

        results = DictionaryRepository(self.database_path).search_exact_many(
            ("食べる",),
            required_rules={"食べる": frozenset({"v1"})},
            direct_match_type="deinflected",
            include_kanji=False,
        )

        self.assertEqual([entry.expression for entry in results["食べる"]], ["食べる"])

    def test_enable_disable_reorder_and_remove(self) -> None:
        first_archive = artifact_path("first.zip")
        second_archive = artifact_path("second.zip")
        write_dictionary(first_archive, title="First", revision="1")
        write_dictionary(second_archive, title="Second", revision="1")
        first = import_dictionary(self.database_path, first_archive).dictionary
        second = import_dictionary(self.database_path, second_archive).dictionary
        repository = DictionaryRepository(self.database_path)

        repository.set_enabled(first.id, False)
        self.assertEqual([entry.dictionary for entry in repository.search("example")], ["Second"])

        repository.move(second.id, -1)
        self.assertEqual(
            [item.title for item in repository.list_dictionaries()], ["Second", "First"]
        )

        repository.remove(first.id)
        self.assertEqual([item.title for item in repository.list_dictionaries()], ["Second"])

    def test_remove_many_is_atomic_and_normalizes_priorities(self) -> None:
        archives = [artifact_path(f"{name}.zip") for name in ("first", "second", "third")]
        for index, archive in enumerate(archives):
            write_dictionary(archive, title=f"Dictionary {index}", revision="1")
        dictionaries = [
            import_dictionary(self.database_path, archive).dictionary for archive in archives
        ]
        repository = DictionaryRepository(self.database_path)

        with self.assertRaises(KeyError):
            repository.remove_many([dictionaries[0].id, 99_999])
        self.assertEqual(len(repository.list_dictionaries()), 3)

        repository.remove_many([dictionaries[0].id, dictionaries[2].id])

        remaining = repository.list_dictionaries()
        self.assertEqual([item.title for item in remaining], ["Dictionary 1"])
        self.assertEqual(remaining[0].priority, 0)

    def test_lookup_enriches_headword_from_independent_metadata_sources(self) -> None:
        term_archive = artifact_path("first.zip")
        metadata_archive = artifact_path("metadata.zip")
        write_dictionary(
            term_archive,
            title="Terms",
            terms=[["食べる", "たべる", "", "v1", 1, ["to eat"], 1, ""]],
        )
        write_dictionary(
            metadata_archive,
            title="Learning Metadata",
            terms=[],
            index_extra={"frequencyMode": "rank-based"},
            extra_files={
                "term_meta_bank_1.json": [
                    ["食べる", "freq", {"reading": "たべる", "frequency": "125㋕"}],
                    ["食べる", "freq", {"reading": "たべない", "frequency": 999}],
                    [
                        "食べる",
                        "pitch",
                        {
                            "reading": "たべる",
                            "pitches": [
                                {
                                    "position": 2,
                                    "nasal": 1,
                                    "devoice": [3],
                                    "tags": ["standard"],
                                },
                                {"position": "LHHL"},
                            ],
                        },
                    ],
                    [
                        "食べる",
                        "ipa",
                        {
                            "reading": "たべる",
                            "transcriptions": [{"ipa": "tabe\u027e\u026f", "tags": ["Tokyo"]}],
                        },
                    ],
                ]
            },
        )
        import_dictionary(self.database_path, term_archive)
        metadata_dictionary = import_dictionary(self.database_path, metadata_archive).dictionary
        repository = DictionaryRepository(self.database_path)

        entry = repository.search("食べる")[0]

        self.assertEqual(
            [
                (item.dictionary, item.value, item.display_value, item.frequency_mode)
                for item in entry.frequencies
            ],
            [("Learning Metadata", 125.0, "125㋕", "rank-based")],
        )
        self.assertEqual(
            [item.position for item in entry.pitch_accents],
            [2, "LHHL"],
        )
        self.assertEqual(entry.pitch_accents[0].nasal_positions, (1,))
        self.assertEqual(entry.pitch_accents[0].devoice_positions, (3,))
        self.assertEqual(
            [(item.transcription, item.tags) for item in entry.ipa],
            [("tabe\u027e\u026f", ("Tokyo",))],
        )

        repository.set_enabled(metadata_dictionary.id, False)
        self.assertEqual(repository.search("食べる")[0].frequencies, ())
        repository.set_enabled(metadata_dictionary.id, True)
        repository.remove(metadata_dictionary.id)
        self.assertEqual(repository.search("食べる")[0].pitch_accents, ())

    def test_frequency_sort_uses_selected_source_and_keeps_missing_values_last(
        self,
    ) -> None:
        term_archive = artifact_path("first.zip")
        rank_archive = artifact_path("second.zip")
        occurrence_archive = artifact_path("third.zip")
        terms = [
            [f"term-{index}", "shared", "", "", 100 - index, [f"entry {index}"], index, ""]
            for index in range(30)
        ]
        write_dictionary(term_archive, title="Terms", terms=terms)
        write_dictionary(
            rank_archive,
            title="Rank Frequency",
            terms=[],
            index_extra={"frequencyMode": "rank-based"},
            extra_files={
                "term_meta_bank_1.json": [
                    ["term-0", "freq", 500],
                    ["term-29", "freq", 10],
                ]
            },
        )
        write_dictionary(
            occurrence_archive,
            title="Occurrence Frequency",
            terms=[],
            index_extra={"frequencyMode": "occurrence-based"},
            extra_files={
                "term_meta_bank_1.json": [
                    ["term-0", "freq", 50_000],
                    ["term-29", "freq", 100],
                ]
            },
        )
        import_dictionary(self.database_path, term_archive)
        rank_source = import_dictionary(self.database_path, rank_archive).dictionary
        occurrence_source = import_dictionary(self.database_path, occurrence_archive).dictionary
        repository = DictionaryRepository(self.database_path)

        default_results = repository.search("shared", limit=3)
        rank_results = repository.search(
            "shared",
            limit=3,
            frequency_sort=FrequencySortPolicy(rank_source.id),
        )
        occurrence_results = repository.search(
            "shared",
            limit=3,
            frequency_sort=FrequencySortPolicy(occurrence_source.id),
        )
        overridden_results = repository.search(
            "shared",
            limit=3,
            frequency_sort=FrequencySortPolicy(rank_source.id, "descending"),
        )
        repository.set_enabled(rank_source.id, False)
        disabled_source_results = repository.search(
            "shared",
            limit=3,
            frequency_sort=FrequencySortPolicy(rank_source.id),
        )

        self.assertEqual(
            [entry.expression for entry in default_results],
            ["term-0", "term-1", "term-2"],
        )
        self.assertEqual(
            [entry.expression for entry in rank_results],
            ["term-29", "term-0", "term-1"],
        )
        self.assertEqual(
            [entry.expression for entry in occurrence_results],
            ["term-0", "term-29", "term-1"],
        )
        self.assertEqual(
            [entry.expression for entry in overridden_results],
            ["term-0", "term-29", "term-1"],
        )
        self.assertEqual(
            [entry.expression for entry in disabled_source_results],
            ["term-0", "term-1", "term-2"],
        )

    def test_lists_only_actual_frequency_metadata_sources(self) -> None:
        rank_archive = artifact_path("second.zip")
        pitch_archive = artifact_path("metadata.zip")
        write_dictionary(
            rank_archive,
            title="Frequency",
            terms=[],
            index_extra={"frequencyMode": "rank-based"},
            extra_files={"term_meta_bank_1.json": [["term", "freq", 10]]},
        )
        write_dictionary(
            pitch_archive,
            title="Pitch",
            terms=[],
            extra_files={
                "term_meta_bank_1.json": [
                    [
                        "term",
                        "pitch",
                        {"reading": "term", "pitches": [{"position": 0}]},
                    ]
                ]
            },
        )
        frequency = import_dictionary(self.database_path, rank_archive).dictionary
        import_dictionary(self.database_path, pitch_archive)
        repository = DictionaryRepository(self.database_path)

        sources = repository.list_frequency_sources()

        self.assertEqual([source.id for source in sources], [frequency.id])
        self.assertEqual(sources[0].frequency_mode, "rank-based")

    def test_frequency_sort_does_not_displace_an_exact_expression_match(self) -> None:
        term_archive = artifact_path("first.zip")
        frequency_archive = artifact_path("second.zip")
        write_dictionary(
            term_archive,
            title="Terms",
            terms=[
                ["shared", "", "", "", 1, ["exact"], 1, ""],
                ["other", "shared", "", "", 100, ["reading"], 2, ""],
            ],
        )
        write_dictionary(
            frequency_archive,
            title="Frequency",
            terms=[],
            index_extra={"frequencyMode": "rank-based"},
            extra_files={
                "term_meta_bank_1.json": [
                    ["shared", "freq", 1_000],
                    ["other", "freq", 1],
                ]
            },
        )
        import_dictionary(self.database_path, term_archive)
        frequency = import_dictionary(self.database_path, frequency_archive).dictionary
        repository = DictionaryRepository(self.database_path)

        entries = repository.search(
            "shared",
            frequency_sort=FrequencySortPolicy(frequency.id),
        )

        self.assertEqual([entry.expression for entry in entries], ["shared", "other"])
        self.assertEqual([entry.match_type for entry in entries], ["exact", "reading"])


def _remove_database(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
