"""Bridge server tests.

Drives a real socket on an operating-system assigned port. The contract asserted here
is the browser extension's, read out of ``native-host.js``: we cannot change it, so
these tests are the only thing that tells us when we have broken it.
"""

from __future__ import annotations

import contextlib
import io
import json
import struct
import threading
import time
import unittest
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from anki_lookup.translation.bridge_server import (
    BRIDGE_PROTOCOL,
    EXTENSION_FAILURE,
    MAX_BODY_BYTES,
    BridgeHTTPServer,
    create_bridge_server,
    is_authorized,
    job_id_for,
    parse_wait_seconds,
    probe_bridge,
)
from anki_lookup.translation.broker import JobBroker
from anki_lookup.translation.models import JobOutcome


class FakeHeaders:
    def __init__(self, headers: dict[str, str]) -> None:
        self._headers = headers

    def items(self) -> Any:
        return self._headers.items()


class AuthorizationTests(unittest.TestCase):
    def test_a_loopback_host_is_allowed(self) -> None:
        for host in ("127.0.0.1:8791", "localhost:8791", "[::1]:8791"):
            with self.subTest(host=host):
                self.assertTrue(is_authorized(FakeHeaders({"Host": host})))

    def test_a_request_without_a_host_is_refused(self) -> None:
        self.assertFalse(is_authorized(FakeHeaders({"Accept": "application/json"})))

    def test_a_rebound_dns_name_is_refused(self) -> None:
        self.assertFalse(is_authorized(FakeHeaders({"Host": "evil.example.com:8791"})))

    def test_any_fetch_metadata_header_means_a_browser_sent_it(self) -> None:
        # Our client is a plain Node http.request and sends none of these. A browser
        # attaches them to every request it makes, loopback subresources included.
        for field in ("Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-Dest"):
            with self.subTest(field=field):
                headers = FakeHeaders({"Host": "127.0.0.1:8791", field: "cross-site"})

                self.assertFalse(is_authorized(headers))

    def test_a_non_empty_origin_is_refused(self) -> None:
        headers = FakeHeaders({"Host": "127.0.0.1:8791", "Origin": "https://example.com"})

        self.assertFalse(is_authorized(headers))

    def test_an_empty_origin_is_tolerated(self) -> None:
        headers = FakeHeaders({"Host": "127.0.0.1:8791", "Origin": "  "})

        self.assertTrue(is_authorized(headers))

    def test_header_names_are_matched_case_insensitively(self) -> None:
        self.assertFalse(
            is_authorized(FakeHeaders({"host": "127.0.0.1:8791", "sec-fetch-site": "same-site"}))
        )


class JobIdTests(unittest.TestCase):
    def test_extracts_the_job_id(self) -> None:
        self.assertEqual(job_id_for("/v1/translation/jobs/job-7/complete", "/complete"), "job-7")
        self.assertEqual(job_id_for("/v1/translation/jobs/job-7/fail", "/fail"), "job-7")

    def test_an_empty_id_does_not_match(self) -> None:
        self.assertEqual(job_id_for("/v1/translation/jobs//complete", "/complete"), "")

    def test_a_path_without_the_suffix_does_not_match(self) -> None:
        self.assertEqual(job_id_for("/v1/translation/jobs/job-7", "/complete"), "")

    def test_a_foreign_path_does_not_match(self) -> None:
        self.assertEqual(job_id_for("/v1/health", "/complete"), "")


class WaitParsingTests(unittest.TestCase):
    def test_reads_the_clients_wait_parameter(self) -> None:
        self.assertEqual(parse_wait_seconds("wait=25"), 25.0)

    def test_clamps_out_of_range_waits(self) -> None:
        self.assertEqual(parse_wait_seconds("wait=9000"), 30.0)
        self.assertEqual(parse_wait_seconds("wait=0"), 1.0)

    def test_falls_back_when_absent_or_unparseable(self) -> None:
        self.assertEqual(parse_wait_seconds(""), 5.0)
        self.assertEqual(parse_wait_seconds("wait=soon"), 5.0)


class BridgeServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.broker = JobBroker()
        self.server = create_bridge_server(0, self.broker)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def test_health_answers_the_exact_shape_the_client_checks(self) -> None:
        status, payload, _ = _get(f"{self.base_url}/v1/health")

        self.assertEqual(status, 200)
        # The client does String(payload.protocol) === "1". A JSON number would pass
        # that by coincidence; the contract says string, so pin the type.
        self.assertIsInstance(payload["protocol"], str)
        self.assertEqual(payload["protocol"], BRIDGE_PROTOCOL)
        self.assertIn("version", payload)

    def test_health_marks_the_extension_connected(self) -> None:
        self.assertFalse(self.broker.is_connected())

        _get(f"{self.base_url}/v1/health")

        self.assertTrue(self.broker.is_connected())

    def test_an_empty_queue_answers_204_so_the_client_polls_again(self) -> None:
        status, body = _get_raw(f"{self.base_url}/v1/translation/next?wait=1")

        self.assertEqual(status, 204)
        self.assertEqual(body, b"")

    def test_a_queued_job_is_handed_out_in_camel_case(self) -> None:
        job_id = self.broker.submit("こんにちは", "ja", "en", "google-translate", lambda i, o: None)

        status, payload, _ = _get(f"{self.base_url}/v1/translation/next?wait=1")

        self.assertEqual(status, 200)
        self.assertEqual(
            payload,
            {
                "id": job_id,
                "provider": "google-translate",
                "sourceText": "こんにちは",
                "sourceLang": "ja",
                "targetLang": "en",
            },
        )

    def test_the_job_payload_satisfies_the_clients_validity_check(self) -> None:
        # native-host.js drops a job unless `id` is truthy and `sourceText` is a
        # string. A silently dropped job would look like a hung translation.
        self.broker.submit("hi", "en", "es", "deepl", lambda i, o: None)

        _, payload, _ = _get(f"{self.base_url}/v1/translation/next?wait=1")

        self.assertTrue(payload["id"])
        self.assertIsInstance(payload["sourceText"], str)

    def test_completing_a_job_settles_its_waiter(self) -> None:
        settled: list[JobOutcome] = []
        job_id = self.broker.submit(
            "こんにちは", "ja", "en", "google-translate", lambda i, o: settled.append(o)
        )
        _get(f"{self.base_url}/v1/translation/next?wait=1")

        status, payload, _ = _post(
            f"{self.base_url}/v1/translation/jobs/{job_id}/complete",
            {"translatedText": "Hello"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["accepted"])
        self.assertEqual(len(settled), 1)
        self.assertEqual(settled[0].text, "Hello")

    def test_failing_a_job_settles_its_waiter_with_the_reported_error(self) -> None:
        settled: list[JobOutcome] = []
        job_id = self.broker.submit(
            "こんにちは", "ja", "en", "google-translate", lambda i, o: settled.append(o)
        )
        _get(f"{self.base_url}/v1/translation/next?wait=1")

        _post(
            f"{self.base_url}/v1/translation/jobs/{job_id}/fail",
            {"error": "The tab was closed."},
        )

        self.assertEqual(len(settled), 1)
        self.assertFalse(settled[0].ok)
        self.assertEqual(settled[0].error, "The tab was closed.")

    def test_a_failure_without_an_error_gets_a_readable_one(self) -> None:
        settled: list[JobOutcome] = []
        job_id = self.broker.submit("hi", "en", "es", "deepl", lambda i, o: settled.append(o))
        _get(f"{self.base_url}/v1/translation/next?wait=1")

        _post(f"{self.base_url}/v1/translation/jobs/{job_id}/fail", {"error": "   "})

        self.assertEqual(settled[0].error, EXTENSION_FAILURE)

    def test_an_unknown_job_id_is_accepted_but_reported_unrecorded(self) -> None:
        # Contract: a retried post must be a harmless no-op, not an error.
        status, payload, _ = _post(
            f"{self.base_url}/v1/translation/jobs/job-does-not-exist/complete",
            {"translatedText": "Hello"},
        )

        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["accepted"])

    def test_an_oversized_body_is_refused(self) -> None:
        status, _ = _post_raw(
            f"{self.base_url}/v1/translation/jobs/job-1/complete",
            b"x" * (MAX_BODY_BYTES + 1),
        )

        self.assertEqual(status, 413)

    def test_a_browser_request_is_refused(self) -> None:
        status, _ = _get_raw(
            f"{self.base_url}/v1/translation/next?wait=1",
            headers={"Sec-Fetch-Site": "cross-site"},
        )

        self.assertEqual(status, 403)

    def test_a_browser_request_cannot_steal_a_job(self) -> None:
        # The point of the Fetch Metadata check: an <img> tag pointed at the poll
        # route would otherwise pop a job the user is waiting on.
        self.broker.submit("こんにちは", "ja", "en", "google-translate", lambda i, o: None)

        _get_raw(
            f"{self.base_url}/v1/translation/next?wait=1",
            headers={"Sec-Fetch-Dest": "image"},
        )

        self.assertEqual(self.broker.pending_count(), 1)

    def test_a_request_with_an_origin_is_refused(self) -> None:
        status, _ = _get_raw(
            f"{self.base_url}/v1/health",
            headers={"Origin": "https://example.com"},
        )

        self.assertEqual(status, 403)

    def test_unknown_routes_are_rejected(self) -> None:
        get_status, _ = _get_raw(f"{self.base_url}/health")
        post_status, _ = _post_raw(f"{self.base_url}/v1/translation/jobs", b"{}")

        self.assertEqual(get_status, 404)
        self.assertEqual(post_status, 404)

    def test_probing_recognises_our_own_bridge(self) -> None:
        payload = probe_bridge(self.port)

        self.assertEqual(payload.get("protocol"), BRIDGE_PROTOCOL)
        self.assertEqual(payload.get("name"), "anki-lookup")

    def test_probing_an_empty_port_reports_nothing(self) -> None:
        self.assertEqual(probe_bridge(_free_port()), {})


