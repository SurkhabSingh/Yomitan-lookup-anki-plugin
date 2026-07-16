"""Webview push encoding tests.

The push channel builds a JavaScript expression out of provider-supplied text — a
translation comes from a web page by way of a browser extension — so the encoding is
the boundary that keeps that text data rather than code.
"""

from __future__ import annotations

import json
import unittest

from anki_lookup.webview_push import RECEIVER, encode_payload


class EncodePayloadTests(unittest.TestCase):
    def test_round_trips_a_payload(self) -> None:
        payload = {"status": "ready", "text": "Hello"}

        self.assertEqual(json.loads(encode_payload(payload)), payload)

    def test_a_closing_script_tag_cannot_escape_the_expression(self) -> None:
        encoded = encode_payload({"text": "</script><img src=x onerror=alert(1)>"})

        self.assertNotIn("</script>", encoded)
        self.assertIn("<\\/script>", encoded)

    def test_the_escaping_survives_a_round_trip(self) -> None:
        # The escape must be transparent to the JSON parser: <\/ is a valid escape for
        # / in JSON, so the text arrives intact.
        original = "</script>"

        self.assertEqual(json.loads(encode_payload({"text": original}))["text"], original)

    def test_line_separators_are_escaped(self) -> None:
        # U+2028 and U+2029 are legal inside a JSON string but terminate a line in
        # JavaScript, so an unescaped one would be a syntax error in the expression
        # we hand to web.eval. ensure_ascii=True escapes them for free.
        #
        # Built with chr() rather than written literally: these characters are line
        # terminators to plenty of tools (Python's own str.splitlines() among them),
        # so a literal here would be invisible on screen and fragile to every editor
        # and linter that touches this file.
        line_separator = chr(0x2028)
        paragraph_separator = chr(0x2029)
        original = f"before{line_separator}after{paragraph_separator}end"

        encoded = encode_payload({"text": original})

        self.assertNotIn(line_separator, encoded)
        self.assertNotIn(paragraph_separator, encoded)
        self.assertIn("u2028", encoded)
        self.assertEqual(json.loads(encoded)["text"], original)

    def test_non_ascii_text_survives(self) -> None:
        encoded = encode_payload({"text": "日本語のテキスト"})

        self.assertEqual(json.loads(encoded)["text"], "日本語のテキスト")

    def test_quotes_and_backslashes_are_escaped(self) -> None:
        original = 'He said "hi" \\ then left'

        self.assertEqual(json.loads(encode_payload({"text": original}))["text"], original)

    def test_the_receiver_call_is_guarded_against_a_reloaded_page(self) -> None:
        # The page can be replaced between submitting a translation and settling it,
        # taking the receiver with it. The && short-circuit is what stops that being a
        # ReferenceError in the console on every card change.
        script = f"{RECEIVER} && {RECEIVER}({encode_payload({'a': 1})});"

        self.assertTrue(script.startswith("window.AnkiLookupPushResult &&"))


if __name__ == "__main__":
    unittest.main()
