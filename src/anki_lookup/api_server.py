"""Local desktop bridge for trusted Wonder of U integrations."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

from .dictionary import DictionaryService
from .furigana import render_furigana_html
from .local_http import log_request_error, read_json_body, send_json
from .metadata import ADDON_NAME, VERSION
from .runtime import dictionary_service

HOST = "127.0.0.1"
PORT = 8766
MAX_BODY_BYTES = 256 * 1024

#: The desktop app reads this bridge from a webview origin. The translation bridge on
#: 8791 is the mirror image: it refuses anything that carries an Origin at all.
CORS_ORIGIN = "http://localhost"

ServiceFactory = Callable[[], DictionaryService]

logger = logging.getLogger(__name__)
_server: ThreadingHTTPServer | None = None
_thread: threading.Thread | None = None
_lock = threading.Lock()


class LocalApiServer(ThreadingHTTPServer):
    """Threading server that carries the dictionary service its handlers need."""

    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        service_factory: ServiceFactory,
    ) -> None:
        self.service_factory = service_factory
        super().__init__(address, handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        # Same exposure as the translation bridge: socketserver's default prints the
        # traceback to stderr, and Anki turns stderr into an error report. A desktop
        # app that gives up on a furigana request must not look like a crash.
        log_request_error("furigana bridge", client_address)


def create_api_server(
    port: int = PORT,
    service_factory: ServiceFactory = dictionary_service,
) -> LocalApiServer:
    """Bind the local bridge without serving it.

    Pass port 0 to let the operating system choose a free port; the caller can then
    read the real port from ``server.server_address[1]``. Tests use this to drive the
    handler without touching the module-level singleton or the fixed port.
    """

    return LocalApiServer((HOST, port), _RequestHandler, service_factory)


def start_api_server() -> bool:
    """Start the local bridge once per Anki process."""

    global _server, _thread
    with _lock:
        if _server is not None:
            return True

        try:
            server = create_api_server()
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
            service = cast(LocalApiServer, self.server).service_factory()
            furigana_html = render_furigana_html(text, service)
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
        return read_json_body(self, MAX_BODY_BYTES)

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        send_json(self, status, payload, cors_origin=CORS_ORIGIN)
