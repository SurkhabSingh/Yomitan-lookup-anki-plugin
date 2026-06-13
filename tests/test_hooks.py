import unittest
from types import SimpleNamespace
from unittest.mock import patch

import anki_lookup.hooks as hooks
from anki_lookup.config import runtime_config


class HookRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        hooks._registered = False
        hooks._frequency_sort_policy = None

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
        service = SimpleNamespace(
            lookup_candidates=lambda candidates, fallback, **_kwargs: ("くるま", [])
        )
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

    def test_bridge_uses_cached_frequency_sort_policy(self) -> None:
        captured = {}

        def lookup_candidates(candidates, fallback, **kwargs):
            captured.update(kwargs)
            return fallback, []

        hooks.apply_runtime_config(
            runtime_config(
                {
                    "lookup": {
                        "frequency_sort_dictionary_id": 73,
                        "frequency_sort_order": "descending",
                    }
                }
            )
        )
        service = SimpleNamespace(lookup_candidates=lookup_candidates)

        with (
            patch.object(hooks, "_is_reviewer", return_value=True),
            patch.object(hooks, "dictionary_service", return_value=service),
        ):
            hooks.on_webview_did_receive_js_message(
                (False, None),
                'anki_lookup:{"action":"lookup","request_id":3,"term":"test"}',
                object(),
            )

        policy = captured["frequency_sort"]
        self.assertEqual(policy.dictionary_id, 73)
        self.assertEqual(policy.order, "descending")


if __name__ == "__main__":
    unittest.main()
