"""Per-provider target language tests.

The asymmetry between the two lists is the whole point of this module, so it is
pinned here rather than left to be discovered at translate time.
"""

from __future__ import annotations

import unittest

from anki_lookup.translation.languages import (
    DEEPL_TARGET_LANGUAGES,
    GOOGLE_TARGET_LANGUAGES,
    normalize_target_language,
    target_language_label,
    target_languages_for,
)
from anki_lookup.translation.models import ALLOWED_PROVIDERS


class TargetLanguageTests(unittest.TestCase):
    def test_neither_provider_list_is_a_superset_of_the_other(self) -> None:
        # If this ever passes, the provider-aware re-check below is dead code and the
        # two lists could be collapsed. Norwegian is the live example: "no" for
        # Google, "nb" for DeepL, which rejects "NO".
        google = {code for code, _ in GOOGLE_TARGET_LANGUAGES}
        deepl = {code for code, _ in DEEPL_TARGET_LANGUAGES}

        self.assertTrue(deepl - google, "DeepL has no code Google lacks")
        self.assertTrue(google - deepl, "Google has no code DeepL lacks")
        self.assertIn("no", google - deepl)
        self.assertIn("nb", deepl - google)

    def test_auto_is_not_a_target_for_either_provider(self) -> None:
        for provider in ALLOWED_PROVIDERS:
            with self.subTest(provider=provider):
                codes = {code for code, _ in target_languages_for(provider)}
                self.assertNotIn("auto", codes)

    def test_deepl_uses_bare_codes_not_regional_variants(self) -> None:
        # The extension maps en -> EN-US and pt -> PT-PT itself and upper-cases the
        # rest, so regional variants here would be double-mapped and rejected.
        codes = {code for code, _ in DEEPL_TARGET_LANGUAGES}

        self.assertIn("en", codes)
        self.assertIn("pt", codes)
        self.assertNotIn("en-us", codes)
        self.assertNotIn("pt-pt", codes)

    def test_every_code_is_lowercase(self) -> None:
        # The extension interpolates these into a provider URL verbatim.
        for provider in ALLOWED_PROVIDERS:
            for code, _ in target_languages_for(provider):
                with self.subTest(provider=provider, code=code):
                    self.assertEqual(code, code.lower())

    def test_normalizing_trims_and_lowercases(self) -> None:
        self.assertEqual(normalize_target_language("  JA  ", "google-translate"), "ja")

    def test_a_code_the_provider_rejects_falls_back_to_english(self) -> None:
        self.assertEqual(normalize_target_language("no", "deepl"), "en")
        self.assertEqual(normalize_target_language("no", "google-translate"), "no")

    def test_a_code_no_provider_knows_falls_back_to_english(self) -> None:
        self.assertEqual(normalize_target_language("klingon", "google-translate"), "en")
        self.assertEqual(normalize_target_language("", "deepl"), "en")

    def test_values_that_are_not_strings_fall_back_to_english(self) -> None:
        self.assertEqual(normalize_target_language(None, "google-translate"), "en")
        self.assertEqual(normalize_target_language(42, "google-translate"), "en")

    def test_labels_resolve_per_provider(self) -> None:
        self.assertEqual(target_language_label("nb", "deepl"), "Norwegian Bokmal")
        self.assertEqual(target_language_label("no", "google-translate"), "Norwegian")

    def test_an_unknown_label_falls_back_to_the_code(self) -> None:
        self.assertEqual(target_language_label("klingon", "deepl"), "klingon")


if __name__ == "__main__":
    unittest.main()
