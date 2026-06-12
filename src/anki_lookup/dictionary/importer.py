"""Secure transactional importer for Yomitan format-3 dictionaries."""

from __future__ import annotations

import json
import math
import re
import sqlite3
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from zipfile import BadZipFile, ZipFile, ZipInfo

from .content import glossary_to_text_items
from .models import DictionaryInfo, ImportResult
from .normalization import normalize_term
from .schema import initialize_database

TERM_BANK_PATTERN = re.compile(r"^term_bank_(\d+)\.json$")
TAG_BANK_PATTERN = re.compile(r"^tag_bank_(\d+)\.json$")
KANJI_BANK_PATTERN = re.compile(r"^kanji_bank_(\d+)\.json$")
TERM_META_BANK_PATTERN = re.compile(r"^term_meta_bank_(\d+)\.json$")

MAX_ARCHIVE_FILES = 10_000
MAX_TOTAL_UNCOMPRESSED_BYTES = 2 * 1024 * 1024 * 1024
MAX_JSON_ENTRY_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 2_000
INSERT_BATCH_SIZE = 1_000


class DictionaryImportError(ValueError):
    """Raised when an archive cannot be imported safely."""


class DictionaryImportCancelled(DictionaryImportError):
    """Raised when the user cancels an in-progress import."""


