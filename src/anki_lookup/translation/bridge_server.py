"""The translation bridge: the server side of the browser extension's contract.

The extension's native host long-polls a local HTTP bridge for translation jobs. It
authenticates nothing — it checks only that something on the configured endpoint
answers ``GET /v1/health`` with ``{"protocol": "1"}`` — so implementing that contract
here is enough to be served, with no change to the extension or the desktop app.

**Only one process can hold port 8791.** The extension reads its endpoint from
``chrome.storage.local`` and offers no UI to change it, so there is no second port to
fall back to: if the Wonder of U desktop app has the port, this add-on cannot be
served, and vice versa. That is why the bridge is off by default (see
``config.DEFAULT_CONFIG``) and why :func:`bridge_status` reports precisely who has it.

Route contract, dictated by ``native-host.js`` and not negotiable from this side:

===================================== ======================================
``GET /v1/health``                    200 with ``protocol`` as the string "1"
``GET /v1/translation/next?wait=25``  200 with a job, or 204 for none
``POST /v1/translation/jobs/{id}/complete``  any 2xx; body not read by client
``POST /v1/translation/jobs/{id}/fail``      any 2xx
===================================== ======================================
"""

from __future__ import annotations

import json
import logging
import socket
import sys
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs

from ..local_http import (
    BodyTooLargeError,
    drain_body,
    log_request_error,
    read_json_body,
    send_empty,
    send_json,
)
from ..metadata import VERSION
from .broker import JobBroker, clamp_long_poll_seconds
from .models import JobOutcome

HOST = "127.0.0.1"

#: Not configurable, deliberately. The extension reads its endpoint from
#: chrome.storage.local, has no settings UI for it, and its sanitizer force-migrates
#: port 8766 back to 8791. A port setting here could only ever desynchronise from the
#: only value the extension will actually poll.
BRIDGE_PORT = 8791

#: The wire protocol version. A **string**: the client does
#: ``String(payload.protocol) === "1"``, and while a JSON number would coincidentally
#: pass that, the contract says string.
BRIDGE_PROTOCOL = "1"

BRIDGE_NAME = "anki-lookup"

#: Ceiling on a /complete or /fail body. A translated sentence is a few hundred bytes.
MAX_BODY_BYTES = 1024 * 1024

#: Cap on threads parked in a long poll. ThreadingHTTPServer has no worker limit, and
#: an <img src="http://127.0.0.1:8791/v1/translation/next?wait=30"> on any page the
#: user visits would otherwise park a thread for 30 seconds each. The Fetch Metadata
#: check below is the real defence; this is the backstop.
MAX_CONCURRENT_POLLS = 8

REAPER_INTERVAL_SECONDS = 1.0
REBIND_INTERVAL_SECONDS = 30.0
PROBE_TIMEOUT_SECONDS = 1.5

# Bridge modes.
DISABLED = "disabled"
BOUND = "bound"
FOREIGN_BRIDGE = "foreign_bridge"
PORT_CONFLICT = "port_conflict"

EXTENSION_FAILURE = "The extension reported a translation failure."

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BridgeStatus:
    """What the popup, the settings dialog, and diagnostics all report from."""

    mode: str
    port: int
    extension_connected: bool
    peer_name: str = ""
    peer_version: str = ""
    last_error: str = ""


class BridgeHTTPServer(ThreadingHTTPServer):
    """Threading server carrying the broker its handlers serve.

    ``allow_reuse_address = False`` is load-bearing, not tidiness.
    ``http.server.HTTPServer`` sets it to 1, and on Windows ``SO_REUSEADDR`` behaves
    like POSIX's ``SO_REUSEPORT``: two processes can bind the same address at once and
    the operating system routes connections between them nondeterministically. With
    the default we would not get ``EADDRINUSE`` when the desktop app already held
    8791 — we would silently shadow it, and translations would land in whichever
    process won each connection. A coin flip, invisible in logs, and it would break the
    *other* application.
    """

    allow_reuse_address = False
    daemon_threads = True

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        broker: JobBroker,
    ) -> None:
        self.broker = broker
        super().__init__(address, handler)

    def handle_error(self, request: Any, client_address: Any) -> None:
        log_request_error("translation bridge", client_address)

    def server_bind(self) -> None:
        # Belt and braces on Windows: SO_REUSEADDR above stops us hijacking someone
        # else, and this stops anyone hijacking us.
        exclusive = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if sys.platform == "win32" and exclusive is not None:
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, exclusive, 1)
            except OSError:
                logger.debug("SO_EXCLUSIVEADDRUSE unavailable; continuing")
        super().server_bind()


