"""Bridge lifecycle: bind if free, explain if not, and keep trying.

Owns the one broker, the one server, and the reaper thread. Everything here has to be
unraisable: it is started from ``bootstrap._on_main_window_did_init``, and an
exception escaping there would take the Tools menu actions down with it.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from .bridge_server import (
    BOUND,
    BRIDGE_PORT,
    DISABLED,
    FOREIGN_BRIDGE,
    PORT_CONFLICT,
    REAPER_INTERVAL_SECONDS,
    REBIND_INTERVAL_SECONDS,
    BridgeHTTPServer,
    BridgeStatus,
    create_bridge_server,
    probe_bridge,
)
from .broker import JobBroker
from .cache import TranslationCache

#: Reported when the port is held by the desktop app's bridge. The four unavailable
#: reasons are deliberately distinct strings: they have four different fixes, and
#: collapsing them into "translation unavailable" would make the common case
#: (Wonder of U is open) indistinguishable from the broken one.
FOREIGN_BRIDGE_REASON = "Wonder of U desktop is handling translation on port 8791."
PORT_CONFLICT_REASON = "Port 8791 is in use by another program."
DISABLED_REASON = "Translation in Anki is turned off in settings."
DISCONNECTED_REASON = "The browser extension is not connected."

logger = logging.getLogger(__name__)


class BridgeController:
    """Starts, stops, and reports on the translation bridge."""

    def __init__(self, cache_path: Path, port: int = BRIDGE_PORT) -> None:
        self._port = port
        self._broker = JobBroker()
        self._cache = TranslationCache(cache_path)
        self._lock = threading.Lock()
        self._server: BridgeHTTPServer | None = None
        self._server_thread: threading.Thread | None = None
        self._reaper_thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._enabled = False
        self._mode = DISABLED
        self._peer: dict[str, Any] = {}
        self._last_error = ""

    @property
    def broker(self) -> JobBroker:
        return self._broker

    @property
    def cache(self) -> TranslationCache:
        return self._cache

    def start(self) -> None:
        """Enable the bridge and begin trying to bind. Never raises."""

        with self._lock:
            if self._enabled:
                return
            self._enabled = True
            self._stopping.clear()

        self._try_bind()
        self._start_reaper()

    def stop(self) -> None:
        """Disable the bridge and release the port. Never raises."""

        with self._lock:
            self._enabled = False
            self._mode = DISABLED
            self._peer = {}
            server = self._server
            self._server = None

        self._stopping.set()

        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                logger.exception("Could not stop the translation bridge cleanly")

    def apply_enabled(self, enabled: bool) -> None:
        """Follow the configured setting, starting or stopping as needed."""

        if enabled:
            self.start()
        else:
            self.stop()

    def status(self) -> BridgeStatus:
        with self._lock:
            mode = self._mode
            peer = dict(self._peer)
            last_error = self._last_error

        return BridgeStatus(
            mode=mode,
            port=self._port,
            extension_connected=mode == BOUND and self._broker.is_connected(),
            peer_name=str(peer.get("name", "")),
            peer_version=str(peer.get("version", "")),
            last_error=last_error,
        )

    def unavailable_reason(self) -> str:
        """Return why translation cannot run right now, or an empty string."""

        status = self.status()
        if status.mode == DISABLED:
            return DISABLED_REASON
        if status.mode == FOREIGN_BRIDGE:
            return FOREIGN_BRIDGE_REASON
        if status.mode == PORT_CONFLICT:
            return PORT_CONFLICT_REASON
        if not status.extension_connected:
            return DISCONNECTED_REASON
        return ""

    def is_ready(self) -> bool:
        return not self.unavailable_reason()

    # -- internals --------------------------------------------------------------

    def _try_bind(self) -> None:
        """Bind the port, or work out who has it. Never raises."""

        with self._lock:
            if not self._enabled or self._server is not None:
                return

        try:
            server = create_bridge_server(self._port, self._broker)
        except OSError as error:
            self._diagnose_bind_failure(error)
            return

        thread = threading.Thread(
            target=server.serve_forever,
            name="anki-lookup-translation-bridge",
            daemon=True,
        )
        thread.start()

        with self._lock:
            self._server = server
            self._server_thread = thread
            self._mode = BOUND
            self._peer = {}
            self._last_error = ""

        logger.info("Translation bridge listening on 127.0.0.1:%s", self._port)

    def _diagnose_bind_failure(self, error: OSError) -> None:
        """Work out whether the port holder is a bridge or something unrelated.

        Runs on whichever thread called us, which is the reaper — never the main
        thread, because this does network I/O.
        """

        peer = probe_bridge(self._port)
        with self._lock:
            self._peer = peer
            self._last_error = str(error)
            self._mode = FOREIGN_BRIDGE if peer else PORT_CONFLICT

        if peer:
            logger.info(
                "Port %s is already serving a translation bridge (%s %s); leaving it alone",
                self._port,
                peer.get("name", "unknown"),
                peer.get("version", ""),
            )
        else:
            logger.warning("Port %s is in use by another program: %s", self._port, error)

    def _start_reaper(self) -> None:
        with self._lock:
            if self._reaper_thread is not None and self._reaper_thread.is_alive():
                return
            thread = threading.Thread(
                target=self._reap,
                name="anki-lookup-translation-reaper",
                daemon=True,
            )
            self._reaper_thread = thread
        thread.start()

    def _reap(self) -> None:
        """Expire leases and deadlines, and retry the bind while unbound.

        The rebind is what lets quitting the Wonder of U desktop app hand the port
        over without restarting Anki.
        """

        elapsed_since_rebind = 0.0

        while not self._stopping.wait(REAPER_INTERVAL_SECONDS):
            try:
                self._broker.tick()
            except Exception:
                logger.exception("Translation reaper tick failed")

            with self._lock:
                needs_bind = self._enabled and self._server is None

            if not needs_bind:
                elapsed_since_rebind = 0.0
                continue

            elapsed_since_rebind += REAPER_INTERVAL_SECONDS
            if elapsed_since_rebind >= REBIND_INTERVAL_SECONDS:
                elapsed_since_rebind = 0.0
                try:
                    self._try_bind()
                except Exception:
                    logger.exception("Translation bridge rebind failed")
