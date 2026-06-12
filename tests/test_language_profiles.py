import unittest

from anki_lookup.language.english import EnglishLanguageProfile
from anki_lookup.language.generic import GenericLanguageProfile
from anki_lookup.language.japanese import JapaneseLanguageProfile
from anki_lookup.language.registry import LanguageProfileRegistry


class GenericLanguageProfileTests(unittest.TestCase):
    def test_normalizes_width_case_and_whitespace(self) -> None:
        profile = GenericLanguageProfile()

        fullwidth_hello = "\uff28\uff25\uff2c\uff2c\uff2f"
        self.assertEqual(profile.normalize(f"  {fullwidth_hello}   World "), "hello world")

    def test_preserves_non_latin_text(self) -> None:
        profile = GenericLanguageProfile()

        self.assertEqual(profile.normalize("日本語"), "日本語")

    def test_detects_right_to_left_text(self) -> None:
        profile = GenericLanguageProfile()

        self.assertEqual(profile.text_direction("مرحبا"), "rtl")
        self.assertEqual(profile.text_direction("hello"), "ltr")

    def test_registry_falls_back_to_generic(self) -> None:
        registry = LanguageProfileRegistry()

        self.assertIs(registry.for_language("unknown"), registry.generic)

    def test_japanese_continuative_form_expands_to_dictionary_form(self) -> None:
        candidates = JapaneseLanguageProfile().expand_query("はがし")

        self.assertTrue(
            any(
                candidate.term == "はがす" and candidate.required_rules == frozenset({"v5s"})
                for candidate in candidates
            )
        )

    def test_japanese_polite_forms_restore_godan_dictionary_endings(self) -> None:
        profile = JapaneseLanguageProfile()

        self.assertIn(
            "はがす",
            {candidate.term for candidate in profile.expand_query("はがしました")},
        )
        self.assertIn(
            "書く",
            {candidate.term for candidate in profile.expand_query("書きません")},
        )

    def test_english_inflections_expand_to_dictionary_forms(self) -> None:
        profile = EnglishLanguageProfile()

        self.assertIn("car", {candidate.term for candidate in profile.expand_query("cars")})
        self.assertIn("run", {candidate.term for candidate in profile.expand_query("running")})

    def test_registry_detects_japanese_and_english_text(self) -> None:
        registry = LanguageProfileRegistry()

        self.assertIsInstance(registry.for_text("はがし"), JapaneseLanguageProfile)
        self.assertIsInstance(registry.for_text("running"), EnglishLanguageProfile)


if __name__ == "__main__":
    unittest.main()
