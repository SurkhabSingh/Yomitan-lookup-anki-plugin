"""External translator URL tests.

Driven by ``tests/fixtures/external_urls.json``, the same fixture
``tests/js/scanner-core.test.js`` reads. The Python and JavaScript builders are
separate implementations of one rule; the shared fixture is what stops them drifting.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from anki_lookup.translation.external import (
    MAX_EXTERNAL_TEXT_LENGTH,
    external_translate_url,
    is_supported_provider,
    truncate_for_external_url,
)


def _load_cases() -> list[dict[str, Any]]:
    path = Path(__file__).parent / "fixtures" / "external_urls.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = payload["cases"]
    return cases


class ExternalUrlTests(unittest.TestCase):
    def test_matches_the_shared_fixture(self) -> None:
        cases = _load_cases()
        self.assertGreater(len(cases), 0)

        for case in cases:
            with self.subTest(case=case["name"]):
                self.assertEqual(
                    external_translate_url(
                        case["provider"],
                        case["text"],
                        case["source"],
                        case["target"],
                    ),
                    case["expected"],
                )

    def test_an_unknown_provider_falls_back_to_google(self) -> None:
        # Defence in depth: config clamping should make this unreachable, but a URL
        # is harmless where a bad provider id on the wire would fail the job.
        url = external_translate_url("wonder-of-u", "hi", "auto", "en")

        self.assertTrue(url.startswith("https://translate.google.com/"))

    def test_long_text_is_truncated(self) -> None:
        text = "あ" * (MAX_EXTERNAL_TEXT_LENGTH + 500)

        self.assertEqual(len(truncate_for_external_url(text)), MAX_EXTERNAL_TEXT_LENGTH)

    def test_empty_language_codes_fall_back_rather_than_producing_a_broken_url(self) -> None:
        url = external_translate_url("google-translate", "hi", "", "")

        self.assertIn("sl=auto", url)
        self.assertIn("tl=en", url)

    def test_supported_providers_are_exactly_the_two_the_extension_accepts(self) -> None:
        self.assertTrue(is_supported_provider("google-translate"))
        self.assertTrue(is_supported_provider("deepl"))
        self.assertFalse(is_supported_provider("deepl-api"))
        self.assertFalse(is_supported_provider(""))
        self.assertFalse(is_supported_provider(None))


if __name__ == "__main__":
    unittest.main()
