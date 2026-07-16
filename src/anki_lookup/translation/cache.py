"""Bounded SQLite cache for completed translations.

Follows ``dictionary/repository.py``'s connection discipline exactly: a fresh
connection per call, opened and closed inside the method. The bridge server threads
and the Qt main thread both read this, and a shared connection would need
``check_same_thread=False`` and its own locking to be safe. Per-call connections are
cheap here — a translation lookup is one indexed row.

The cache lives in its own database rather than the dictionary one so a cache
problem can never put imported dictionaries at risk, and so clearing it is a file
delete.
"""

from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

#: Rows kept before the oldest are pruned. A translation is a few hundred bytes, so
#: this is a small file even when full; the cap exists so an unattended session
#: cannot grow it without bound.
MAX_ROWS = 5_000

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS translations (
    provider TEXT NOT NULL,
    target_lang TEXT NOT NULL,
    source_text TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (provider, target_lang, source_text)
);
CREATE INDEX IF NOT EXISTS translations_created_at ON translations (created_at);
"""


class TranslationCache:
    """Stores completed translations keyed by provider, target language, and text."""

    def __init__(
        self,
        database_path: Path,
        now: Callable[[], float] | None = None,
    ) -> None:
        self.database_path = database_path
        self._now = now if now is not None else time.time
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(_SCHEMA)
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self._initialized = True

    def get(
        self,
        provider: str,
        target_lang: str,
        source_text: str,
        ttl_hours: int,
    ) -> str | None:
        """Return a cached translation, or None when absent, stale, or caching is off."""

        if ttl_hours <= 0:
            return None

        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT translated_text, created_at
                FROM translations
                WHERE provider = ? AND target_lang = ? AND source_text = ?
                """,
                (provider, target_lang, source_text),
            ).fetchone()

        if row is None:
            return None

        translated_text, created_at = row
        if (self._now() - float(created_at)) > (ttl_hours * 3600):
            return None
        return str(translated_text)

    def store(
        self,
        provider: str,
        target_lang: str,
        source_text: str,
        translated_text: str,
        ttl_hours: int,
    ) -> None:
        """Record a translation. A no-op when caching is turned off."""

        if ttl_hours <= 0:
            return

        self.initialize()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO translations
                    (provider, target_lang, source_text, translated_text, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (provider, target_lang, source_text)
                DO UPDATE SET translated_text = excluded.translated_text,
                              created_at = excluded.created_at
                """,
                (provider, target_lang, source_text, translated_text, self._now()),
            )
            self._prune(connection)

    def clear(self) -> None:
        self.initialize()
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM translations")

    def count(self) -> int:
        self.initialize()
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT COUNT(*) FROM translations").fetchone()
        return int(row[0])

    def _prune(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            DELETE FROM translations
            WHERE rowid NOT IN (
                SELECT rowid FROM translations ORDER BY created_at DESC LIMIT ?
            )
            """,
            (MAX_ROWS,),
        )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=30)
