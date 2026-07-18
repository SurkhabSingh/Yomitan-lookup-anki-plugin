import json
import unittest
from pathlib import Path

from anki_lookup.config import DEFAULT_CONFIG, runtime_config


class DefaultConfigParityTests(unittest.TestCase):
    def test_shipped_config_json_matches_default_config(self) -> None:
        # config.json is what Anki shows the user; DEFAULT_CONFIG is what the add-on
        # actually validates against. They are mirrored by hand, and _merge_known
        # silently falls back to DEFAULT_CONFIG for anything missing, so drift would
        # ship as a setting that appears editable but never takes effect.
        shipped = json.loads(_config_json_path().read_text(encoding="utf-8"))

        self.assertEqual(shipped, DEFAULT_CONFIG)


def _config_json_path() -> Path:
    return Path(__file__).parents[1] / "src" / "anki_lookup" / "config.json"


class RuntimeConfigTests(unittest.TestCase):
    def test_invalid_values_fall_back_or_are_bounded(self) -> None:
        config = runtime_config(
            {
                "lookup": {
                    "modifier": "Space",
                    "release_behavior": "unknown",
                    "selection_shortcut": "L",
                    "pin_shortcut": "Ctrl+Shift+L",
                    "debounce_ms": 2,
                    "maximum_term_length": 10_000,
                    "frequency_sort_dictionary_id": -10,
                    "frequency_sort_order": "sideways",
                },
                "appearance": {
                    "theme": "custom-script",
                    "font_family": "x" * 300,
                    "font_size_px": 200,
                    "popup_width_px": 10,
                    "popup_max_height_px": 10_000,
                    "dictionary_layout": "floating",
                },
            }
        )

        self.assertEqual(config["lookup"]["modifier"], "Shift")
        self.assertEqual(config["lookup"]["release_behavior"], "remain_open")
        self.assertEqual(config["lookup"]["selection_shortcut"], "Ctrl+Shift+L")
        self.assertEqual(config["lookup"]["pin_shortcut"], "Ctrl+Shift+K")
        self.assertEqual(config["lookup"]["debounce_ms"], 2)
        self.assertEqual(config["lookup"]["maximum_term_length"], 500)
        self.assertTrue(config["lookup"]["allow_nested_popups"])
        self.assertEqual(config["lookup"]["maximum_popup_depth"], 4)
        self.assertEqual(config["lookup"]["frequency_sort_dictionary_id"], 0)
        self.assertEqual(config["lookup"]["frequency_sort_order"], "auto")
        self.assertEqual(config["appearance"]["theme"], "system")
        self.assertEqual(len(config["appearance"]["font_family"]), 200)
        self.assertEqual(config["appearance"]["font_size_px"], 32)
        self.assertEqual(config["appearance"]["popup_width_px"], 240)
        self.assertEqual(config["appearance"]["popup_max_height_px"], 800)
        self.assertEqual(config["appearance"]["dictionary_layout"], "source_rail")

    def test_unknown_keys_are_not_exposed_to_javascript(self) -> None:
        config = runtime_config({"unexpected": "value", "lookup": {"unexpected": True}})

        self.assertNotIn("unexpected", config)
        self.assertNotIn("unexpected", config["lookup"])

    def test_kanji_click_defaults_on_and_a_non_boolean_falls_back(self) -> None:
        # A bool flag: _merge_known only accepts a value matching the default's type,
        # so a non-bool from user config is dropped and the default survives.
        self.assertTrue(runtime_config({})["lookup"]["allow_kanji_click"])
        self.assertTrue(
            runtime_config({"lookup": {"allow_kanji_click": "no"}})["lookup"]["allow_kanji_click"]
        )
        self.assertFalse(
            runtime_config({"lookup": {"allow_kanji_click": False}})["lookup"]["allow_kanji_click"]
        )

    def test_translation_defaults_keep_the_bridge_off(self) -> None:
        # Turning the bridge on binds a port the Wonder of U desktop app also wants.
        # Installing this add-on must never take that port by surprise.
        config = runtime_config({})

        self.assertFalse(config["translation"]["bridge_enabled"])

    def test_an_unknown_provider_falls_back_rather_than_reaching_the_extension(self) -> None:
        # The extension does not sanitize job.provider: an unknown non-empty string
        # fails the job instead of falling back. This clamp is what stops that.
        config = runtime_config({"translation": {"provider": "deepl-api"}})

        self.assertEqual(config["translation"]["provider"], "google-translate")

    def test_both_extension_provider_ids_are_accepted(self) -> None:
        for provider in ("google-translate", "deepl"):
            with self.subTest(provider=provider):
                config = runtime_config({"translation": {"provider": provider}})

                self.assertEqual(config["translation"]["provider"], provider)

    def test_a_target_language_the_provider_rejects_falls_back_to_english(self) -> None:
        # Norwegian is "no" for Google but "nb" for DeepL, which rejects "NO".
        google = runtime_config(
            {"translation": {"provider": "google-translate", "target_language": "no"}}
        )
        deepl = runtime_config({"translation": {"provider": "deepl", "target_language": "no"}})

        self.assertEqual(google["translation"]["target_language"], "no")
        self.assertEqual(deepl["translation"]["target_language"], "en")

    def test_the_target_language_label_is_injected_for_javascript(self) -> None:
        config = runtime_config({"translation": {"provider": "deepl", "target_language": "nb"}})

        self.assertEqual(config["translation"]["target_language_label"], "Norwegian Bokmal")

    def test_the_cache_lifetime_is_bounded(self) -> None:
        self.assertEqual(
            runtime_config({"translation": {"cache_ttl_hours": 10_000_000}})["translation"][
                "cache_ttl_hours"
            ],
            8_760,
        )
        self.assertEqual(
            runtime_config({"translation": {"cache_ttl_hours": -5}})["translation"][
                "cache_ttl_hours"
            ],
            0,
        )
        self.assertEqual(
            runtime_config({"translation": {"cache_ttl_hours": "forever"}})["translation"][
                "cache_ttl_hours"
            ],
            168,
        )

    def test_a_non_boolean_bridge_flag_does_not_enable_the_bridge(self) -> None:
        for value in ("true", 1, "yes"):
            with self.subTest(value=value):
                config = runtime_config({"translation": {"bridge_enabled": value}})

                self.assertFalse(config["translation"]["bridge_enabled"])

    def test_the_bridge_can_be_turned_on(self) -> None:
        config = runtime_config({"translation": {"bridge_enabled": True}})

        self.assertTrue(config["translation"]["bridge_enabled"])

    def test_normalizes_valid_shortcuts(self) -> None:
        config = runtime_config(
            {
                "lookup": {
                    "selection_shortcut": "ctrl+alt+s",
                    "pin_shortcut": "shift+p",
                    "frequency_sort_dictionary_id": 42,
                    "frequency_sort_order": "descending",
                }
            }
        )

        self.assertEqual(config["lookup"]["selection_shortcut"], "Ctrl+Alt+S")
        self.assertEqual(config["lookup"]["pin_shortcut"], "Shift+P")
        self.assertEqual(config["lookup"]["frequency_sort_dictionary_id"], 42)
        self.assertEqual(config["lookup"]["frequency_sort_order"], "descending")


if __name__ == "__main__":
    unittest.main()
