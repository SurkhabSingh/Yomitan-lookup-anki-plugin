import json
import unittest

from anki_lookup.dictionary.models import (
    FrequencyInfo,
    IpaInfo,
    LookupEntry,
    PitchAccentInfo,
)
from anki_lookup.protocol import (
    MAXIMUM_TRANSLATION_LENGTH,
    MESSAGE_PREFIX,
    LookupRequest,
    lookup_result,
    parse_lookup_message,
    parse_message,
    parse_translate_cancel_payload,
    parse_translate_payload,
    translation_result,
)


class ProtocolTests(unittest.TestCase):
    def test_ignores_other_message_namespaces(self) -> None:
        self.assertIsNone(parse_lookup_message("other-addon:lookup"))

    def test_parses_and_normalizes_lookup_request(self) -> None:
        payload = json.dumps(
            {
                "action": "lookup",
                "request_id": 7,
                "term": "  hello   world ",
                "sentence": " This is   hello world. ",
                "candidates": ["hello world", "hello", "hello"],
            }
        )

        request = parse_lookup_message(f"{MESSAGE_PREFIX}{payload}")

        self.assertEqual(
            request,
            LookupRequest(
                request_id=7,
                term="hello world",
                sentence="This is hello world.",
                candidates=("hello world", "hello"),
            ),
        )

    def test_rejects_invalid_payload(self) -> None:
        with self.assertRaises(ValueError):
            parse_lookup_message(
                f'{MESSAGE_PREFIX}{{"action":"lookup","request_id":true,"term":"word"}}'
            )

    def test_routes_every_supported_action(self) -> None:
        for action in ("lookup", "translate", "translate_cancel", "open_external"):
            with self.subTest(action=action):
                parsed = parse_message(f'{MESSAGE_PREFIX}{{"action":"{action}"}}')

                assert parsed is not None
                self.assertEqual(parsed[0], action)

    def test_rejects_an_action_we_do_not_implement(self) -> None:
        with self.assertRaises(ValueError):
            parse_message(f'{MESSAGE_PREFIX}{{"action":"delete_collection"}}')

    def test_parse_message_ignores_other_namespaces(self) -> None:
        self.assertIsNone(parse_message("other-addon:whatever"))

    def test_parses_a_translate_request(self) -> None:
        request = parse_translate_payload(
            {
                "request_id": 3,
                "popup_token": "popup-2",
                "text": "  こんにちは   世界  ",
            }
        )

        self.assertEqual(request.request_id, 3)
        self.assertEqual(request.popup_token, "popup-2")
        self.assertEqual(request.text, "こんにちは 世界")

    def test_translation_text_is_capped(self) -> None:
        request = parse_translate_payload(
            {
                "request_id": 1,
                "popup_token": "popup-1",
                "text": "あ" * (MAXIMUM_TRANSLATION_LENGTH + 500),
            }
        )

        self.assertEqual(len(request.text), MAXIMUM_TRANSLATION_LENGTH)

    def test_rejects_a_translate_request_without_usable_text(self) -> None:
        for text in ("", "   ", 42, None):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_translate_payload({"request_id": 1, "popup_token": "popup-1", "text": text})

    def test_rejects_a_translate_request_without_a_usable_popup_token(self) -> None:
        # The token routes a late result back to the right popup. Without a real one,
        # a translation could be rendered into a popup that did not ask for it.
        for token in ("", "   ", 7, None, "x" * 65):
            with self.subTest(token=token), self.assertRaises(ValueError):
                parse_translate_payload({"request_id": 1, "popup_token": token, "text": "hi"})

    def test_rejects_a_translate_request_with_a_bad_request_id(self) -> None:
        for request_id in (True, -1, "3", None):
            with self.subTest(request_id=request_id), self.assertRaises(ValueError):
                parse_translate_payload(
                    {"request_id": request_id, "popup_token": "popup-1", "text": "hi"}
                )

    def test_parses_a_translate_cancel_request(self) -> None:
        request = parse_translate_cancel_payload({"request_id": 9, "popup_token": "popup-4"})

        self.assertEqual(request.request_id, 9)
        self.assertEqual(request.popup_token, "popup-4")

    def test_translation_result_carries_everything_the_popup_renders_from(self) -> None:
        result = translation_result(
            5,
            "popup-1",
            status="unavailable",
            message="Port 8791 is in use by another program.",
            provider="deepl",
            external_url="https://www.deepl.com/translator#auto/en/hi",
        )

        self.assertEqual(result["kind"], "translation")
        self.assertEqual(result["request_id"], 5)
        self.assertEqual(result["popup_token"], "popup-1")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["provider"], "deepl")
        self.assertTrue(result["external_url"])
        self.assertFalse(result["cached"])

    def test_lookup_result_preserves_request_identity(self) -> None:
        entry = LookupEntry(
            expression="example",
            reading="",
            dictionary="Synthetic",
            term_tags=("common",),
            definition_tags=(),
            definitions=("A sample.",),
            match_type="exact",
            score=1,
            frequencies=(FrequencyInfo("Frequency", 125.0, "125", "rank-based"),),
            pitch_accents=(PitchAccentInfo("Pitch", "example", 2, (1,), (3,), ("standard",)),),
            ipa=(
                IpaInfo(
                    "IPA",
                    "example",
                    "\u026a\u0261\u02c8z\u00e6mp\u0259l",
                    ("US",),
                ),
            ),
        )
        result = lookup_result(
            LookupRequest(request_id=9, term="example", sentence="An example sentence."),
            [entry],
        )

        self.assertEqual(result["request_id"], 9)
        self.assertEqual(result["term"], "example")
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["sentence"], "An example sentence.")
        self.assertEqual(result["entries"][0]["dictionary"], "Synthetic")
        self.assertEqual(result["entries"][0]["entry_type"], "term")
        self.assertEqual(result["entries"][0]["frequencies"][0]["value"], 125.0)
        self.assertEqual(result["entries"][0]["pitch_accents"][0]["position"], 2)
        self.assertEqual(
            result["entries"][0]["ipa"][0]["transcription"],
            "\u026a\u0261\u02c8z\u00e6mp\u0259l",
        )

    def test_lookup_result_has_empty_state(self) -> None:
        result = lookup_result(LookupRequest(request_id=10, term="missing"), [])

        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["entries"], [])


if __name__ == "__main__":
    unittest.main()
