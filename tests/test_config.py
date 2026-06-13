import unittest

from anki_lookup.config import runtime_config


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
