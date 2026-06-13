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
    metadata_count: int = 0
    frequency_mode: str | None = None


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
class FrequencySourceInfo:
    id: int
    title: str
    revision: str
    enabled: bool
    frequency_mode: str | None


@dataclass(frozen=True)
class FrequencySortPolicy:
    dictionary_id: int
    order: str = "auto"

    def __post_init__(self) -> None:
        if self.dictionary_id <= 0:
            raise ValueError("Frequency sort dictionary ID must be positive")
        if self.order not in {"auto", "ascending", "descending"}:
            raise ValueError("Unsupported frequency sort order")


@dataclass(frozen=True)
class FrequencyInfo:
    dictionary: str
    value: float | None
    display_value: str
    frequency_mode: str | None = None


@dataclass(frozen=True)
class PitchAccentInfo:
    dictionary: str
    reading: str
    position: int | str
    nasal_positions: tuple[int, ...] = ()
    devoice_positions: tuple[int, ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class IpaInfo:
    dictionary: str
    reading: str
    transcription: str
    tags: tuple[str, ...] = ()


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
    frequencies: tuple[FrequencyInfo, ...] = ()
    pitch_accents: tuple[PitchAccentInfo, ...] = ()
    ipa: tuple[IpaInfo, ...] = ()
