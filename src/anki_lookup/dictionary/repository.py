"""SQLite repository for dictionary management and lookup."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Optional

from .models import (
    DictionaryInfo,
    FrequencyInfo,
    FrequencySortPolicy,
    FrequencySourceInfo,
    IpaInfo,
    LookupEntry,
    PitchAccentInfo,
)
from .normalization import normalize_term
from .schema import initialize_database

RankedEntry = tuple[int, int, float, int, LookupEntry]
FrequencySortData = dict[str, list[tuple[str, float, Optional[str]]]]
FREQUENCY_SORT_CANDIDATE_LIMIT = 100


class DictionaryRepository:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            initialize_database(connection)
        self._initialized = True

    def list_dictionaries(self) -> list[DictionaryInfo]:
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    id, title, revision, format, enabled, priority,
                    term_count, kanji_count, metadata_count, frequency_mode
                FROM dictionaries
                ORDER BY priority, id
                """
            ).fetchall()
        return [
            DictionaryInfo(
                id=row[0],
                title=row[1],
                revision=row[2],
                format=row[3],
                enabled=bool(row[4]),
                priority=row[5],
                term_count=row[6],
                kanji_count=row[7],
                metadata_count=row[8],
                frequency_mode=row[9] or None,
            )
            for row in rows
        ]

    def list_frequency_sources(self) -> list[FrequencySourceInfo]:
        self.initialize()
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT
                    d.id,
                    d.title,
                    d.revision,
                    d.enabled,
                    d.frequency_mode
                FROM dictionaries d
                WHERE EXISTS (
                    SELECT 1
                    FROM term_metadata m
                    WHERE m.dictionary_id = d.id
                      AND m.mode = 'freq'
                )
                ORDER BY d.priority, d.id
                """
            ).fetchall()
        return [
            FrequencySourceInfo(
                id=row[0],
                title=row[1],
                revision=row[2],
                enabled=bool(row[3]),
                frequency_mode=row[4] or None,
            )
            for row in rows
        ]

    def search(
        self,
        term: str,
        limit: int = 20,
        required_rules: frozenset[str] = frozenset(),
        direct_match_type: str | None = None,
        include_reverse: bool = True,
        frequency_sort: FrequencySortPolicy | None = None,
    ) -> list[LookupEntry]:
        query = normalize_term(term)
        if not query:
            return []
        limit = min(100, max(1, limit))
        candidate_limit = FREQUENCY_SORT_CANDIDATE_LIMIT if frequency_sort else limit
        self.initialize()
        with closing(self._connect()) as connection:
            term_rows = connection.execute(
                """
                SELECT
                    t.expression,
                    t.reading,
                    d.title,
                    d.has_rule_metadata,
                    t.term_tags,
                    t.rules,
                    t.definition_tags,
                    t.definitions_json,
                    CASE
                        WHEN t.normalized_expression = :query THEN 0
                        ELSE 1
                    END AS match_rank,
                    t.score,
                    d.priority,
                    t.id
                FROM terms t
                JOIN dictionaries d ON d.id = t.dictionary_id
                WHERE d.enabled = 1
                  AND (
                    t.normalized_expression = :query
                    OR t.normalized_reading = :query
                  )
                ORDER BY d.priority, match_rank, t.score DESC, t.id
                LIMIT :limit
                """,
                {"query": query, "limit": candidate_limit},
            ).fetchall()
            kanji_rows = connection.execute(
                """
                SELECT
                    k.character,
                    k.onyomi,
                    k.kunyomi,
                    d.title,
                    k.tags,
                    k.meanings_json,
                    k.stats_json,
                    d.priority,
                    k.id
                FROM kanji k
                JOIN dictionaries d ON d.id = k.dictionary_id
                WHERE d.enabled = 1
                  AND k.normalized_character = :query
                ORDER BY d.priority, k.id
                LIMIT :limit
                """,
                {"query": query, "limit": limit},
            ).fetchall()
            if required_rules:
                term_rows = [
                    row
                    for row in term_rows
                    if not row[3] or _rules_match(required_rules, row[4], row[5])
                ]
            direct_term_ids = {row[11] for row in term_rows}
            reverse_rows = []
            if include_reverse and _is_reverse_lookup_query(query) and len(term_rows) < limit:
                reverse_rows = connection.execute(
                    """
                    SELECT
                        t.expression,
                        t.reading,
                        d.title,
                        t.term_tags,
                        t.rules,
                        t.definition_tags,
                        t.definitions_json,
                        t.score,
                        d.priority,
                        t.id,
                        bm25(term_definitions_fts) AS relevance,
                        CASE
                            WHEN EXISTS (
                                SELECT 1
                                FROM json_each(t.definitions_json)
                                WHERE lower(CAST(value AS TEXT)) = :query
                                   OR lower(CAST(value AS TEXT))
                                      LIKE :query || char(10) || '%'
                            ) THEN 0
                            ELSE 1
                        END AS gloss_rank
                    FROM term_definitions_fts
                    JOIN terms t ON t.id = term_definitions_fts.rowid
                    JOIN dictionaries d ON d.id = t.dictionary_id
                    WHERE d.enabled = 1
                      AND term_definitions_fts MATCH :fts_query
                    ORDER BY gloss_rank, relevance, d.priority, t.score DESC, t.id
                    LIMIT :limit
                    """,
                    {
                        "query": query,
                        "fts_query": _fts_phrase(query),
                        "limit": min(
                            FREQUENCY_SORT_CANDIDATE_LIMIT,
                            candidate_limit + len(direct_term_ids),
                        ),
                    },
                ).fetchall()

        ranked_entries: list[RankedEntry] = [
            (
                row[10],
                row[8],
                -row[9],
                row[11],
                LookupEntry(
                    expression=row[0],
                    reading=row[1],
                    dictionary=row[2],
                    term_tags=tuple(row[4].split()),
                    definition_tags=tuple(row[6].split()),
                    definitions=tuple(json.loads(row[7])),
                    match_type=direct_match_type or ("exact", "reading")[row[8]],
                    score=row[9],
                ),
            )
            for row in term_rows
        ]
        ranked_entries.extend(
            (
                row[8],
                2,
                row[11] * 1000 + row[10],
                row[9],
                LookupEntry(
                    expression=row[0],
                    reading=row[1],
                    dictionary=row[2],
                    term_tags=tuple(row[3].split()),
                    definition_tags=tuple(row[5].split()),
                    definitions=tuple(json.loads(row[6])),
                    match_type="definition",
                    score=row[7],
                ),
            )
            for row in reverse_rows
            if row[9] not in direct_term_ids
        )
        for row in kanji_rows:
            readings = " / ".join(value for value in (row[1], row[2]) if value)
            stats = json.loads(row[6])
            ranked_entries.append(
                (
                    row[7],
                    2,
                    0,
                    row[8],
                    LookupEntry(
                        expression=row[0],
                        reading=readings,
                        dictionary=row[3],
                        term_tags=tuple(row[4].split()),
                        definition_tags=(),
                        definitions=tuple(json.loads(row[5])),
                        match_type="kanji",
                        score=0,
                        entry_type="kanji",
                        metadata=tuple(
                            (str(key), str(value))
                            for key, value in stats.items()
                            if isinstance(key, str)
                        ),
                    ),
                )
            )
        frequency_data = self._load_frequency_sort_data(
            [item[4] for item in ranked_entries],
            frequency_sort,
        )
        ordered = _order_ranked_entries(
            ranked_entries,
            limit,
            frequency_sort,
            frequency_data,
        )
        return self._enrich_entries(ordered)

    def search_exact_many(
        self,
        terms: tuple[str, ...],
        limit_per_term: int = 20,
        required_rules: dict[str, frozenset[str]] | None = None,
        direct_match_type: str | None = None,
        include_kanji: bool = True,
        frequency_sort: FrequencySortPolicy | None = None,
    ) -> dict[str, list[LookupEntry]]:
        """Return direct term, reading, and kanji matches for several source prefixes."""

        queries = list(dict.fromkeys(query for term in terms if (query := normalize_term(term))))
        if not queries:
            return {}

        limit_per_term = min(100, max(1, limit_per_term))
        values = ", ".join("(?, ?)" for _ in queries)
        parameters: list[object] = []
        for index, query in enumerate(queries):
            parameters.extend((query, index))
        normalized_rules = {
            normalize_term(term): rules for term, rules in (required_rules or {}).items() if rules
        }
        row_limit = (
            FREQUENCY_SORT_CANDIDATE_LIMIT
            if normalized_rules or frequency_sort is not None
            else limit_per_term
        )
        parameters.append(row_limit)

        self.initialize()
        with closing(self._connect()) as connection:
            term_rows = connection.execute(
                f"""
                WITH queries(query, query_index) AS (
                    VALUES {values}
                ),
                ranked_terms AS (
                    SELECT
                        q.query,
                        q.query_index,
                        t.expression,
                        t.reading,
                        d.title,
                        d.has_rule_metadata,
                        t.term_tags,
                        t.rules,
                        t.definition_tags,
                        t.definitions_json,
                        CASE
                            WHEN t.normalized_expression = q.query THEN 0
                            ELSE 1
                        END AS match_rank,
                        t.score,
                        d.priority,
                        t.id,
                        ROW_NUMBER() OVER (
                            PARTITION BY q.query_index
                            ORDER BY
                                d.priority,
                                CASE
                                    WHEN t.normalized_expression = q.query THEN 0
                                    ELSE 1
                                END,
                                t.score DESC,
                                t.id
                        ) AS result_rank
                    FROM queries q
                    JOIN terms t
                      ON t.normalized_expression = q.query
                      OR t.normalized_reading = q.query
                    JOIN dictionaries d ON d.id = t.dictionary_id
                    WHERE d.enabled = 1
                )
                SELECT
                    query,
                    query_index,
                    expression,
                    reading,
                    title,
                    has_rule_metadata,
                    term_tags,
                    rules,
                    definition_tags,
                    definitions_json,
                    match_rank,
                    score,
                    priority,
                    id
                FROM ranked_terms
                WHERE result_rank <= ?
                ORDER BY query_index, result_rank
                """,
                parameters,
            ).fetchall()
            kanji_rows = (
                connection.execute(
                    f"""
                    WITH queries(query, query_index) AS (
                        VALUES {values}
                    ),
                    ranked_kanji AS (
                        SELECT
                            q.query,
                            q.query_index,
                            k.character,
                            k.onyomi,
                            k.kunyomi,
                            d.title,
                            k.tags,
                            k.meanings_json,
                            k.stats_json,
                            d.priority,
                            k.id,
                            ROW_NUMBER() OVER (
                                PARTITION BY q.query_index
                                ORDER BY d.priority, k.id
                            ) AS result_rank
                        FROM queries q
                        JOIN kanji k ON k.normalized_character = q.query
                        JOIN dictionaries d ON d.id = k.dictionary_id
                        WHERE d.enabled = 1
                    )
                    SELECT
                        query,
                        query_index,
                        character,
                        onyomi,
                        kunyomi,
                        title,
                        tags,
                        meanings_json,
                        stats_json,
                        priority,
                        id
                    FROM ranked_kanji
                    WHERE result_rank <= ?
                    ORDER BY query_index, result_rank
                    """,
                    parameters,
                ).fetchall()
                if include_kanji
                else []
            )

        ranked_by_query: dict[str, list[RankedEntry]] = {query: [] for query in queries}
        for row in term_rows:
            rules = normalized_rules.get(row[0], frozenset())
            if rules and row[5] and not _rules_match(rules, row[6], row[7]):
                continue
            ranked_by_query[row[0]].append(
                (
                    row[12],
                    row[10],
                    -row[11],
                    row[13],
                    LookupEntry(
                        expression=row[2],
                        reading=row[3],
                        dictionary=row[4],
                        term_tags=tuple(row[6].split()),
                        definition_tags=tuple(row[8].split()),
                        definitions=tuple(json.loads(row[9])),
                        match_type=direct_match_type or ("exact", "reading")[row[10]],
                        score=row[11],
                    ),
                )
            )
        for row in kanji_rows:
            readings = " / ".join(value for value in (row[3], row[4]) if value)
            stats = json.loads(row[8])
            ranked_by_query[row[0]].append(
                (
                    row[9],
                    2,
                    0,
                    row[10],
                    LookupEntry(
                        expression=row[2],
                        reading=readings,
                        dictionary=row[5],
                        term_tags=tuple(row[6].split()),
                        definition_tags=(),
                        definitions=tuple(json.loads(row[7])),
                        match_type="kanji",
                        score=0,
                        entry_type="kanji",
                        metadata=tuple(
                            (str(key), str(value))
                            for key, value in stats.items()
                            if isinstance(key, str)
                        ),
                    ),
                )
            )

        all_entries = [
            ranked_entry[4]
            for ranked_entries in ranked_by_query.values()
            for ranked_entry in ranked_entries
        ]
        frequency_data = self._load_frequency_sort_data(all_entries, frequency_sort)
        results = {
            query: _order_ranked_entries(
                ranked_entries,
                limit_per_term,
                frequency_sort,
                frequency_data,
            )
            for query, ranked_entries in ranked_by_query.items()
        }
        enriched = self._enrich_entries(
            [entry for entries in results.values() for entry in entries]
        )
        offset = 0
        for query in ranked_by_query:
            count = len(results[query])
            results[query] = enriched[offset : offset + count]
            offset += count
        return results

    def _load_frequency_sort_data(
        self,
        entries: list[LookupEntry],
        policy: FrequencySortPolicy | None,
    ) -> FrequencySortData:
        if policy is None:
            return {}
        expressions = list(
            dict.fromkeys(
                normalize_term(entry.expression)
                for entry in entries
                if entry.entry_type == "term" and entry.expression
            )
        )
        if not expressions:
            return {}

        rows: list[tuple[str, str, str, str]] = []
        with closing(self._connect()) as connection:
            for offset in range(0, len(expressions), 400):
                expression_batch = expressions[offset : offset + 400]
                placeholders = ", ".join("?" for _ in expression_batch)
                rows.extend(
                    connection.execute(
                        f"""
                        SELECT
                            m.normalized_expression,
                            m.normalized_reading,
                            m.data_json,
                            d.frequency_mode
                        FROM term_metadata m
                        JOIN dictionaries d ON d.id = m.dictionary_id
                        WHERE d.id = ?
                          AND d.enabled = 1
                          AND m.mode = 'freq'
                          AND m.normalized_expression IN ({placeholders})
                        ORDER BY m.id
                        """,
                        [policy.dictionary_id, *expression_batch],
                    ).fetchall()
                )

        frequency_data: FrequencySortData = {}
        for expression, reading, data_json, frequency_mode in rows:
            data = json.loads(data_json)
            if not isinstance(data, dict):
                continue
            value = data.get("value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            frequency_data.setdefault(expression, []).append(
                (reading, float(value), frequency_mode or None)
            )
        return frequency_data

    def _enrich_entries(self, entries: list[LookupEntry]) -> list[LookupEntry]:
        expressions = list(
            dict.fromkeys(
                normalize_term(entry.expression)
                for entry in entries
                if entry.entry_type == "term" and entry.expression
            )
        )
        if not expressions:
            return entries

        rows: list[tuple[str, str, str, str, str, str]] = []
        with closing(self._connect()) as connection:
            for offset in range(0, len(expressions), 400):
                expression_batch = expressions[offset : offset + 400]
                placeholders = ", ".join("?" for _ in expression_batch)
                rows.extend(
                    connection.execute(
                        f"""
                        SELECT
                            m.normalized_expression,
                            m.normalized_reading,
                            m.mode,
                            m.data_json,
                            d.title,
                            d.frequency_mode
                        FROM term_metadata m
                        JOIN dictionaries d ON d.id = m.dictionary_id
                        WHERE d.enabled = 1
                          AND m.normalized_expression IN ({placeholders})
                        ORDER BY d.priority, m.id
                        """,
                        expression_batch,
                    ).fetchall()
                )

        by_expression: dict[str, list[tuple[str, str, str, str, str]]] = {
            expression: [] for expression in expressions
        }
        for (
            expression,
            reading,
            mode,
            data_json,
            dictionary,
            frequency_mode,
        ) in rows:
            by_expression[expression].append(
                (
                    reading,
                    mode,
                    data_json,
                    dictionary,
                    frequency_mode,
                )
            )

        enriched: list[LookupEntry] = []
        for entry in entries:
            if entry.entry_type != "term":
                enriched.append(entry)
                continue
            reading = normalize_term(entry.reading)
            frequencies: list[FrequencyInfo] = []
            pitch_accents: list[PitchAccentInfo] = []
            ipa: list[IpaInfo] = []
            for (
                metadata_reading,
                mode,
                data_json,
                dictionary,
                frequency_mode,
            ) in by_expression.get(normalize_term(entry.expression), []):
                if metadata_reading and metadata_reading != reading:
                    continue
                data = json.loads(data_json)
                if not isinstance(data, dict):
                    continue
                if mode == "freq":
                    display_value = data.get("display_value")
                    value = data.get("value")
                    if not isinstance(display_value, str):
                        continue
                    numeric_value = (
                        float(value)
                        if isinstance(value, (int, float)) and not isinstance(value, bool)
                        else None
                    )
                    frequencies.append(
                        FrequencyInfo(
                            dictionary=dictionary,
                            value=numeric_value,
                            display_value=display_value,
                            frequency_mode=frequency_mode or None,
                        )
                    )
                elif mode == "pitch":
                    pitches = data.get("pitches")
                    metadata_source_reading = data.get("reading")
                    if not isinstance(pitches, list) or not isinstance(
                        metadata_source_reading, str
                    ):
                        continue
                    for pitch in pitches:
                        pitch_info = _pitch_accent_info(
                            pitch,
                            dictionary,
                            metadata_source_reading,
                        )
                        if pitch_info is not None:
                            pitch_accents.append(pitch_info)
                elif mode == "ipa":
                    transcriptions = data.get("transcriptions")
                    metadata_source_reading = data.get("reading")
                    if not isinstance(transcriptions, list) or not isinstance(
                        metadata_source_reading, str
                    ):
                        continue
                    for transcription in transcriptions:
                        ipa_info = _ipa_info(
                            transcription,
                            dictionary,
                            metadata_source_reading,
                        )
                        if ipa_info is not None:
                            ipa.append(ipa_info)
            enriched.append(
                replace(
                    entry,
                    frequencies=tuple(dict.fromkeys(frequencies)),
                    pitch_accents=tuple(dict.fromkeys(pitch_accents)),
                    ipa=tuple(dict.fromkeys(ipa)),
                )
            )
        return enriched

    def set_enabled(self, dictionary_id: int, enabled: bool) -> None:
        self.initialize()
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "UPDATE dictionaries SET enabled = ? WHERE id = ?",
                (int(enabled), dictionary_id),
            )
            if cursor.rowcount != 1:
                raise KeyError(f"Dictionary {dictionary_id} does not exist")

    def remove(self, dictionary_id: int) -> None:
        self.remove_many([dictionary_id])

    def remove_many(self, dictionary_ids: list[int]) -> None:
        unique_ids = list(dict.fromkeys(dictionary_ids))
        if not unique_ids:
            return
        self.initialize()
        with closing(self._connect()) as connection, connection:
            placeholders = ", ".join("?" for _ in unique_ids)
            existing = {
                row[0]
                for row in connection.execute(
                    f"SELECT id FROM dictionaries WHERE id IN ({placeholders})",
                    unique_ids,
                ).fetchall()
            }
            missing = [
                dictionary_id for dictionary_id in unique_ids if dictionary_id not in existing
            ]
            if missing:
                missing_text = ", ".join(str(dictionary_id) for dictionary_id in missing)
                raise KeyError(f"Dictionaries do not exist: {missing_text}")
            connection.execute(
                f"DELETE FROM dictionaries WHERE id IN ({placeholders})",
                unique_ids,
            )
            self._normalize_priorities(connection)

    def move(self, dictionary_id: int, offset: int) -> None:
        dictionaries = self.list_dictionaries()
        current_index = next(
            (index for index, item in enumerate(dictionaries) if item.id == dictionary_id),
            None,
        )
        if current_index is None:
            raise KeyError(f"Dictionary {dictionary_id} does not exist")
        target_index = max(0, min(len(dictionaries) - 1, current_index + offset))
        if target_index == current_index:
            return
        dictionaries[current_index], dictionaries[target_index] = (
            dictionaries[target_index],
            dictionaries[current_index],
        )
        with closing(self._connect()) as connection, connection:
            connection.executemany(
                "UPDATE dictionaries SET priority = ? WHERE id = ?",
                [(index, item.id) for index, item in enumerate(dictionaries)],
            )

    def _normalize_priorities(self, connection: sqlite3.Connection) -> None:
        rows = connection.execute("SELECT id FROM dictionaries ORDER BY priority, id").fetchall()
        connection.executemany(
            "UPDATE dictionaries SET priority = ? WHERE id = ?",
            [(index, row[0]) for index, row in enumerate(rows)],
        )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _order_ranked_entries(
    ranked_entries: list[RankedEntry],
    limit: int,
    frequency_sort: FrequencySortPolicy | None,
    frequency_data: FrequencySortData,
) -> list[LookupEntry]:
    if frequency_sort is None:
        ranked_entries.sort(key=lambda item: item[:4])
    else:
        ranked_entries.sort(
            key=lambda item: (
                item[1],
                *_frequency_sort_key(item[4], frequency_sort, frequency_data),
                item[0],
                item[2],
                item[3],
            )
        )
    return [item[4] for item in ranked_entries[:limit]]


def _frequency_sort_key(
    entry: LookupEntry,
    policy: FrequencySortPolicy,
    frequency_data: FrequencySortData,
) -> tuple[int, float]:
    values: list[float] = []
    frequency_mode: str | None = None
    reading = normalize_term(entry.reading)
    for metadata_reading, value, mode in frequency_data.get(normalize_term(entry.expression), []):
        if metadata_reading and metadata_reading != reading:
            continue
        values.append(value)
        frequency_mode = mode or frequency_mode

    if not values:
        return (1, 0.0)

    order = policy.order
    if order == "auto":
        order = "descending" if frequency_mode == "occurrence-based" else "ascending"
    if order == "descending":
        return (0, -max(values))
    return (0, min(values))


def _pitch_accent_info(
    value: object,
    dictionary: str,
    reading: str,
) -> PitchAccentInfo | None:
    if not isinstance(value, dict):
        return None
    position = value.get("position")
    if not (
        (isinstance(position, int) and not isinstance(position, bool)) or isinstance(position, str)
    ):
        return None
    return PitchAccentInfo(
        dictionary=dictionary,
        reading=reading,
        position=position,
        nasal_positions=_integer_tuple(value.get("nasal")),
        devoice_positions=_integer_tuple(value.get("devoice")),
        tags=_string_tuple(value.get("tags")),
    )


def _ipa_info(
    value: object,
    dictionary: str,
    reading: str,
) -> IpaInfo | None:
    if not isinstance(value, dict):
        return None
    transcription = value.get("ipa")
    if not isinstance(transcription, str):
        return None
    return IpaInfo(
        dictionary=dictionary,
        reading=reading,
        transcription=transcription,
        tags=_string_tuple(value.get("tags")),
    )


def _integer_tuple(value: object) -> tuple[int, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, int) and not isinstance(item, bool))


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _is_reverse_lookup_query(query: str) -> bool:
    return any("a" <= character <= "z" for character in query.casefold())


def _fts_phrase(query: str) -> str:
    return f'"{query.replace(chr(34), chr(34) * 2)}"'


def _rules_match(required: frozenset[str], term_tags: str, rules: str) -> bool:
    available = frozenset((*term_tags.split(), *rules.split()))
    return any(
        _rule_is_compatible(required_rule, available_rule)
        for required_rule in required
        for available_rule in available
    )


def _rule_is_compatible(required: str, available: str) -> bool:
    if required == available:
        return True
    if required.startswith("v5"):
        return available == "v5" or available.startswith(required + "-")
    if required in {"v1", "vs"}:
        return available.startswith(required + "-")
    return False
