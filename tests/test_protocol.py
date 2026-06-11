import json
import unittest

from anki_lookup.protocol import (
    MESSAGE_PREFIX,
    LookupRequest,
    parse_lookup_message,
    placeholder_result,
)


class ProtocolTests(unittest.TestCase):
    def test_ignores_other_message_namespaces(self) -> None:
        self.assertIsNone(parse_lookup_message("other-addon:lookup"))

    def test_parses_and_normalizes_lookup_request(self) -> None:
        payload = json.dumps({"action": "lookup", "request_id": 7, "term": "  hello   world "})

        request = parse_lookup_message(f"{MESSAGE_PREFIX}{payload}")

        self.assertEqual(request, LookupRequest(request_id=7, term="hello world"))

    def test_rejects_invalid_payload(self) -> None:
        with self.assertRaises(ValueError):
            parse_lookup_message(
                f'{MESSAGE_PREFIX}{{"action":"lookup","request_id":true,"term":"word"}}'
            )

    def test_placeholder_result_preserves_request_identity(self) -> None:
        result = placeholder_result(LookupRequest(request_id=9, term="example"))

        self.assertEqual(result["request_id"], 9)
        self.assertEqual(result["term"], "example")
        self.assertEqual(result["status"], "ready")
        self.assertGreater(len(result["definitions"]), 0)


if __name__ == "__main__":
    unittest.main()
