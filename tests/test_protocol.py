import json
import unittest

from anki_lookup.dictionary.models import LookupEntry
from anki_lookup.protocol import (
    MESSAGE_PREFIX,
    LookupRequest,
    lookup_result,
    parse_lookup_message,
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

    def test_lookup_result_has_empty_state(self) -> None:
        result = lookup_result(LookupRequest(request_id=10, term="missing"), [])

        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["entries"], [])


if __name__ == "__main__":
    unittest.main()
