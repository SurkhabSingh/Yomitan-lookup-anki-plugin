import unittest
from pathlib import Path

from dictionary_helpers import artifact_path, write_dictionary

from anki_lookup.dictionary.importer import import_dictionary
from anki_lookup.dictionary.repository import DictionaryRepository


class DictionaryRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = artifact_path("repository.sqlite3")
        _remove_database(self.database_path)

    def tearDown(self) -> None:
        _remove_database(self.database_path)
        for name in ("first.zip", "second.zip", "third.zip"):
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


def _remove_database(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
