"""Characterization tests for the local 8766 bridge.

These pin the behaviour the Wonder of U desktop app already depends on, so the
shared-helper extraction that the translation bridge needs cannot quietly change
it. They drive a real socket on an operating-system assigned port rather than the
module-level singleton on the fixed port.
"""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from dictionary_helpers import artifact_path, write_dictionary

from anki_lookup.api_server import MAX_BODY_BYTES, LocalApiServer, create_api_server
from anki_lookup.dictionary.service import DictionaryService
from anki_lookup.metadata import ADDON_NAME, VERSION


class ApiServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_path = artifact_path("api_server.sqlite3")
        self.archive_path = artifact_path("api_server.zip")
        _remove_database(self.database_path)
        self.archive_path.unlink(missing_ok=True)

        write_dictionary(
            self.archive_path,
            title="Japanese",
            terms=[["日本語", "にほんご", "", "", 10, ["Japanese language"], 1, ""]],
        )
        service = DictionaryService(self.database_path)
        service.import_archive(self.archive_path)

        self.server = create_api_server(port=0, service_factory=lambda: service)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop_server)

    def _stop_server(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        _remove_database(self.database_path)
        self.archive_path.unlink(missing_ok=True)

    @property
    def base_url(self) -> str:
        host, port = self.server.server_address[0], self.server.server_address[1]
        return f"http://{host}:{port}"

    def test_health_reports_the_addon_and_its_features(self) -> None:
        status, payload, _ = _get(f"{self.base_url}/health")

        self.assertEqual(status, 200)
        self.assertEqual(
            payload,
            {"ok": True, "addon": ADDON_NAME, "version": VERSION, "features": ["furigana"]},
        )

    def test_health_sends_the_localhost_cors_header(self) -> None:
        # The desktop app reads this bridge from a webview origin; 8791 must not
        # copy this header, which is why the two servers cannot share a helper
        # that hardcodes it.
        _, _, headers = _get(f"{self.base_url}/health")

        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://localhost")

    def test_furigana_wraps_dictionary_matches_in_ruby(self) -> None:
        status, payload, _ = _post(f"{self.base_url}/furigana", {"text": "日本語"})

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["source"], ADDON_NAME)
        self.assertIn("<ruby>日本語<rt>にほんご</rt></ruby>", payload["furiganaHtml"])

    def test_furigana_rejects_a_missing_text_field(self) -> None:
        status, payload, _ = _post(f"{self.base_url}/furigana", {"text": 42})

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("text string", payload["error"])

    def test_furigana_rejects_an_oversized_body(self) -> None:
        status, payload, _ = _post(
            f"{self.base_url}/furigana",
            {"text": "あ" * MAX_BODY_BYTES},
        )

        self.assertEqual(status, 400)
        self.assertFalse(payload["ok"])
        self.assertIn("too large", payload["error"])

    def test_unknown_routes_are_rejected(self) -> None:
        get_status, get_payload, _ = _get(f"{self.base_url}/translation/next")
        post_status, post_payload, _ = _post(f"{self.base_url}/lookup", {"text": "x"})

        self.assertEqual(get_status, 404)
        self.assertEqual(post_status, 404)
        self.assertFalse(get_payload["ok"])
        self.assertFalse(post_payload["ok"])

    def test_the_server_reuses_one_dictionary_service(self) -> None:
        self.assertIsInstance(self.server, LocalApiServer)

        calls: list[int] = []
        service = DictionaryService(self.database_path)

        def factory() -> DictionaryService:
            calls.append(1)
            return service

        self.server.service_factory = factory
        _post(f"{self.base_url}/furigana", {"text": "日本語"})
        _post(f"{self.base_url}/furigana", {"text": "日本語"})

        self.assertEqual(len(calls), 2)


def _get(url: str) -> tuple[int, dict[str, Any], dict[str, str]]:
    request = urllib.request.Request(url, method="GET")
    return _send(request)


def _post(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, str]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return _send(request)


def _send(request: urllib.request.Request) -> tuple[int, dict[str, Any], dict[str, str]]:
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            raw = response.read().decode("utf-8")
            headers = {key: value for key, value in response.headers.items()}
            return response.status, json.loads(raw), headers
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8")
        headers = {key: value for key, value in error.headers.items()}
        return error.code, json.loads(raw), headers


def _remove_database(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.with_suffix(path.suffix + "-shm").unlink(missing_ok=True)
    path.with_suffix(path.suffix + "-wal").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
