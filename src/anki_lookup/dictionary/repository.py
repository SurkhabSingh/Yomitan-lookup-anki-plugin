"""SQLite repository for dictionary management and lookup."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .models import DictionaryInfo, LookupEntry
from .normalization import normalize_term
from .schema import initialize_database


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
                SELECT id, title, revision, format, enabled, priority, term_count, kanji_count
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
    ) -> list[LookupEntry]:
        query = normalize_term(term)
        if not query:
            return []
        limit = min(100, max(1, limit))
        self.initialize()
        with closing(self._connect()) as connection:
            term_rows = connection.execute(
                """
                SELECT
                    t.expression,
                    t.reading,
                    d.title,
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
                {"query": query, "limit": limit},
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
                    row for row in term_rows if _rules_match(required_rules, row[3], row[4])
                ]
            direct_term_ids = {row[10] for row in term_rows}
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
                        "limit": min(100, limit + len(direct_term_ids)),
                    },
                ).fetchall()

        ranked_entries = [
            (
                row[9],
                row[7],
                -row[8],
                row[10],
                LookupEntry(
                    expression=row[0],
                    reading=row[1],
                    dictionary=row[2],
                    term_tags=tuple(row[3].split()),
                    definition_tags=tuple(row[5].split()),
                    definitions=tuple(json.loads(row[6])),
                    match_type=direct_match_type or ("exact", "reading")[row[7]],
                    score=row[8],
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
        ranked_entries.sort(key=lambda item: item[:4])
        return [item[4] for item in ranked_entries[:limit]]

    def search_exact_many(
        self,
        terms: tuple[str, ...],
        limit_per_term: int = 20,
        required_rules: dict[str, frozenset[str]] | None = None,
        direct_match_type: str | None = None,
        include_kanji: bool = True,
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
        row_limit = 100 if normalized_rules else limit_per_term
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

        ranked_by_query: dict[str, list[tuple[int, int, float, int, LookupEntry]]] = {
            query: [] for query in queries
        }
        for row in term_rows:
            rules = normalized_rules.get(row[0], frozenset())
            if rules and not _rules_match(rules, row[5], row[6]):
                continue
            ranked_by_query[row[0]].append(
                (
                    row[11],
                    row[9],
                    -row[10],
                    row[12],
                    LookupEntry(
                        expression=row[2],
                        reading=row[3],
                        dictionary=row[4],
                        term_tags=tuple(row[5].split()),
                        definition_tags=tuple(row[7].split()),
                        definitions=tuple(json.loads(row[8])),
                        match_type=direct_match_type or ("exact", "reading")[row[9]],
                        score=row[10],
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

        results: dict[str, list[LookupEntry]] = {}
        for query, ranked_entries in ranked_by_query.items():
            ranked_entries.sort(key=lambda item: item[:4])
            results[query] = [item[4] for item in ranked_entries[:limit_per_term]]
        return results

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


def _is_reverse_lookup_query(query: str) -> bool:
    return any("a" <= character <= "z" for character in query.casefold())


def _fts_phrase(query: str) -> str:
    return f'"{query.replace(chr(34), chr(34) * 2)}"'


def _rules_match(required: frozenset[str], term_tags: str, rules: str) -> bool:
    available = frozenset((*term_tags.split(), *rules.split()))
    return bool(required & available)
