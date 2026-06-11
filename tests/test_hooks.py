import unittest
from types import SimpleNamespace

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


if __name__ == "__main__":
    unittest.main()
