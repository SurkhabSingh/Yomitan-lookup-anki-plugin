import unittest
from types import SimpleNamespace
from unittest.mock import patch

import anki_lookup.hooks as hooks


class HookRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        hooks._registered = False

    def test_hooks_are_registered_once(self) -> None:
        fake_hooks = SimpleNamespace(
            webview_will_set_content=[],
            webview_did_receive_js_message=[],
        )

        hooks.register_hooks(fake_hooks)
        hooks.register_hooks(fake_hooks)

        self.assertEqual(fake_hooks.webview_will_set_content, [hooks.on_webview_will_set_content])
        self.assertEqual(
            fake_hooks.webview_did_receive_js_message,
            [hooks.on_webview_did_receive_js_message],
        )

    def test_bridge_returns_longest_matching_japanese_candidate(self) -> None:
        service = SimpleNamespace(lookup_candidates=lambda candidates, fallback: ("くるま", []))
        message = (
            'anki_lookup:{"action":"lookup","request_id":2,"term":"くる",'
            '"candidates":["くるま","くる","く"]}'
        )

        with (
            patch.object(hooks, "_is_reviewer", return_value=True),
            patch.object(hooks, "dictionary_service", return_value=service),
        ):
            handled, result = hooks.on_webview_did_receive_js_message(
                (False, None),
                message,
                object(),
            )

        self.assertTrue(handled)
        self.assertEqual(result["term"], "くるま")


if __name__ == "__main__":
    unittest.main()
