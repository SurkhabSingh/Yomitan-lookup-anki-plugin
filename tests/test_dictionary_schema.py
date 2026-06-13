import sqlite3
import unittest
from contextlib import closing
from pathlib import Path

from dictionary_helpers import artifact_path

from anki_lookup.dictionary.schema import SCHEMA_VERSION, initialize_database


class DictionarySchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = artifact_path("schema.sqlite3")
        _remove_database(self.database_path)

    def tearDown(self) -> None:
        _remove_database(self.database_path)

    def test_migrates_version_one_database_without_losing_dictionaries(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO schema_meta(key, value) VALUES('schema_version', '1');
                CREATE TABLE dictionaries (
                    id INTEGER PRIMARY KEY,
                    title TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    format INTEGER NOT NULL,
                    source_filename TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    priority INTEGER NOT NULL,
                    term_count INTEGER NOT NULL DEFAULT 0,
                    imported_at TEXT NOT NULL,
                    UNIQUE(title, revision)
                );
                INSERT INTO dictionaries(
                    title, revision, format, source_filename, priority, imported_at
                ) VALUES('Existing', '1', 3, 'existing.zip', 0, '2026-06-11');
                """
            )
            initialize_database(connection)

            version = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()[0]
            dictionary = connection.execute(
                """
                SELECT
                    title, kanji_count, has_rule_metadata,
                    metadata_count, frequency_mode
                FROM dictionaries
                """
            ).fetchone()
            kanji_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'kanji'"
            ).fetchone()
            reverse_index = connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'term_definitions_fts'"
            ).fetchone()
            metadata_table = connection.execute(
                "SELECT name FROM sqlite_master WHERE name = 'term_metadata'"
            ).fetchone()

        self.assertEqual(version, str(SCHEMA_VERSION))
        self.assertEqual(dictionary, ("Existing", 0, 0, 0, ""))
        self.assertIsNotNone(kanji_table)
        self.assertIsNotNone(reverse_index)
        self.assertIsNotNone(metadata_table)

    def test_migrates_existing_terms_into_reverse_lookup_index(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            initialize_database(connection)
            connection.executescript(
                """
                DROP TRIGGER terms_fts_insert;
                DROP TRIGGER terms_fts_delete;
                DROP TRIGGER terms_fts_update_delete;
                DROP TRIGGER terms_fts_update_insert;
                DROP TABLE term_definitions_fts;
                UPDATE schema_meta SET value = '2' WHERE key = 'schema_version';
                INSERT INTO dictionaries(
                    title, revision, format, source_filename, priority, imported_at
                ) VALUES('Existing', '1', 3, 'existing.zip', 0, '2026-06-11');
                INSERT INTO terms(
                    dictionary_id, expression, reading, normalized_expression,
                    normalized_reading, term_tags, definition_tags, score, sequence,
                    definitions_json
                ) VALUES(
                    1, '車', 'くるま', '車', 'くるま', '', '', 0, 1,
                    '["car","automobile"]'
                );
                """
            )

            initialize_database(connection)

            matches = connection.execute(
                """
                SELECT rowid
                FROM term_definitions_fts
                WHERE term_definitions_fts MATCH '"car"'
                """
            ).fetchall()

        self.assertEqual(matches, [(1,)])

    def test_migrates_rule_capability_from_part_of_speech_tags(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            initialize_database(connection)
            connection.executescript(
                """
                UPDATE schema_meta SET value = '4' WHERE key = 'schema_version';
                INSERT INTO dictionaries(
                    title, revision, format, source_filename, priority, imported_at
                ) VALUES
                    ('Grammar aware', '1', 3, 'aware.zip', 0, '2026-06-12'),
                    ('Grammar free', '1', 3, 'free.zip', 1, '2026-06-12');
                INSERT INTO tags(
                    dictionary_id, name, category, sort_order, notes, score
                ) VALUES(1, 'v1', 'partOfSpeech', 0, 'Ichidan verb', 0);
                """
            )
            connection.execute("ALTER TABLE dictionaries DROP COLUMN has_rule_metadata")

            initialize_database(connection)

            capabilities = connection.execute(
                "SELECT title, has_rule_metadata FROM dictionaries ORDER BY priority"
            ).fetchall()

        self.assertEqual(capabilities, [("Grammar aware", 1), ("Grammar free", 0)])

    def test_migrates_version_five_database_for_term_metadata(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection, connection:
            initialize_database(connection)
            connection.execute("UPDATE schema_meta SET value = '5' WHERE key = 'schema_version'")
            connection.execute("ALTER TABLE dictionaries DROP COLUMN metadata_count")
            connection.execute("ALTER TABLE dictionaries DROP COLUMN frequency_mode")
            connection.commit()

            initialize_database(connection)

            columns = {row[1] for row in connection.execute("PRAGMA table_info(dictionaries)")}
            version = connection.execute(
                "SELECT value FROM schema_meta WHERE key = 'schema_version'"
            ).fetchone()[0]

        self.assertEqual(version, str(SCHEMA_VERSION))
        self.assertIn("metadata_count", columns)
        self.assertIn("frequency_mode", columns)


def _remove_database(path: Path) -> None:
    for suffix in ("", "-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
