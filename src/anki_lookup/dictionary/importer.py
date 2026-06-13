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
            title, revision, dictionary_format, frequency_mode = _validate_index(index)
            term_banks = _ordered_matching(entries.values(), TERM_BANK_PATTERN)
            kanji_banks = _ordered_matching(entries.values(), KANJI_BANK_PATTERN)
            term_meta_banks = _ordered_matching(entries.values(), TERM_META_BANK_PATTERN)

            if not term_banks and not kanji_banks and not term_meta_banks:
                raise DictionaryImportError(
                    "The archive contains no searchable term, kanji, or term metadata banks."
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
                        term_count, kanji_count, metadata_count, frequency_mode,
                        imported_at
                    ) VALUES (?, ?, ?, ?, 1, ?, 0, 0, 0, ?, ?)
                    """,
                    (
                        title,
                        revision,
                        dictionary_format,
                        archive_path.name,
                        priority,
                        frequency_mode or "",
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
                metadata_count = _import_term_meta_banks(
                    connection,
                    archive,
                    term_meta_banks,
                    dictionary_id,
                    should_cancel,
                )
                if term_count == 0 and kanji_count == 0 and metadata_count == 0:
                    raise DictionaryImportError(
                        "No searchable term definitions, kanji entries, or term metadata "
                        "were found."
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
                    SET term_count = ?,
                        kanji_count = ?,
                        metadata_count = ?,
                        has_rule_metadata = CASE
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
                    WHERE id = ?
                    """,
                    (term_count, kanji_count, metadata_count, dictionary_id),
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
        metadata_count=metadata_count,
        frequency_mode=frequency_mode,
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


def _validate_index(index: dict[str, Any]) -> tuple[str, str, int, str | None]:
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
    frequency_mode = index.get("frequencyMode")
    if frequency_mode is not None and frequency_mode not in {
        "occurrence-based",
        "rank-based",
    }:
        raise DictionaryImportError("index.json has an invalid frequencyMode.")
    return title.strip(), revision.strip(), dictionary_format, frequency_mode


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


def _import_term_meta_banks(
    connection: sqlite3.Connection,
    archive: ZipFile,
    banks: list[ZipInfo],
    dictionary_id: int,
    should_cancel: Callable[[], bool] | None,
) -> int:
    metadata_count = 0
    batch: list[tuple[object, ...]] = []
    for bank in banks:
        _raise_if_cancelled(should_cancel)
        rows = _load_json_array(archive, bank)
        for row_number, row in enumerate(rows, start=1):
            parsed = _parse_term_meta_row(row, bank.filename, row_number)
            if parsed is None:
                continue
            batch.append((dictionary_id, *parsed))
            metadata_count += 1
            if len(batch) >= INSERT_BATCH_SIZE:
                _raise_if_cancelled(should_cancel)
                _insert_term_metadata(connection, batch)
                batch.clear()
    if batch:
        _insert_term_metadata(connection, batch)
    return metadata_count


def _parse_term_meta_row(
    row: object,
    bank_name: str,
    row_number: int,
) -> tuple[object, ...] | None:
    if not isinstance(row, list) or len(row) != 3:
        raise DictionaryImportError(
            f"{bank_name} row {row_number} does not match the format-3 term metadata schema."
        )
    expression, mode, data = row
    if not isinstance(expression, str) or not expression.strip():
        return None
    if mode not in {"freq", "pitch", "ipa"}:
        raise DictionaryImportError(
            f"{bank_name} row {row_number} has unsupported metadata type {mode!r}."
        )

    if mode == "freq":
        reading, canonical_data = _parse_frequency_data(data, bank_name, row_number)
    elif mode == "pitch":
        reading, canonical_data = _parse_pitch_data(data, bank_name, row_number)
    else:
        reading, canonical_data = _parse_ipa_data(data, bank_name, row_number)

    expression = expression.strip()
    return (
        expression,
        reading,
        normalize_term(expression),
        normalize_term(reading),
        mode,
        json.dumps(canonical_data, ensure_ascii=False, separators=(",", ":")),
    )


def _parse_frequency_data(
    data: object,
    bank_name: str,
    row_number: int,
) -> tuple[str, dict[str, object]]:
    reading = ""
    frequency = data
    if isinstance(data, dict) and "reading" in data:
        if set(data) != {"reading", "frequency"} or not isinstance(data["reading"], str):
            raise DictionaryImportError(
                f"{bank_name} row {row_number} has invalid reading-specific frequency data."
            )
        reading = data["reading"].strip()
        frequency = data["frequency"]

    value, display_value = _parse_frequency_value(frequency, bank_name, row_number)
    return reading, {
        "reading": reading,
        "value": value,
        "display_value": display_value,
    }


