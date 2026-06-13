"""SQLite schema and migrations for imported dictionaries."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 6


def initialize_database(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dictionaries (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            revision TEXT NOT NULL,
            format INTEGER NOT NULL,
            source_filename TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
            priority INTEGER NOT NULL,
            term_count INTEGER NOT NULL DEFAULT 0,
            kanji_count INTEGER NOT NULL DEFAULT 0,
            metadata_count INTEGER NOT NULL DEFAULT 0,
            frequency_mode TEXT NOT NULL DEFAULT '',
            has_rule_metadata INTEGER NOT NULL DEFAULT 0
                CHECK (has_rule_metadata IN (0, 1)),
            imported_at TEXT NOT NULL,
            UNIQUE(title, revision)
        );

        CREATE TABLE IF NOT EXISTS terms (
            id INTEGER PRIMARY KEY,
            dictionary_id INTEGER NOT NULL REFERENCES dictionaries(id) ON DELETE CASCADE,
            expression TEXT NOT NULL,
            reading TEXT NOT NULL,
            normalized_expression TEXT NOT NULL,
            normalized_reading TEXT NOT NULL,
            term_tags TEXT NOT NULL,
            rules TEXT NOT NULL DEFAULT '',
            definition_tags TEXT NOT NULL,
            score REAL NOT NULL,
            sequence INTEGER NOT NULL,
            definitions_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS tags (
            dictionary_id INTEGER NOT NULL REFERENCES dictionaries(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            category TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            notes TEXT NOT NULL,
            score REAL NOT NULL,
            PRIMARY KEY (dictionary_id, name)
        );

        CREATE TABLE IF NOT EXISTS kanji (
            id INTEGER PRIMARY KEY,
            dictionary_id INTEGER NOT NULL REFERENCES dictionaries(id) ON DELETE CASCADE,
            character TEXT NOT NULL,
            normalized_character TEXT NOT NULL,
            onyomi TEXT NOT NULL,
            kunyomi TEXT NOT NULL,
            tags TEXT NOT NULL,
            meanings_json TEXT NOT NULL,
            stats_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS term_metadata (
            id INTEGER PRIMARY KEY,
            dictionary_id INTEGER NOT NULL REFERENCES dictionaries(id) ON DELETE CASCADE,
            expression TEXT NOT NULL,
            reading TEXT NOT NULL,
            normalized_expression TEXT NOT NULL,
            normalized_reading TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('freq', 'pitch', 'ipa')),
            data_json TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS terms_expression_idx
            ON terms(normalized_expression, dictionary_id);
        CREATE INDEX IF NOT EXISTS terms_reading_idx
            ON terms(normalized_reading, dictionary_id);
        CREATE INDEX IF NOT EXISTS terms_dictionary_idx
            ON terms(dictionary_id);
        CREATE INDEX IF NOT EXISTS kanji_character_idx
            ON kanji(normalized_character, dictionary_id);
        CREATE INDEX IF NOT EXISTS kanji_dictionary_idx
            ON kanji(dictionary_id);
        CREATE INDEX IF NOT EXISTS term_metadata_expression_idx
            ON term_metadata(normalized_expression, dictionary_id);
        CREATE INDEX IF NOT EXISTS term_metadata_reading_idx
            ON term_metadata(normalized_expression, normalized_reading, dictionary_id);
        CREATE INDEX IF NOT EXISTS term_metadata_dictionary_idx
            ON term_metadata(dictionary_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS term_definitions_fts USING fts5(
            definitions,
            content='',
            tokenize='unicode61 remove_diacritics 2'
        );

        CREATE TRIGGER IF NOT EXISTS terms_fts_insert
        AFTER INSERT ON terms
        WHEN new.definitions_json GLOB '*[A-Za-z]*' BEGIN
            INSERT INTO term_definitions_fts(rowid, definitions)
            VALUES (new.id, new.definitions_json);
        END;
        CREATE TRIGGER IF NOT EXISTS terms_fts_delete
        AFTER DELETE ON terms
        WHEN old.definitions_json GLOB '*[A-Za-z]*' BEGIN
            INSERT INTO term_definitions_fts(term_definitions_fts, rowid, definitions)
            VALUES ('delete', old.id, old.definitions_json);
        END;
        CREATE TRIGGER IF NOT EXISTS terms_fts_update_delete
        AFTER UPDATE OF definitions_json ON terms
        WHEN old.definitions_json GLOB '*[A-Za-z]*' BEGIN
            INSERT INTO term_definitions_fts(term_definitions_fts, rowid, definitions)
            VALUES ('delete', old.id, old.definitions_json);
        END;
        CREATE TRIGGER IF NOT EXISTS terms_fts_update_insert
        AFTER UPDATE OF definitions_json ON terms
        WHEN new.definitions_json GLOB '*[A-Za-z]*' BEGIN
            INSERT INTO term_definitions_fts(rowid, definitions)
            VALUES (new.id, new.definitions_json);
        END;
        """
    )
    existing = connection.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    if existing is None:
        connection.execute(
            "INSERT INTO schema_meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
    elif int(existing[0]) in {1, 2, 3, 4, 5}:
        existing_version = int(existing[0])
        dictionary_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(dictionaries)").fetchall()
        }
        if "kanji_count" not in dictionary_columns:
            connection.execute(
                "ALTER TABLE dictionaries ADD COLUMN kanji_count INTEGER NOT NULL DEFAULT 0"
            )
        if "has_rule_metadata" not in dictionary_columns:
            connection.execute(
                """
                ALTER TABLE dictionaries
                ADD COLUMN has_rule_metadata INTEGER NOT NULL DEFAULT 0
                CHECK (has_rule_metadata IN (0, 1))
                """
            )
        if "metadata_count" not in dictionary_columns:
            connection.execute(
                "ALTER TABLE dictionaries ADD COLUMN metadata_count INTEGER NOT NULL DEFAULT 0"
            )
        if "frequency_mode" not in dictionary_columns:
            connection.execute(
                "ALTER TABLE dictionaries ADD COLUMN frequency_mode TEXT NOT NULL DEFAULT ''"
            )
        term_columns = {row[1] for row in connection.execute("PRAGMA table_info(terms)").fetchall()}
        if "rules" not in term_columns:
            connection.execute("ALTER TABLE terms ADD COLUMN rules TEXT NOT NULL DEFAULT ''")
        if existing_version < 3:
            connection.execute(
                """
                INSERT INTO term_definitions_fts(rowid, definitions)
                SELECT id, definitions_json
                FROM terms
                WHERE definitions_json GLOB '*[A-Za-z]*'
                """
            )
        connection.execute(
            """
            UPDATE dictionaries
            SET has_rule_metadata = CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM tags
                    WHERE tags.dictionary_id = dictionaries.id
                      AND lower(tags.category) = 'partofspeech'
                )
                OR EXISTS (
                    SELECT 1
                    FROM terms
                    WHERE terms.dictionary_id = dictionaries.id
                      AND trim(terms.rules) <> ''
                )
                THEN 1
                ELSE 0
            END
            """
        )
        connection.execute(
            "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
            (str(SCHEMA_VERSION),),
        )
    elif int(existing[0]) != SCHEMA_VERSION:
        raise RuntimeError(
            f"Unsupported dictionary database schema {existing[0]}; expected {SCHEMA_VERSION}"
        )
