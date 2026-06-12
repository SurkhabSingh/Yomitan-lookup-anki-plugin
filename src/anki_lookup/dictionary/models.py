"""Dictionary domain models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DictionaryInfo:
    id: int
    title: str
    revision: str
    format: int
    enabled: bool
    priority: int
    term_count: int
    kanji_count: int


@dataclass(frozen=True)
class ImportResult:
    dictionary: DictionaryInfo
    elapsed_seconds: float


@dataclass(frozen=True)
class ImportFailure:
    filename: str
    message: str


@dataclass(frozen=True)
class BatchImportResult:
    imported: tuple[ImportResult, ...]
    failed: tuple[ImportFailure, ...]
    cancelled: bool


@dataclass(frozen=True)
class LookupEntry:
    expression: str
    reading: str
    dictionary: str
    term_tags: tuple[str, ...]
    definition_tags: tuple[str, ...]
    definitions: tuple[str, ...]
    match_type: str
    score: float
    entry_type: str = "term"
    metadata: tuple[tuple[str, str], ...] = ()
    inflection_reasons: tuple[str, ...] = ()