def create_bridge_server(port: int, broker: JobBroker) -> BridgeHTTPServer:
    """Bind the bridge without serving it.

    Pass port 0 to let the operating system choose a free port; tests read the real
    port back from ``server.server_address[1]``.
    """

    return BridgeHTTPServer((HOST, port), _BridgeRequestHandler, broker)


def is_authorized(headers: Any) -> bool:
    """Keep browsers off the bridge. Three checks, none of which authenticates.

    * **Fetch Metadata.** Browsers attach ``Sec-Fetch-*`` to every request they make,
      loopback subresources included. Our client is a plain Node ``http.request``,
      which sends none. So any ``Sec-Fetch-*`` header at all means a browser sent it.
    * **Origin.** Kept, but not load-bearing: ``Origin`` rides on fetch/XHR, not on
      subresource GETs, so an ``<img>`` tag arrives without one. The page could not
      read the reply anyway — but ``claim_next`` would already have popped the job,
      and the user's translation would die waiting.
    * **Host.** The usual DNS-rebinding guard: a name that resolves to 127.0.0.1 still
      arrives carrying its own ``Host``.

    What this does **not** do is prove identity. It separates "a browser sent this"
    from "a native client sent this"; any other local process can still speak the
    contract and be believed. That is the bridge's pre-existing trust boundary, shared
    with the desktop app, and closing it would need a shared secret negotiated over
    the native-messaging port — a change to the extension, which is out of scope.
    """

    host_ok = False

    for field, value in headers.items():
        name = field.lower()

        if name.startswith("sec-fetch-"):
            return False
        if name == "origin" and value.strip():
            return False
        if name == "host":
            host_ok = _hostname_of(value) in ("127.0.0.1", "localhost", "[::1]")

    return host_ok


def _hostname_of(host_header: str) -> str:
    """Strip the port from a Host header, keeping bracketed IPv6 literals intact.

    A bare ``split(":")`` turns ``[::1]:8791`` into ``[``, which quietly fails the
    loopback check. The desktop app's Rust original has exactly that bug; it is
    invisible there only because the client always connects to 127.0.0.1.
    """

    value = host_header.strip()
    if value.startswith("["):
        closing = value.find("]")
        if closing != -1:
            return value[: closing + 1]
    return value.split(":")[0]


def job_id_for(path: str, suffix: str) -> str:
    """Extract the job id from ``/v1/translation/jobs/{id}{suffix}``.

    Job ids are generated locally and contain no reserved characters, so no
    percent-decoding is required. Returns an empty string when the path does not match.
    """

    prefix = "/v1/translation/jobs/"
    if not path.startswith(prefix) or not path.endswith(suffix):
        return ""
    return path[len(prefix) : -len(suffix)]


def parse_wait_seconds(query: str) -> float:
    values = parse_qs(query).get("wait")
    if not values:
        return clamp_long_poll_seconds(None)
    try:
        return clamp_long_poll_seconds(int(values[0]))
    except (TypeError, ValueError):
        return clamp_long_poll_seconds(None)