def import_dictionary(
    database_path: Path,
    archive_path: Path,
    should_cancel: Callable[[], bool] | None = None,
) -> ImportResult:
    """Import one Yomitan dictionary into the database."""

    started = time.perf_counter()
    database_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with ZipFile(archive_path) as archive:
            entries = _validate_archive(archive)
            index = _load_json_object(archive, entries["index.json"])
            title, revision, dictionary_format = _validate_index(index)
            term_banks = _ordered_matching(entries.values(), TERM_BANK_PATTERN)
            kanji_banks = _ordered_matching(entries.values(), KANJI_BANK_PATTERN)

            if not term_banks and not kanji_banks:
                if _ordered_matching(entries.values(), TERM_META_BANK_PATTERN):
                    raise DictionaryImportError(
                        "This archive contains term metadata but no term definitions. "
                        "Import a term dictionary first."
                    )
                raise DictionaryImportError(
                    "The archive contains no searchable term or kanji banks."
                )

            connection = sqlite3.connect(database_path, timeout=30)
            try:
                initialize_database(connection)
                connection.commit()
                connection.execute("BEGIN IMMEDIATE")
                priority = connection.execute(
                    "SELECT COALESCE(MAX(priority), -1) + 1 FROM dictionaries"
                ).fetchone()[0]
                cursor = connection.execute(
                    """
                    INSERT INTO dictionaries(
                        title, revision, format, source_filename, enabled, priority,
                        term_count, kanji_count, imported_at
                    ) VALUES (?, ?, ?, ?, 1, ?, 0, 0, ?)
                    """,
                    (
                        title,
                        revision,
                        dictionary_format,
                        archive_path.name,
                        priority,
                        datetime.now(timezone.utc).isoformat(),
                    ),
                )
                if cursor.lastrowid is None:
                    raise RuntimeError("SQLite did not return the imported dictionary ID")
                dictionary_id = cursor.lastrowid
                term_count = _import_term_banks(
                    connection,
                    archive,
                    term_banks,
                    dictionary_id,
                    should_cancel,
                )
                kanji_count = _import_kanji_banks(
                    connection,
                    archive,
                    kanji_banks,
                    dictionary_id,
                    should_cancel,
                )
                if term_count == 0 and kanji_count == 0:
                    raise DictionaryImportError(
                        "No searchable term definitions or kanji entries were found."
                    )
                _import_tag_banks(
                    connection,
                    archive,
                    _ordered_matching(entries.values(), TAG_BANK_PATTERN),
                    dictionary_id,
                )
                connection.execute(
                    """
                    UPDATE dictionaries
                    SET term_count = ?, kanji_count = ?
                    WHERE id = ?
                    """,
                    (term_count, kanji_count, dictionary_id),
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                if "dictionaries.title, dictionaries.revision" in str(error):
                    raise DictionaryImportError(
                        f"{title} ({revision}) is already imported."
                    ) from error
                raise
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()
    except BadZipFile as error:
        raise DictionaryImportError("The selected file is not a valid ZIP archive.") from error

    dictionary = DictionaryInfo(
        id=dictionary_id,
        title=title,
        revision=revision,
        format=dictionary_format,
        enabled=True,
        priority=int(priority),
        term_count=term_count,
        kanji_count=kanji_count,
    )
    return ImportResult(dictionary, time.perf_counter() - started)


def _validate_archive(archive: ZipFile) -> dict[str, ZipInfo]:
    entries = archive.infolist()
    if not entries or len(entries) > MAX_ARCHIVE_FILES:
        raise DictionaryImportError("The archive has an invalid number of files.")

    by_name: dict[str, ZipInfo] = {}
    total_uncompressed = 0
    for entry in entries:
        if entry.flag_bits & 0x1:
            raise DictionaryImportError(
                f"Encrypted archive entries are unsupported: {entry.filename}"
            )
        path = PurePosixPath(entry.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts:
            raise DictionaryImportError(f"Unsafe archive path: {entry.filename}")
        normalized_name = path.as_posix()
        if normalized_name in by_name:
            raise DictionaryImportError(f"Duplicate archive path: {normalized_name}")
        by_name[normalized_name] = entry
        total_uncompressed += entry.file_size

        if entry.filename.lower().endswith(".json"):
            if entry.file_size > MAX_JSON_ENTRY_BYTES:
                raise DictionaryImportError(f"JSON bank is too large: {entry.filename}")
            if (
                entry.compress_size > 0
                and entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO
            ):
                raise DictionaryImportError(f"Suspicious compression ratio: {entry.filename}")

    if total_uncompressed > MAX_TOTAL_UNCOMPRESSED_BYTES:
        raise DictionaryImportError("The archive expands beyond the 2 GiB safety limit.")
    if "index.json" not in by_name:
        raise DictionaryImportError("The archive does not contain index.json at its root.")
    return by_name


def _validate_index(index: dict[str, Any]) -> tuple[str, str, int]:
    title = index.get("title")
    revision = index.get("revision")
    dictionary_format = index.get("format")
    if not isinstance(title, str) or not title.strip():
        raise DictionaryImportError("index.json has no valid title.")
    if not isinstance(revision, str) or not revision.strip():
        raise DictionaryImportError("index.json has no valid revision.")
    if dictionary_format != 3:
        raise DictionaryImportError(
            f"Dictionary format {dictionary_format!r} is unsupported; expected format 3."
        )
    return title.strip(), revision.strip(), dictionary_format


def _import_term_banks(
    connection: sqlite3.Connection,
    archive: ZipFile,
    banks: list[ZipInfo],
    dictionary_id: int,
    should_cancel: Callable[[], bool] | None,
) -> int:
    term_count = 0
    batch: list[tuple[object, ...]] = []
    for bank in banks:
        _raise_if_cancelled(should_cancel)
        rows = _load_json_array(archive, bank)
        for row_number, row in enumerate(rows, start=1):
            parsed = _parse_term_row(row, bank.filename, row_number)
            if parsed is None:
                continue
            batch.append((dictionary_id, *parsed))
            term_count += 1
            if len(batch) >= INSERT_BATCH_SIZE:
                _raise_if_cancelled(should_cancel)
                _insert_terms(connection, batch)
                batch.clear()
    if batch:
        _insert_terms(connection, batch)
    return term_count


def _import_kanji_banks(
    connection: sqlite3.Connection,
    archive: ZipFile,
    banks: list[ZipInfo],
    dictionary_id: int,
    should_cancel: Callable[[], bool] | None,
) -> int:
    kanji_count = 0
    batch: list[tuple[object, ...]] = []
    for bank in banks:
        _raise_if_cancelled(should_cancel)
        rows = _load_json_array(archive, bank)
        for row_number, row in enumerate(rows, start=1):
            parsed = _parse_kanji_row(row, bank.filename, row_number)
            if parsed is None:
                continue
            batch.append((dictionary_id, *parsed))
            kanji_count += 1
            if len(batch) >= INSERT_BATCH_SIZE:
                _raise_if_cancelled(should_cancel)
                _insert_kanji(connection, batch)
                batch.clear()
    if batch:
        _insert_kanji(connection, batch)
    return kanji_count


def _parse_kanji_row(row: object, bank_name: str, row_number: int) -> tuple[object, ...] | None:
    if not isinstance(row, list) or len(row) < 6:
        raise DictionaryImportError(
            f"{bank_name} row {row_number} does not match the format-3 kanji schema."
        )
    character, onyomi, kunyomi, tags, meanings, stats = row[:6]
    if not isinstance(character, str) or not character.strip():
        return None
    if not isinstance(meanings, list):
        raise DictionaryImportError(f"{bank_name} row {row_number} has invalid kanji meanings.")
    cleaned_meanings = tuple(
        meaning.strip() for meaning in meanings if isinstance(meaning, str) and meaning.strip()
    )
    if not cleaned_meanings:
        return None
    if not isinstance(stats, dict):
        stats = {}
    safe_stats = {
        str(key): value
        for key, value in stats.items()
        if isinstance(key, str) and _is_safe_stat_value(value)
    }
    return (
        character.strip(),
        normalize_term(character),
        onyomi.strip() if isinstance(onyomi, str) else "",
        kunyomi.strip() if isinstance(kunyomi, str) else "",
        tags.strip() if isinstance(tags, str) else "",
        json.dumps(cleaned_meanings, ensure_ascii=False, separators=(",", ":")),
        json.dumps(safe_stats, ensure_ascii=False, separators=(",", ":")),
    )


def _insert_kanji(connection: sqlite3.Connection, batch: list[tuple[object, ...]]) -> None:
    connection.executemany(
        """
        INSERT INTO kanji(
            dictionary_id, character, normalized_character, onyomi, kunyomi,
            tags, meanings_json, stats_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )


def _is_safe_stat_value(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, (str, int, bool))


def _parse_term_row(row: object, bank_name: str, row_number: int) -> tuple[object, ...] | None:
    if not isinstance(row, list) or len(row) < 8:
        raise DictionaryImportError(
            f"{bank_name} row {row_number} does not match the format-3 term schema."
        )
    expression, reading, term_tags, rules, score, glossary, sequence, definition_tags = row[:8]
    if not isinstance(expression, str) or not expression.strip():
        return None
    if not isinstance(reading, str):
        reading = ""
    if not isinstance(term_tags, str):
        term_tags = ""
    if not isinstance(rules, str):
        rules = ""
    if not isinstance(definition_tags, str):
        definition_tags = ""
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
        score = 0
    if isinstance(sequence, bool) or not isinstance(sequence, int):
        sequence = 0

    definitions = glossary_to_text_items(glossary)
    if not definitions:
        return None
    return (
        expression.strip(),
        reading.strip(),
        normalize_term(expression),
        normalize_term(reading),
        term_tags.strip(),
        rules.strip(),
        definition_tags.strip(),
        float(score),
        sequence,
        json.dumps(definitions, ensure_ascii=False, separators=(",", ":")),
    )


def _insert_terms(connection: sqlite3.Connection, batch: list[tuple[object, ...]]) -> None:
    connection.executemany(
        """
        INSERT INTO terms(
            dictionary_id, expression, reading, normalized_expression,
            normalized_reading, term_tags, rules, definition_tags, score, sequence,
            definitions_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )


def _import_tag_banks(
    connection: sqlite3.Connection,
    archive: ZipFile,
    banks: list[ZipInfo],
    dictionary_id: int,
) -> None:
    tags: list[tuple[object, ...]] = []
    for bank in banks:
        for row_number, row in enumerate(_load_json_array(archive, bank), start=1):
            if not isinstance(row, list) or len(row) < 5:
                raise DictionaryImportError(
                    f"{bank.filename} row {row_number} has an invalid tag schema."
                )
            name, category, sort_order, notes, score = row[:5]
            if not isinstance(name, str) or not name:
                continue
            tags.append(
                (
                    dictionary_id,
                    name,
                    category if isinstance(category, str) else "",
                    sort_order if isinstance(sort_order, int) else 0,
                    notes if isinstance(notes, str) else "",
                    float(score) if isinstance(score, (int, float)) else 0.0,
                )
            )
    if tags:
        connection.executemany(
            """
            INSERT OR REPLACE INTO tags(
                dictionary_id, name, category, sort_order, notes, score
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            tags,
        )


def _load_json_object(archive: ZipFile, entry: ZipInfo) -> dict[str, Any]:
    value = _load_json(archive, entry)
    if not isinstance(value, dict):
        raise DictionaryImportError(f"{entry.filename} must contain a JSON object.")
    return value


def _load_json_array(archive: ZipFile, entry: ZipInfo) -> list[object]:
    value = _load_json(archive, entry)
    if not isinstance(value, list):
        raise DictionaryImportError(f"{entry.filename} must contain a JSON array.")
    return value


def _load_json(archive: ZipFile, entry: ZipInfo) -> object:
    try:
        with archive.open(entry) as source:
            return json.load(source)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DictionaryImportError(f"Invalid JSON in {entry.filename}.") from error


def _ordered_matching(entries: Iterable[ZipInfo], pattern: re.Pattern[str]) -> list[ZipInfo]:
    matched: list[tuple[int, ZipInfo]] = []
    for entry in entries:
        match = pattern.fullmatch(entry.filename)
        if match:
            matched.append((int(match.group(1)), entry))
    return [entry for _, entry in sorted(matched, key=lambda item: item[0])]


def _raise_if_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise DictionaryImportCancelled("Dictionary import was cancelled.")
