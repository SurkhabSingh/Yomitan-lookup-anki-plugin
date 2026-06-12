import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from zipfile import ZipFile

from dictionary_helpers import artifact_path, write_dictionary

from anki_lookup.dictionary.importer import (
    DictionaryImportCancelled,
    DictionaryImportError,
    import_dictionary,
)
from anki_lookup.dictionary.repository import DictionaryRepository


class DictionaryImporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = artifact_path("importer.sqlite3")
        self.archive_path = artifact_path("synthetic.zip")
        _remove_database(self.database_path)
        self.archive_path.unlink(missing_ok=True)

    def tearDown(self) -> None:
        _remove_database(self.database_path)
        self.archive_path.unlink(missing_ok=True)

    def test_imports_format_three_terms_and_tags(self) -> None:
        write_dictionary(
            self.archive_path,
            terms=[
                [
                    "Cafe",
                    "cafe",
                    "common",
                    "",
                    5,
                    [
                        {
                            "type": "structured-content",
                            "content": [
                                {"tag": "div", "content": "A small restaurant."},
                                {"tag": "img", "path": "unsafe.png"},
                            ],
                        }
                    ],
                    10,
                    "noun",
                ]
            ],
        )

        result = import_dictionary(self.database_path, self.archive_path)
        repository = DictionaryRepository(self.database_path)
        entries = repository.search("CAFE")

        self.assertEqual(result.dictionary.term_count, 1)
        self.assertEqual(result.dictionary.kanji_count, 0)
        self.assertEqual(entries[0].expression, "Cafe")
        self.assertEqual(entries[0].definitions, ("A small restaurant.",))
        self.assertEqual(entries[0].term_tags, ("common",))
        self.assertEqual(entries[0].definition_tags, ("noun",))

        with closing(sqlite3.connect(self.database_path)) as connection:
            tag_count = connection.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        self.assertEqual(tag_count, 1)

    def test_duplicate_import_rolls_back(self) -> None:
        write_dictionary(self.archive_path)
        import_dictionary(self.database_path, self.archive_path)

        with self.assertRaisesRegex(DictionaryImportError, "already imported"):
            import_dictionary(self.database_path, self.archive_path)

        dictionaries = DictionaryRepository(self.database_path).list_dictionaries()
        self.assertEqual(len(dictionaries), 1)
        self.assertEqual(dictionaries[0].term_count, 1)

    def test_rejects_unsafe_archive_path_without_creating_dictionary(self) -> None:
        with ZipFile(self.archive_path, "w") as archive:
            archive.writestr(
                "index.json",
                '{"title":"Unsafe","revision":"1","format":3}',
            )
            archive.writestr("../term_bank_1.json", "[]")

        with self.assertRaisesRegex(DictionaryImportError, "Unsafe archive path"):
            import_dictionary(self.database_path, self.archive_path)

        repository = DictionaryRepository(self.database_path)
        self.assertEqual(repository.list_dictionaries(), [])

    def test_imports_and_searches_kanji_only_archive(self) -> None:
        write_dictionary(
            self.archive_path,
            terms=[],
            extra_files={
                "term_bank_1.json": [],
                "kanji_bank_1.json": [
                    ["字", "ジ", "あざ", "jouyou", ["character", "letter"], {"grade": 1}]
                ],
            },
        )

        result = import_dictionary(self.database_path, self.archive_path)
        entries = DictionaryRepository(self.database_path).search("字")

        self.assertEqual(result.dictionary.term_count, 0)
        self.assertEqual(result.dictionary.kanji_count, 1)
        self.assertEqual(entries[0].entry_type, "kanji")
        self.assertEqual(entries[0].reading, "ジ / あざ")
        self.assertEqual(entries[0].definitions, ("character", "letter"))
        self.assertEqual(entries[0].metadata, (("grade", "1"),))

    def test_cancelled_import_rolls_back_partial_terms(self) -> None:
        rows = [
            [f"term-{index}", "", "", "", 0, [f"Definition {index}"], index, ""]
            for index in range(2_100)
        ]
        write_dictionary(self.archive_path, terms=rows)
        checks = 0

        def should_cancel() -> bool:
            nonlocal checks
            checks += 1
            return checks >= 3

        with self.assertRaises(DictionaryImportCancelled):
            import_dictionary(
                self.database_path,
                self.archive_path,
                should_cancel=should_cancel,
            )

        self.assertEqual(DictionaryRepository(self.database_path).list_dictionaries(), [])


def _remove_database(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