class _BridgeRequestHandler(BaseHTTPRequestHandler):
    # Deliberately HTTP/1.0: each long poll becomes one connection and one thread that
    # dies with its response. HTTP/1.1 keep-alive would pin a thread for the whole
    # lifetime of the poller for no benefit.
    server_version = "AnkiLookupBridge/1"

    _poll_slots = threading.BoundedSemaphore(MAX_CONCURRENT_POLLS)

    @property
    def _broker(self) -> JobBroker:
        return cast(BridgeHTTPServer, self.server).broker

    def do_GET(self) -> None:
        try:
            self._do_get()
        except OSError:
            # The client went away. Nothing to report and nowhere to report it.
            logger.debug("Translation client disconnected during a GET")

    def do_POST(self) -> None:
        try:
            self._do_post()
        except OSError:
            logger.debug("Translation client disconnected during a POST")

    def _do_get(self) -> None:
        if not is_authorized(self.headers):
            send_empty(self, 403)
            return

        path, _, query = self.path.partition("?")

        if path == "/v1/health":
            self._broker.touch_last_seen()
            send_json(
                self,
                200,
                {"protocol": BRIDGE_PROTOCOL, "version": VERSION, "name": BRIDGE_NAME},
            )
            return

        if path == "/v1/translation/next":
            self._claim_next(parse_wait_seconds(query))
            return

        send_empty(self, 404)

    def _do_post(self) -> None:
        if not is_authorized(self.headers):
            send_empty(self, 403)
            return

        path, _, _ = self.path.partition("?")

        complete_id = job_id_for(path, "/complete")
        if complete_id:
            self._resolve(complete_id, complete=True)
            return

        fail_id = job_id_for(path, "/fail")
        if fail_id:
            self._resolve(fail_id, complete=False)
            return

        send_empty(self, 404)

    def _claim_next(self, wait_seconds: float) -> None:
        if not self._poll_slots.acquire(blocking=False):
            # Over the cap: answer "no job" at once rather than parking another
            # thread. A real client just polls again.
            send_empty(self, 204)
            return

        try:
            job = self._broker.claim_next(wait_seconds)
        finally:
            self._poll_slots.release()

        if job is None:
            send_empty(self, 204)
            return

        try:
            send_json(self, 200, job.as_payload())
        except OSError:
            # The client hung up between claiming and delivery — routine for a poll
            # that may have been parked for 25 seconds. The job is already out of the
            # queue, so without this it would sit claimed until the lease expired and
            # the caller would wait out that entire window for a job nobody holds.
            #
            # Accepted risk: if the write failed *after* the client read it, the job
            # is delivered twice and translated twice. Harmless — the first /complete
            # settles the waiter and the second finds none — and far better than
            # stalling the user for the length of a lease.
            self._broker.release(job.id)
            logger.debug("Translation client disconnected before job %s was delivered", job.id)

    def _resolve(self, job_id: str, complete: bool) -> None:
        try:
            payload = read_json_body(self, MAX_BODY_BYTES)
        except BodyTooLargeError:
            # Discard what the client is still sending before answering, or its write
            # fails and it never sees the 413.
            drain_body(self)
            send_empty(self, 413)
            return
        except (ValueError, UnicodeDecodeError):
            # A malformed body is not worth a 400: the client does not read our
            # response body, and the contract wants a resolve attempt regardless.
            payload = {}

        if complete:
            translated = payload.get("translatedText")
            text = translated if isinstance(translated, str) else ""
            outcome = JobOutcome.done(text)
        else:
            reported = payload.get("error")
            error = reported.strip() if isinstance(reported, str) else ""
            outcome = JobOutcome.failed(error or EXTENSION_FAILURE)

        accepted = self._broker.resolve(job_id, outcome)

        # 200 even for an id the bridge no longer knows, as the contract requires: a
        # retried post must be a harmless no-op rather than something that corrupts
        # state. `accepted` tells the client whether it was recorded — though it does
        # not read the body, so this is for humans and tests.
        send_json(self, 200, {"ok": True, "accepted": accepted})

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug("translation bridge: " + format, *args)


def probe_bridge(port: int, timeout: float = PROBE_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Ask whoever holds the port whether they are a bridge.

    Returns the parsed health payload, or an empty dict when the port is held by
    something that is not a bridge. Never raises. Must not run on the Qt main thread:
    it does network I/O, however local.
    """

    request = urllib.request.Request(
        f"http://{HOST}:{port}/v1/health",
        method="GET",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return {}
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return {}

    if not isinstance(payload, dict):
        return {}
    if str(payload.get("protocol", "")) != BRIDGE_PROTOCOL:
        return {}
    return payload
