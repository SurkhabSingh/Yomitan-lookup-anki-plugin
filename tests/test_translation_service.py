"""Translation orchestration tests."""

from __future__ import annotations

import unittest
from pathlib import Path

from dictionary_helpers import artifact_path

from anki_lookup.translation.broker import MAX_QUEUE_DEPTH
from anki_lookup.translation.controller import (
    DISABLED_REASON,
    FOREIGN_BRIDGE_REASON,
    BridgeController,
)
from anki_lookup.translation.models import JobOutcome
from anki_lookup.translation.service import (
    ERROR,
    PENDING,
    READY,
    UNAVAILABLE,
    TranslationService,
)


class _StubController(BridgeController):
    """A controller whose availability we drive directly, with no sockets."""

    def __init__(self, cache_path: Path, reason: str = "") -> None:
        super().__init__(cache_path, port=0)
        self._reason = reason

    def unavailable_reason(self) -> str:
        return self._reason

    def set_reason(self, reason: str) -> None:
        self._reason = reason


class TranslationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_path = artifact_path("service_cache.sqlite3")
        _remove_database(self.cache_path)
        self.addCleanup(_remove_database, self.cache_path)
        self.controller = _StubController(self.cache_path)
        self.addCleanup(self.controller.stop)
        self.service = TranslationService(self.controller)
        self.settled: list[tuple[str, JobOutcome]] = []

    def _record(self, job_id: str, outcome: JobOutcome) -> None:
        self.settled.append((job_id, outcome))

    def _translate(self, text: str = "こんにちは") -> object:
        return self.service.translate(
            text=text,
            provider="google-translate",
            target_lang="en",
            cache_ttl_hours=24,
            on_settled=self._record,
        )

    def test_an_available_bridge_queues_a_job(self) -> None:
        outcome = self._translate()

        self.assertEqual(outcome.status, PENDING)
        self.assertTrue(outcome.job_id)
        self.assertEqual(self.controller.broker.pending_count(), 1)

    def test_a_cached_translation_resolves_without_the_bridge(self) -> None:
        self.controller.cache.store("google-translate", "en", "こんにちは", "Hello", 24)

        outcome = self._translate()

        self.assertEqual(outcome.status, READY)
        self.assertEqual(outcome.text, "Hello")
        self.assertTrue(outcome.cached)
        self.assertEqual(self.controller.broker.pending_count(), 0)

    def test_the_cache_answers_even_when_the_bridge_is_unavailable(self) -> None:
        # Deliberate ordering: there is no reason to punish the user with a port
        # conflict message for a sentence we already know the answer to.
        self.controller.cache.store("google-translate", "en", "こんにちは", "Hello", 24)
        self.controller.set_reason(FOREIGN_BRIDGE_REASON)

        outcome = self._translate()

        self.assertEqual(outcome.status, READY)
        self.assertEqual(outcome.text, "Hello")

    def test_an_unavailable_bridge_reports_why_and_offers_the_website(self) -> None:
        self.controller.set_reason(FOREIGN_BRIDGE_REASON)

        outcome = self._translate()

        self.assertEqual(outcome.status, UNAVAILABLE)
        self.assertEqual(outcome.message, FOREIGN_BRIDGE_REASON)
        self.assertTrue(outcome.external_url.startswith("https://translate.google.com/"))
        self.assertEqual(self.controller.broker.pending_count(), 0)

    def test_a_disabled_bridge_still_offers_the_website(self) -> None:
        self.controller.set_reason(DISABLED_REASON)

        outcome = self._translate()

        self.assertEqual(outcome.status, UNAVAILABLE)
        self.assertEqual(outcome.message, DISABLED_REASON)
        self.assertTrue(outcome.external_url)

    def test_a_full_queue_reports_an_error_with_a_way_out(self) -> None:
        for index in range(MAX_QUEUE_DEPTH):
            self._translate(f"text-{index}")

        outcome = self._translate("one too many")

        self.assertEqual(outcome.status, ERROR)
        self.assertIn("queue is full", outcome.message)
        self.assertTrue(outcome.external_url)

    def test_a_cache_ttl_of_zero_never_reuses_a_translation(self) -> None:
        self.controller.cache.store("google-translate", "en", "こんにちは", "Hello", 24)

        outcome = self.service.translate(
            text="こんにちは",
            provider="google-translate",
            target_lang="en",
            cache_ttl_hours=0,
            on_settled=self._record,
        )

        self.assertEqual(outcome.status, PENDING)

    def test_a_translation_is_cached_per_provider_and_language(self) -> None:
        self.service.store("こんにちは", "google-translate", "en", "Hello", 24)

        self.assertEqual(
            self.controller.cache.get("google-translate", "en", "こんにちは", 24),
            "Hello",
        )
        self.assertIsNone(self.controller.cache.get("deepl", "en", "こんにちは", 24))

    def test_storing_an_empty_translation_is_a_no_op(self) -> None:
        self.service.store("こんにちは", "google-translate", "en", "", 24)

        self.assertEqual(self.controller.cache.count(), 0)

    def test_a_broken_cache_does_not_break_translation(self) -> None:
        # The cache is an optimisation. If it cannot be read, the user should get a
        # slower translation, not an error.
        self.controller.cache.database_path = Path("\x00 invalid")
        self.controller.cache._initialized = False

        outcome = self._translate()

        self.assertEqual(outcome.status, PENDING)

    def test_cancelling_drops_the_job(self) -> None:
        outcome = self._translate()

        self.service.cancel(outcome.job_id)

        self.assertEqual(self.controller.broker.pending_count(), 0)

    def test_the_source_language_is_left_to_the_provider(self) -> None:
        self._translate()

        job = self.controller.broker.claim_next(wait_seconds=0)

        assert job is not None
        self.assertEqual(job.source_lang, "auto")

    def test_the_wire_provider_is_one_the_extension_accepts(self) -> None:
        self.service.translate(
            text="hi",
            provider="deepl",
            target_lang="de",
            cache_ttl_hours=24,
            on_settled=self._record,
        )

        job = self.controller.broker.claim_next(wait_seconds=0)

        assert job is not None
        self.assertIn(job.provider, ("google-translate", "deepl"))


def _remove_database(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.with_suffix(path.suffix + "-shm").unlink(missing_ok=True)
    path.with_suffix(path.suffix + "-wal").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