def _parse_frequency_value(
    value: object,
    bank_name: str,
    row_number: int,
) -> tuple[float | None, str]:
    if isinstance(value, bool):
        raise DictionaryImportError(f"{bank_name} row {row_number} has invalid frequency data.")
    if isinstance(value, (int, float)):
        if not math.isfinite(value):
            raise DictionaryImportError(f"{bank_name} row {row_number} has a non-finite frequency.")
        return float(value), str(value)
    if isinstance(value, str):
        match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", value)
        numeric_value = float(match.group(0)) if match else None
        return numeric_value, value
    if isinstance(value, dict):
        if set(value) - {"value", "displayValue"} or "value" not in value:
            raise DictionaryImportError(f"{bank_name} row {row_number} has invalid frequency data.")
        numeric_value = value["value"]
        display_value = value.get("displayValue")
        if (
            isinstance(numeric_value, bool)
            or not isinstance(numeric_value, (int, float))
            or not math.isfinite(numeric_value)
            or (display_value is not None and not isinstance(display_value, str))
        ):
            raise DictionaryImportError(f"{bank_name} row {row_number} has invalid frequency data.")
        return float(numeric_value), (
            display_value if isinstance(display_value, str) else str(numeric_value)
        )
    raise DictionaryImportError(f"{bank_name} row {row_number} has invalid frequency data.")


def _parse_pitch_data(
    data: object,
    bank_name: str,
    row_number: int,
) -> tuple[str, dict[str, object]]:
    if (
        not isinstance(data, dict)
        or set(data) - {"reading", "pitches"}
        or not isinstance(data.get("reading"), str)
        or not isinstance(data.get("pitches"), list)
    ):
        raise DictionaryImportError(f"{bank_name} row {row_number} has invalid pitch data.")
    reading = data["reading"].strip()
    pitches: list[dict[str, object]] = []
    for pitch in data["pitches"]:
        if not isinstance(pitch, dict) or set(pitch) - {
            "position",
            "nasal",
            "devoice",
            "tags",
        }:
            raise DictionaryImportError(f"{bank_name} row {row_number} has invalid pitch data.")
        position = pitch.get("position")
        if not (
            (isinstance(position, int) and not isinstance(position, bool) and position >= 0)
            or (isinstance(position, str) and bool(re.fullmatch(r"[HL]+", position)))
        ):
            raise DictionaryImportError(
                f"{bank_name} row {row_number} has an invalid pitch position."
            )
        pitches.append(
            {
                "position": position,
                "nasal": _parse_positions(pitch.get("nasal"), bank_name, row_number, "nasal"),
                "devoice": _parse_positions(pitch.get("devoice"), bank_name, row_number, "devoice"),
                "tags": _parse_metadata_tags(pitch.get("tags"), bank_name, row_number),
            }
        )
    return reading, {"reading": reading, "pitches": pitches}


def _parse_ipa_data(
    data: object,
    bank_name: str,
    row_number: int,
) -> tuple[str, dict[str, object]]:
    if (
        not isinstance(data, dict)
        or set(data) - {"reading", "transcriptions"}
        or not isinstance(data.get("reading"), str)
        or not isinstance(data.get("transcriptions"), list)
    ):
        raise DictionaryImportError(f"{bank_name} row {row_number} has invalid IPA data.")
    reading = data["reading"].strip()
    transcriptions: list[dict[str, object]] = []
    for transcription in data["transcriptions"]:
        if (
            not isinstance(transcription, dict)
            or set(transcription) - {"ipa", "tags"}
            or not isinstance(transcription.get("ipa"), str)
        ):
            raise DictionaryImportError(f"{bank_name} row {row_number} has invalid IPA data.")
        transcriptions.append(
            {
                "ipa": transcription["ipa"],
                "tags": _parse_metadata_tags(transcription.get("tags"), bank_name, row_number),
            }
        )
    return reading, {"reading": reading, "transcriptions": transcriptions}


def _parse_positions(
    value: object,
    bank_name: str,
    row_number: int,
    label: str,
) -> list[int]:
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    if any(
        isinstance(position, bool) or not isinstance(position, int) or position < 0
        for position in values
    ):
        raise DictionaryImportError(f"{bank_name} row {row_number} has invalid {label} positions.")
    return list(dict.fromkeys(values))


def _parse_metadata_tags(
    value: object,
    bank_name: str,
    row_number: int,
) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or any(not isinstance(tag, str) for tag in value):
        raise DictionaryImportError(f"{bank_name} row {row_number} has invalid metadata tags.")
    return list(dict.fromkeys(tag for tag in value if tag))


def _insert_term_metadata(
    connection: sqlite3.Connection,
    batch: list[tuple[object, ...]],
) -> None:
    connection.executemany(
        """
        INSERT INTO term_metadata(
            dictionary_id, expression, reading, normalized_expression,
            normalized_reading, mode, data_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        batch,
    )


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
