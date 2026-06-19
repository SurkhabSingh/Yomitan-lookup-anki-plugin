"""Local desktop bridge for trusted Wonder of U integrations."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .furigana import render_furigana_html
from .metadata import ADDON_NAME, VERSION
from .runtime import dictionary_service

HOST = "127.0.0.1"
PORT = 8766
MAX_BODY_BYTES = 256 * 1024

logger = logging.getLogger(__name__)
_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


def start_api_server() -> bool:
    """Start the local bridge once per Anki process."""

    global _server, _thread
    with _lock:
        if _server is not None:
            return True

        try:
            server = ThreadingHTTPServer((HOST, PORT), _RequestHandler)
        except OSError:
            logger.exception("Could not start %s local bridge on %s:%s", ADDON_NAME, HOST, PORT)
            return False

        thread = threading.Thread(
            target=server.serve_forever,
            name="anki-lookup-local-api",
            daemon=True,
        )
        thread.start()
        _server = server
        _thread = thread
        logger.info("%s local bridge started on %s:%s", ADDON_NAME, HOST, PORT)
        return True


class _RequestHandler(BaseHTTPRequestHandler):
    server_version = "AnkiLookupLocalApi/1"

    def do_GET(self) -> None:
        if self.path != "/health":
            self._send_json(404, {"ok": False, "error": "Unknown endpoint."})
            return

        self._send_json(
            200,
            {
                "ok": True,
                "addon": ADDON_NAME,
                "version": VERSION,
                "features": ["furigana"],
            },
        )

    def do_POST(self) -> None:
        if self.path != "/furigana":
            self._send_json(404, {"ok": False, "error": "Unknown endpoint."})
            return

        try:
            payload = self._read_json_body()
            text = payload.get("text")
            if not isinstance(text, str):
                raise ValueError("Expected a text string.")
            furigana_html = render_furigana_html(text, dictionary_service())
        except Exception as error:
            logger.exception("Furigana request failed")
            self._send_json(400, {"ok": False, "error": str(error)})
            return

        self._send_json(
            200,
            {
                "ok": True,
                "furiganaHtml": furigana_html,
                "source": ADDON_NAME,
            },
        )

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("local bridge: " + format, *args)

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0") or "0")
        if content_length <= 0:
            return {}
        if content_length > MAX_BODY_BYTES:
            raise ValueError("Request body is too large.")

        raw_body = self.rfile.read(content_length)
        payload = json.loads(raw_body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object.")
        return payload

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://localhost")
        self.end_headers()
        self.wfile.write(body)