#: How long to let a socket-level event actually happen. These tests coordinate with a
#: real server thread through a real socket, so there is no event to wait on — only a
#: settle. Generous enough that a false pass would require the server not to react to a
#: condition-variable notify within half a second, which would be a bug in itself.
SETTLE_SECONDS = 0.1


class DisconnectTests(unittest.TestCase):
    """Reproduces the failure seen in real use.

    The extension's long poll can be parked for 25 seconds; the client going away in
    that window is routine. Before this was handled it produced two distinct symptoms:
    an Anki error report (socketserver printed the traceback to stderr, which Anki
    reads as a crash), and a translation that appeared to do nothing for over two
    minutes before a browser tab suddenly opened — the job had left the queue, reached
    nobody, and sat claimed until the lease expired.
    """

    def setUp(self) -> None:
        self.broker = JobBroker()
        self.server = create_bridge_server(0, self.broker)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self._stop)

    def _stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def _park_poll_then_hang_up(self) -> None:
        """Park a long poll on the server, then kill the client under it.

        The ordering is the whole point, and it mirrors what actually happens: the
        extension parks a poll for up to 25 seconds, dies in that window, and a job
        arrives afterwards. Parking first also makes the test deterministic — a client
        that connects and RSTs immediately usually dies while the server is still
        *reading the request*, so no job is ever claimed and the test would pass
        without proving anything.
        """

        import socket as socket_module

        client = socket_module.socket()
        client.connect(("127.0.0.1", self.port))
        client.sendall(
            b"GET /v1/translation/next?wait=5 HTTP/1.0\r\n"
            b"Host: 127.0.0.1\r\n"
            b"Accept: application/json\r\n\r\n"
        )

        # claim_next touches last-seen the moment it is entered, so this tells us the
        # request was fully read and the poll is genuinely parked.
        self.assertTrue(
            self._wait_for(self.broker.is_connected),
            "the server never parked the long poll",
        )

        # Force an RST rather than a graceful FIN: that is what a killed client
        # produces, and what raised ConnectionResetError in the wild.
        client.setsockopt(
            socket_module.SOL_SOCKET,
            socket_module.SO_LINGER,
            struct.pack("ii", 1, 0),
        )
        client.close()

        # Let the reset actually land. Without this the server's write can still
        # succeed into a socket buffer and the disconnect goes unnoticed, which makes
        # every assertion below depend on timing.
        time.sleep(SETTLE_SECONDS)

    def _wait_for(self, predicate: Callable[[], bool], timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()

    def _submit(self, on_settled: Callable[[str, JobOutcome], None]) -> str:
        return self.broker.submit("こんにちは", "ja", "en", "google-translate", on_settled)

    def _submit_and_settle(self, on_settled: Callable[[str, JobOutcome], None]) -> str:
        """Submit, then wait for the parked poll to wake, claim, and fail to deliver.

        Sampled once at the end rather than polled: a job is legitimately pending for
        a few microseconds between submit and claim, and polling for "pending == 1"
        catches that flicker and passes whether or not the release ever happens.
        """

        job_id = self._submit(on_settled)
        time.sleep(SETTLE_SECONDS * 5)
        return job_id

    def test_a_client_that_hangs_up_does_not_lose_the_job(self) -> None:
        settled: list[JobOutcome] = []
        self._park_poll_then_hang_up()

        # Submitted only now, so the parked poll wakes, pops the job, and fails to
        # write it to a socket that is already gone. That is the exact path that lost
        # the job in real use.
        self._submit_and_settle(lambda i, o: settled.append(o))

        # Back in the queue, not stranded in `claimed` until the 135s lease.
        self.assertEqual(self.broker.pending_count(), 1, "the job was not returned to the queue")
        self.assertEqual(self.broker.claimed_count(), 0, "the job is still held by a dead client")
        # And still waiting for its answer: the handover failed, the caller did not.
        self.assertEqual(settled, [])
        self.assertEqual(self.broker.waiting_count(), 1)

    def test_the_job_is_delivered_to_the_next_client(self) -> None:
        self._park_poll_then_hang_up()
        job_id = self._submit_and_settle(lambda i, o: None)

        status, payload, _ = _get(f"http://127.0.0.1:{self.port}/v1/translation/next?wait=1")

        self.assertEqual(status, 200)
        self.assertEqual(payload["id"], job_id)

    def test_a_disconnect_mid_delivery_writes_nothing_to_stderr(self) -> None:
        # Anki treats anything on stderr as an add-on crash and shows the user an error
        # report. This is the path guarded by the do_GET wrapper: the request was read,
        # the job was claimed, and the write is what failed.
        captured = io.StringIO()

        with contextlib.redirect_stderr(captured):
            self._park_poll_then_hang_up()
            self._submit_and_settle(lambda i, o: None)

        self.assertEqual(captured.getvalue(), "")

    def test_a_reset_before_the_request_is_read_writes_nothing_to_stderr(self) -> None:
        # A different path, and the one that produced the traceback in the wild: the
        # client resets before the server has read the request line, so the error is
        # raised inside handle_one_request, where no handler-level guard can reach it.
        # Only the handle_error override covers this.
        import socket as socket_module

        captured = io.StringIO()

        with contextlib.redirect_stderr(captured):
            for _ in range(5):
                client = socket_module.socket()
                client.connect(("127.0.0.1", self.port))
                client.setsockopt(
                    socket_module.SOL_SOCKET,
                    socket_module.SO_LINGER,
                    struct.pack("ii", 1, 0),
                )
                client.close()
            time.sleep(SETTLE_SECONDS * 3)

        self.assertEqual(captured.getvalue(), "")

    def test_the_server_keeps_serving_after_a_disconnect(self) -> None:
        self._park_poll_then_hang_up()
        self._submit_and_settle(lambda i, o: None)

        status, payload, _ = _get(f"http://127.0.0.1:{self.port}/v1/health")

        self.assertEqual(status, 200)
        self.assertEqual(payload["protocol"], BRIDGE_PROTOCOL)


class ExclusiveBindTests(unittest.TestCase):
    """The regression guard for the Windows SO_REUSEADDR hazard.

    http.server sets allow_reuse_address = 1. On Windows that behaves like POSIX
    SO_REUSEPORT: two processes bind the same port and the OS splits connections
    between them nondeterministically. With the default, starting Anki while the
    desktop app held 8791 would not raise — it would silently shadow it. This test is
    what keeps allow_reuse_address = False in place.
    """

    def test_the_server_does_not_reuse_an_address(self) -> None:
        self.assertFalse(BridgeHTTPServer.allow_reuse_address)

    def test_binding_a_held_port_raises_rather_than_shadowing_it(self) -> None:
        broker = JobBroker()
        first = create_bridge_server(0, broker)
        self.addCleanup(first.server_close)
        port = int(first.server_address[1])

        with self.assertRaises(OSError):
            create_bridge_server(port, broker)


def _free_port() -> int:
    import socket

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _get(url: str) -> tuple[int, dict[str, Any], dict[str, str]]:
    status, body = _get_raw(url)
    return status, json.loads(body), {}


def _get_raw(url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, method="GET", headers=headers or {})
    return _send(request)


def _post(url: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any], dict[str, str]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    status, raw = _post_raw(url, body)
    return status, json.loads(raw), {}


def _post_raw(url: str, body: bytes) -> tuple[int, bytes]:
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return _send(request)


def _send(request: urllib.request.Request) -> tuple[int, bytes]:
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


if __name__ == "__main__":
    unittest.main()
