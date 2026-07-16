"""Bridge lifecycle tests.

The interesting cases are all about who owns port 8791, because only one process can
and the extension cannot be pointed anywhere else.
"""

from __future__ import annotations

import socket
import threading
import unittest
from pathlib import Path

from dictionary_helpers import artifact_path

from anki_lookup.translation.bridge_server import (
    BOUND,
    DISABLED,
    FOREIGN_BRIDGE,
    PORT_CONFLICT,
    create_bridge_server,
)
from anki_lookup.translation.broker import JobBroker
from anki_lookup.translation.controller import (
    DISABLED_REASON,
    DISCONNECTED_REASON,
    FOREIGN_BRIDGE_REASON,
    PORT_CONFLICT_REASON,
    BridgeController,
)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class BridgeControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cache_path = artifact_path("controller_cache.sqlite3")
        _remove_database(self.cache_path)
        self.addCleanup(_remove_database, self.cache_path)

    def _controller(self, port: int) -> BridgeController:
        controller = BridgeController(self.cache_path, port=port)
        self.addCleanup(controller.stop)
        return controller

    def test_it_does_nothing_until_started(self) -> None:
        # The whole point of the default: installing the add-on must not touch the
        # port the desktop app wants.
        controller = self._controller(_free_port())

        status = controller.status()

        self.assertEqual(status.mode, DISABLED)
        self.assertEqual(controller.unavailable_reason(), DISABLED_REASON)
        self.assertFalse(controller.is_ready())

    def test_it_binds_a_free_port(self) -> None:
        controller = self._controller(_free_port())

        controller.start()

        self.assertEqual(controller.status().mode, BOUND)

    def test_a_bound_bridge_is_not_ready_until_the_extension_polls(self) -> None:
        controller = self._controller(_free_port())
        controller.start()

        self.assertEqual(controller.unavailable_reason(), DISCONNECTED_REASON)

        controller.broker.touch_last_seen()

        self.assertEqual(controller.unavailable_reason(), "")
        self.assertTrue(controller.is_ready())

    def test_it_recognises_another_translation_bridge_on_the_port(self) -> None:
        # The common case: the Wonder of U desktop app is already running. We must
        # leave its port alone and say so, not fight it for the extension.
        port = _free_port()
        rival = create_bridge_server(port, JobBroker())
        rival_thread = threading.Thread(target=rival.serve_forever, daemon=True)
        rival_thread.start()
        self.addCleanup(rival_thread.join, 5)
        self.addCleanup(rival.server_close)
        self.addCleanup(rival.shutdown)

        controller = self._controller(port)
        controller.start()

        status = controller.status()
        self.assertEqual(status.mode, FOREIGN_BRIDGE)
        self.assertEqual(controller.unavailable_reason(), FOREIGN_BRIDGE_REASON)
        self.assertEqual(status.peer_name, "anki-lookup")

    def test_it_reports_a_port_held_by_something_that_is_not_a_bridge(self) -> None:
        port = _free_port()
        squatter = socket.socket()
        squatter.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        squatter.bind(("127.0.0.1", port))
        squatter.listen(1)
        self.addCleanup(squatter.close)

        controller = self._controller(port)
        controller.start()

        status = controller.status()
        self.assertEqual(status.mode, PORT_CONFLICT)
        self.assertEqual(controller.unavailable_reason(), PORT_CONFLICT_REASON)
        self.assertEqual(status.peer_name, "")

    def test_the_four_unavailable_reasons_are_distinct(self) -> None:
        # They have four different fixes. Collapsing them into one "unavailable"
        # message would make "Wonder of U is open" look identical to "something is
        # broken".
        reasons = {
            DISABLED_REASON,
            FOREIGN_BRIDGE_REASON,
            PORT_CONFLICT_REASON,
            DISCONNECTED_REASON,
        }

        self.assertEqual(len(reasons), 4)

    def test_stopping_releases_the_port(self) -> None:
        port = _free_port()
        controller = self._controller(port)
        controller.start()
        self.assertEqual(controller.status().mode, BOUND)

        controller.stop()

        self.assertEqual(controller.status().mode, DISABLED)
        # If the port were still held, this would raise.
        successor = self._controller(port)
        successor.start()
        self.assertEqual(successor.status().mode, BOUND)

    def test_starting_twice_is_harmless(self) -> None:
        controller = self._controller(_free_port())

        controller.start()
        controller.start()

        self.assertEqual(controller.status().mode, BOUND)

    def test_stopping_without_starting_is_harmless(self) -> None:
        controller = self._controller(_free_port())

        controller.stop()

        self.assertEqual(controller.status().mode, DISABLED)

    def test_following_the_setting_starts_and_stops(self) -> None:
        controller = self._controller(_free_port())

        controller.apply_enabled(True)
        self.assertEqual(controller.status().mode, BOUND)

        controller.apply_enabled(False)
        self.assertEqual(controller.status().mode, DISABLED)


def _remove_database(path: Path) -> None:
    path.unlink(missing_ok=True)
    path.with_suffix(path.suffix + "-shm").unlink(missing_ok=True)
    path.with_suffix(path.suffix + "-wal").unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
