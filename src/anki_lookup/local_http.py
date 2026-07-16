"""Helpers shared by the two local HTTP servers.

There are two, and they are deliberately not one server:

* ``api_server`` on 8766 serves the Wonder of U desktop app's furigana requests. It
  **sends** ``Access-Control-Allow-Origin`` because a webview origin reads it.
* ``translation.bridge_server`` on 8791 serves the browser extension's native host.
  It must **reject** anything carrying an ``Origin`` at all.

Opposite trust postures, so only the mechanical parts are shared. Anything that
encodes a policy stays with its own server.
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler
from typing import Any

logger = logging.getLogger(__name__)


def log_request_error(server_name: str, client_address: Any) -> None:
    """Handle a request that raised, without writing to stderr.

    ``socketserver.BaseServer.handle_error`` prints the traceback to stderr, and Anki
    treats anything on stderr as an add-on crash and shows the user an error report.
    A client hanging up mid-response is completely routine for a long-polling server,
    so the default behaviour turns normal operation into what looks like a bug.

    Connection errors are logged at debug and otherwise ignored. Anything else is a
    real defect and is logged with its traceback — to the log, where it belongs.
    """

    import sys

    error = sys.exc_info()[1]
    if isinstance(error, (ConnectionError, TimeoutError, BrokenPipeError)):
        logger.debug("%s: client disconnected (%s)", server_name, error)
        return
    logger.exception("%s: unhandled error serving %s", server_name, client_address)


class BodyTooLargeError(ValueError):
    """Raised when a request body exceeds the caller's ceiling.

    A ``ValueError`` so the 8766 server's existing catch-all keeps reporting it as a
    400; the bridge catches it by type and answers 413 instead.
    """


def read_json_body(handler: BaseHTTPRequestHandler, max_bytes: int) -> dict[str, Any]:
    """Read and parse a JSON object body, refusing anything oversized.

    The declared ``Content-Length`` is checked first so an oversized body is rejected
    before a byte is buffered, and the read is capped to that length so a lying
    client cannot make us buffer more than it declared.
    """

    content_length = int(handler.headers.get("Content-Length", "0") or "0")
    if content_length <= 0:
        return {}
    if content_length > max_bytes:
        raise BodyTooLargeError("Request body is too large.")

    raw_body = handler.rfile.read(content_length)
    payload = json.loads(raw_body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object.")
    return payload


#: Ceiling on how much of a rejected body we are willing to read and throw away so the
#: client can read our response. Comfortably above any real request; past this we let
#: the connection break instead, which is the right answer for something that is not a
#: real client anyway.
DRAIN_LIMIT_BYTES = 8 * 1024 * 1024


def drain_body(handler: BaseHTTPRequestHandler, max_bytes: int = DRAIN_LIMIT_BYTES) -> None:
    """Read and discard a body we are about to refuse.

    Without this, replying before the client has finished sending makes its write fail
    and it never reads the status: an oversized POST surfaces as a dropped connection
    rather than the 413 we actually sent. Read in chunks and discard, so refusing a
    large body still costs no memory.
    """

    remaining = int(handler.headers.get("Content-Length", "0") or "0")
    if remaining <= 0 or remaining > max_bytes:
        return

    while remaining > 0:
        chunk = handler.rfile.read(min(65_536, remaining))
        if not chunk:
            return
        remaining -= len(chunk)


def send_json(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: dict[str, Any],
    cors_origin: str = "",
) -> None:
    """Write a JSON response, optionally with a CORS header."""

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    if cors_origin:
        handler.send_header("Access-Control-Allow-Origin", cors_origin)
    handler.end_headers()
    handler.wfile.write(body)


def send_empty(handler: BaseHTTPRequestHandler, status: int) -> None:
    """Write a bodyless response.

    Used for 204, which must carry no body and no ``Content-Length``: the extension's
    long poll reads 204 as "no job, poll again".
    """

    handler.send_response(status)
    handler.end_headers()
