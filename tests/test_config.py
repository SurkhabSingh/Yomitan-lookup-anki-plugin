import unittest

from anki_lookup.config import runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def test_invalid_values_fall_back_or_are_bounded(self) -> None:
        config = runtime_config(
            {
                "lookup": {
                    "modifier": "Space",
                    "release_behavior": "unknown",
                    "debounce_ms": 2,
                    "maximum_term_length": 10_000,
                },
                "appearance": {
                    "theme": "custom-script",
                    "font_family": "x" * 300,
                    "font_size_px": 200,
                    "popup_width_px": 10,
                    "popup_max_height_px": 10_000,
                },
            }
        )

        self.assertEqual(config["lookup"]["modifier"], "Shift")
        self.assertEqual(config["lookup"]["release_behavior"], "remain_open")
        self.assertEqual(config["lookup"]["debounce_ms"], 30)
        self.assertEqual(config["lookup"]["maximum_term_length"], 500)
        self.assertEqual(config["appearance"]["theme"], "system")
        self.assertEqual(len(config["appearance"]["font_family"]), 200)
        self.assertEqual(config["appearance"]["font_size_px"], 32)
        self.assertEqual(config["appearance"]["popup_width_px"], 240)
        self.assertEqual(config["appearance"]["popup_max_height_px"], 800)

    def test_unknown_keys_are_not_exposed_to_javascript(self) -> None:
        config = runtime_config({"unexpected": "value", "lookup": {"unexpected": True}})

        self.assertNotIn("unexpected", config)
        self.assertNotIn("unexpected", config["lookup"])


if __name__ == "__main__":
    unittest.main()
