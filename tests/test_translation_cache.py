"""Translation cache tests."""

from __future__ import annotations

import unittest
from pathlib import Path

from dictionary_helpers import artifact_path

from anki_lookup.translation.cache import MAX_ROWS, TranslationCache


class FakeClock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class TranslationCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = artifact_path("translation_cache.sqlite3")
        _remove_database(self.database_path)
        self.clock = FakeClock()
        self.cache = TranslationCache(self.database_path, now=self.clock)
        self.addCleanup(_remove_database, self.database_path)

    def test_stores_and_returns_a_translation(self) -> None:
        self.cache.store("google-translate", "en", "こんにちは", "Hello", ttl_hours=24)

        self.assertEqual(
            self.cache.get("google-translate", "en", "こんにちは", ttl_hours=24),
            "Hello",
        )

    def test_a_miss_returns_nothing(self) -> None:
        self.assertIsNone(self.cache.get("google-translate", "en", "unknown", ttl_hours=24))

    def test_entries_are_keyed_by_provider_and_target_language(self) -> None:
        self.cache.store("google-translate", "en", "こんにちは", "Hello", ttl_hours=24)

        self.assertIsNone(self.cache.get("deepl", "en", "こんにちは", ttl_hours=24))
        self.assertIsNone(self.cache.get("google-translate", "es", "こんにちは", ttl_hours=24))

    def test_an_entry_past_its_ttl_is_not_returned(self) -> None:
        self.cache.store("google-translate", "en", "こんにちは", "Hello", ttl_hours=1)

        self.clock.advance(3_600 - 1)
        self.assertEqual(
            self.cache.get("google-translate", "en", "こんにちは", ttl_hours=1),
            "Hello",
        )

        self.clock.advance(2)
        self.assertIsNone(self.cache.get("google-translate", "en", "こんにちは", ttl_hours=1))

    def test_a_zero_ttl_turns_caching_off_entirely(self) -> None:
        self.cache.store("google-translate", "en", "こんにちは", "Hello", ttl_hours=0)

        self.assertEqual(self.cache.count(), 0)
        self.assertIsNone(self.cache.get("google-translate", "en", "こんにちは", ttl_hours=0))

    def test_restoring_the_same_key_replaces_the_translation(self) -> None:
        self.cache.store("google-translate", "en", "こんにちは", "Hello", ttl_hours=24)
        self.cache.store("google-translate", "en", "こんにちは", "Hi there", ttl_hours=24)

        self.assertEqual(self.cache.count(), 1)
        self.assertEqual(
            self.cache.get("google-translate", "en", "こんにちは", ttl_hours=24),
            "Hi there",
        )

    def test_the_row_cap_prunes_the_oldest_entries(self) -> None:
        for index in range(MAX_ROWS + 10):
            self.cache.store("google-translate", "en", f"text-{index}", f"out-{index}", 24)
            self.clock.advance(1)

        self.assertEqual(self.cache.count(), MAX_ROWS)
        self.assertIsNone(self.cache.get("google-translate", "en", "text-0", ttl_hours=24))
        self.assertEqual(
            self.cache.get("google-translate", "en", f"text-{MAX_ROWS + 9}", ttl_hours=24),
            f"out-{MAX_ROWS + 9}",
        )

    def test_clearing_removes_everything(self) -> None:
        self.cache.store("google-translate", "en", "こんにちは", "Hello", ttl_hours=24)

        self.cache.clear()

        self.assertEqual(self.cache.count(), 0)

    def test_the_database_is_created_on_demand(self) -> None:
        nested = self.database_path.parent / "nested" / "cache.sqlite3"
        nested.unlink(missing_ok=True)
        cache = TranslationCache(nested)
        self.addCleanup(_remove_database, nested)

        cache.store("deepl", "de", "hello", "hallo", ttl_hours=24)

        self.assertTrue(nested.exists())
        self.assertEqual(cache.get("deepl", "de", "hello", ttl_hours=24), "hallo")


def _remove_database(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.with_suffix(path.suffix + "-shm").unlink(missing_ok=True)
    path.with_suffix(path.suffix + "-wal").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
