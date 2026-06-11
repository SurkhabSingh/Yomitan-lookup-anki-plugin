import importlib
import inspect
import sys
import unittest


class BootstrapTests(unittest.TestCase):
    def test_package_imports_without_anki_runtime(self) -> None:
        sys.modules.pop("anki_lookup", None)

        module = importlib.import_module("anki_lookup")

        self.assertEqual(module.__name__, "anki_lookup")

    def test_initialize_returns_false_without_aqt(self) -> None:
        from anki_lookup.bootstrap import initialize

        self.assertFalse(initialize())

    def test_main_window_hook_callback_accepts_no_arguments(self) -> None:
        from anki_lookup.bootstrap import _on_main_window_did_init

        self.assertEqual(len(inspect.signature(_on_main_window_did_init).parameters), 0)


if __name__ == "__main__":
    unittest.main()
