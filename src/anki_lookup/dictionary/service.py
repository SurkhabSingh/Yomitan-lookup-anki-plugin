"""Dictionary application service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from ..language import language_profiles
from .importer import DictionaryImportCancelled, import_dictionary
from .models import BatchImportResult, DictionaryInfo, ImportFailure, ImportResult, LookupEntry
from .normalization import normalize_term
from .repository import DictionaryRepository


class DictionaryService:
    def __init__(self, database_path: Path) -> None:
        self.repository = DictionaryRepository(database_path)

    def import_archive(
        self,
        archive_path: Path,
        should_cancel: Callable[[], bool] | None = None,
    ) -> ImportResult:
        return import_dictionary(self.repository.database_path, archive_path, should_cancel)

    def import_archives(
        self,
        archive_paths: list[Path],
        should_cancel: Callable[[], bool] | None = None,
    ) -> BatchImportResult:
        imported: list[ImportResult] = []
        failed: list[ImportFailure] = []
        cancelled = False
        for archive_path in archive_paths:
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            try:
                imported.append(self.import_archive(archive_path, should_cancel))
            except DictionaryImportCancelled:
                cancelled = True
                break
            except Exception as error:
                failed.append(ImportFailure(archive_path.name, str(error)))
        return BatchImportResult(tuple(imported), tuple(failed), cancelled)

    def list_dictionaries(self) -> list[DictionaryInfo]:
        return self.repository.list_dictionaries()

    def lookup(self, term: str, limit: int = 20) -> list[LookupEntry]:
        return self.repository.search(term, limit)

    def lookup_candidates(
        self, candidates: tuple[str, ...], fallback: str, limit: int = 20
    ) -> tuple[str, list[LookupEntry]]:
        source_candidates = tuple(dict.fromkeys(candidates or (fallback,)))
        direct_matches = self.repository.search_exact_many(source_candidates, limit)
        grouped_results: list[tuple[str, list[LookupEntry]]] = []
        seen: set[tuple[str, str, str, tuple[str, ...]]] = set()

        for source in source_candidates:
            profile = language_profiles.for_text(source)
            expansions = profile.expand_query(source)
            if not expansions:
                continue

            results: list[LookupEntry] = []
            self._extend_unique(
                results,
                seen,
                direct_matches.get(normalize_term(source), []),
                (),
                limit,
            )
            transformed = expansions[1:]
            transformed_matches = (
                self.repository.search_exact_many(
                    tuple(expansion.term for expansion in transformed),
                    limit,
                    required_rules={
                        expansion.term: expansion.required_rules
                        for expansion in transformed
                        if expansion.required_rules
                    },
                    direct_match_type="deinflected",
                    include_kanji=False,
                )
                if transformed and len(results) < limit
                else {}
            )
            for expansion in transformed:
                self._extend_unique(
                    results,
                    seen,
                    transformed_matches.get(normalize_term(expansion.term), []),
                    expansion.reasons,
                    limit,
                )
                if len(results) >= limit:
                    break
            if "en" in profile.language_codes():
                reverse_terms = [expansion.term for expansion in expansions[1:]]
                reverse_terms.append(expansions[0].term)
                for reverse_term in reverse_terms:
                    if len(results) >= limit:
                        break
                    self._extend_unique(
                        results,
                        seen,
                        [
                            entry
                            for entry in self.repository.search(reverse_term, limit)
                            if entry.match_type == "definition"
                        ],
                        (),
                        limit,
                    )
            if results:
                grouped_results.append((source, results))

        if grouped_results:
            return grouped_results[0][0], self._merge_source_groups(grouped_results, limit)

        return fallback, self.lookup(fallback, limit)

    @staticmethod
    def _merge_source_groups(
        groups: list[tuple[str, list[LookupEntry]]],
        limit: int,
    ) -> list[LookupEntry]:
        """Keep longest-source ranking while reserving a result for shorter matches."""

        merged: list[LookupEntry] = []
        for index, (_, entries) in enumerate(groups):
            available_slots = limit - len(merged)
            if available_slots <= 0:
                break
            remaining_group_count = min(
                len(groups) - index - 1,
                available_slots - 1,
            )
            available = available_slots - remaining_group_count
            if available <= 0:
                break
            merged.extend(entries[:available])
        return merged

    @staticmethod
    def _extend_unique(
        target: list[LookupEntry],
        seen: set[tuple[str, str, str, tuple[str, ...]]],
        entries: list[LookupEntry],
        reasons: tuple[str, ...],
        limit: int,
    ) -> None:
        for entry in entries:
            key = (entry.dictionary, entry.expression, entry.reading, entry.definitions)
            if key in seen:
                continue
            seen.add(key)
            target.append(replace(entry, inflection_reasons=reasons))
            if len(target) >= limit:
                return

    def set_enabled(self, dictionary_id: int, enabled: bool) -> None:
        self.repository.set_enabled(dictionary_id, enabled)

    def remove(self, dictionary_id: int) -> None:
        self.repository.remove(dictionary_id)

    def remove_many(self, dictionary_ids: list[int]) -> None:
        self.repository.remove_many(dictionary_ids)

    def move(self, dictionary_id: int, offset: int) -> None:
        self.repository.move(dictionary_id, offset)
