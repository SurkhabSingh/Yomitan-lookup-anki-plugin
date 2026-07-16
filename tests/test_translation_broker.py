"""Broker tests.

Ported one-for-one from the desktop app's ``translation_bridge.rs`` test module,
which is the reference implementation's own spec. Where a test asserts different
behaviour to Rust, the reason is spelled out — those are the places the callback
design deliberately diverges from the blocking one.

Time is aged by swapping the injected clock. Nothing here sleeps.
"""

from __future__ import annotations

import threading
import unittest

from anki_lookup.translation.broker import (
    CLIENT_GONE_ERROR,
    CONNECTION_TTL_SECONDS,
    LEASE_TIMEOUT_SECONDS,
    MAX_LONG_POLL_SECONDS,
    MAX_QUEUE_DEPTH,
    REQUEST_TIMEOUT_SECONDS,
    TIMED_OUT_ERROR,
    JobBroker,
    QueueFullError,
    clamp_long_poll_seconds,
)
from anki_lookup.translation.models import JobOutcome


class FakeClock:
    def __init__(self) -> None:
        self.value = 1_000.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class BrokerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.clock = FakeClock()
        self.broker = JobBroker(now=self.clock)
        self.settled: list[tuple[str, JobOutcome]] = []

    def _record(self, job_id: str, outcome: JobOutcome) -> None:
        self.settled.append((job_id, outcome))

    def _submit(self, text: str = "こんにちは") -> str:
        return self.broker.submit(
            source_text=text,
            source_lang="ja",
            target_lang="en",
            provider="google-translate",
            on_settled=self._record,
        )

    def test_a_submitted_job_is_claimed_and_carries_the_wire_payload(self) -> None:
        job_id = self._submit()

        job = self.broker.claim_next(wait_seconds=0)

        assert job is not None
        self.assertEqual(job.id, job_id)
        self.assertEqual(
            job.as_payload(),
            {
                "id": job_id,
                "provider": "google-translate",
                "sourceText": "こんにちは",
                "sourceLang": "ja",
                "targetLang": "en",
            },
        )

    def test_claiming_an_empty_queue_returns_nothing(self) -> None:
        self.assertIsNone(self.broker.claim_next(wait_seconds=0))

    def test_resolving_a_job_nobody_asked_for_is_reported_unaccepted(self) -> None:
        # Rust: resolve() returns false for an id not in `waiting`. A result nobody
        # is waiting for is a duplicate post, a late one, or not ours.
        accepted = self.broker.resolve("job-nobody-asked-for", JobOutcome.done("hi"))

        self.assertFalse(accepted)
        self.assertEqual(self.settled, [])

    def test_a_completion_settles_the_waiter(self) -> None:
        job_id = self._submit()
        self.broker.claim_next(wait_seconds=0)

        accepted = self.broker.resolve(job_id, JobOutcome.done("Hello"))

        self.assertTrue(accepted)
        self.assertEqual(len(self.settled), 1)
        self.assertEqual(self.settled[0][0], job_id)
        self.assertTrue(self.settled[0][1].ok)
        self.assertEqual(self.settled[0][1].text, "Hello")

    def test_a_failure_settles_the_waiter_with_its_error(self) -> None:
        job_id = self._submit()
        self.broker.claim_next(wait_seconds=0)

        self.broker.resolve(job_id, JobOutcome.failed("The tab was closed."))

        self.assertEqual(len(self.settled), 1)
        self.assertFalse(self.settled[0][1].ok)
        self.assertEqual(self.settled[0][1].error, "The tab was closed.")

    def test_a_retried_completion_does_not_settle_twice(self) -> None:
        # Rust keeps a `results` map so first-writer-wins. Here popping the waiter is
        # itself atomic, so the second POST simply finds no waiter.
        job_id = self._submit()
        self.broker.claim_next(wait_seconds=0)

        first = self.broker.resolve(job_id, JobOutcome.done("Hello"))
        second = self.broker.resolve(job_id, JobOutcome.done("Goodbye"))

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(len(self.settled), 1)
        self.assertEqual(self.settled[0][1].text, "Hello")

    def test_a_claimed_job_survives_a_dead_client_and_is_handed_out_again(self) -> None:
        # The "job-loss bug" the Rust `claimed` map exists to fix: claim_next used to
        # pop from pending and track the job nowhere, so a client that died mid-job
        # dropped it on the floor.
        job_id = self._submit()
        first = self.broker.claim_next(wait_seconds=0)
        assert first is not None

        self.clock.advance(LEASE_TIMEOUT_SECONDS + 1)
        second = self.broker.claim_next(wait_seconds=0)

        assert second is not None
        self.assertEqual(second.id, job_id)
        self.assertEqual(self.settled, [])

    def test_after_the_last_attempt_the_caller_is_told_rather_than_looped(self) -> None:
        job_id = self._submit()

        self.broker.claim_next(wait_seconds=0)
        self.clock.advance(LEASE_TIMEOUT_SECONDS + 1)
        self.broker.claim_next(wait_seconds=0)
        self.clock.advance(LEASE_TIMEOUT_SECONDS + 1)
        third = self.broker.claim_next(wait_seconds=0)

        self.assertIsNone(third)
        self.assertEqual(len(self.settled), 1)
        self.assertEqual(self.settled[0][0], job_id)
        self.assertFalse(self.settled[0][1].ok)
        self.assertEqual(self.settled[0][1].error, CLIENT_GONE_ERROR)

    def test_an_expired_lease_for_a_cancelled_job_is_dropped_silently(self) -> None:
        job_id = self._submit()
        self.broker.claim_next(wait_seconds=0)
        self.broker.cancel(job_id)

        self.clock.advance(LEASE_TIMEOUT_SECONDS + 1)
        self.broker.expire_leases()

        self.assertEqual(self.settled, [])
        self.assertEqual(self.broker.pending_count(), 0)
        self.assertEqual(self.broker.waiting_count(), 0)

    def test_an_expired_lease_returns_the_job_to_the_queue_not_to_the_caller(self) -> None:
        # A requeued job goes back to `pending` and waits for a claim. Nothing settles
        # it in the meantime, which is exactly why the request deadline below has to
        # exist: without it a client that never comes back leaves the caller hanging.
        self._submit()
        self.broker.claim_next(wait_seconds=0)
        self.clock.advance(LEASE_TIMEOUT_SECONDS + 1)

        self.broker.expire_leases()

        self.assertEqual(self.settled, [])
        self.assertEqual(self.broker.pending_count(), 1)

    def test_a_job_nothing_ever_claims_times_out_rather_than_hanging(self) -> None:
        # The gap the Rust port left behind: `await_result` used to enforce this, and
        # removing the blocking wait removed the deadline with it. Without this the
        # popup spinner would run forever whenever the extension disappeared.
        job_id = self._submit()

        self.clock.advance(REQUEST_TIMEOUT_SECONDS + 1)
        self.broker.tick()

        self.assertEqual(len(self.settled), 1)
        self.assertEqual(self.settled[0][0], job_id)
        self.assertFalse(self.settled[0][1].ok)
        self.assertEqual(self.settled[0][1].error, TIMED_OUT_ERROR)
        self.assertEqual(self.broker.pending_count(), 0)
        self.assertEqual(self.broker.waiting_count(), 0)

    def test_a_job_inside_its_deadline_is_left_alone(self) -> None:
        self._submit()

        self.clock.advance(REQUEST_TIMEOUT_SECONDS - 1)
        self.broker.tick()

        self.assertEqual(self.settled, [])
        self.assertEqual(self.broker.waiting_count(), 1)

    def test_a_deadline_does_not_settle_a_job_twice(self) -> None:
        job_id = self._submit()
        self.broker.resolve(job_id, JobOutcome.done("Hello"))

        self.clock.advance(REQUEST_TIMEOUT_SECONDS + 1)
        self.broker.tick()

        self.assertEqual(len(self.settled), 1)
        self.assertTrue(self.settled[0][1].ok)

    def test_a_cancelled_job_never_reports_a_timeout(self) -> None:
        job_id = self._submit()
        self.broker.cancel(job_id)

        self.clock.advance(REQUEST_TIMEOUT_SECONDS + 1)
        self.broker.tick()

        self.assertEqual(self.settled, [])

    def test_the_queue_applies_back_pressure(self) -> None:
        for _ in range(MAX_QUEUE_DEPTH):
            self._submit()

        with self.assertRaises(QueueFullError):
            self._submit()

    def test_cancelling_drops_the_waiter_and_forgets_the_job(self) -> None:
        job_id = self._submit()

        self.assertTrue(self.broker.cancel(job_id))
        self.assertFalse(self.broker.cancel(job_id))
        self.assertEqual(self.broker.pending_count(), 0)
        self.assertIsNone(self.broker.claim_next(wait_seconds=0))

    def test_releasing_a_claim_puts_the_job_back_for_the_next_poll(self) -> None:
        # The bug this exists for: the client hung up between the claim and the write,
        # so the job left the queue and reached nobody. Without release it sat claimed
        # until the lease expired and the caller waited out that whole window.
        job_id = self._submit()
        self.broker.claim_next(wait_seconds=0)
        self.assertEqual(self.broker.pending_count(), 0)

        released = self.broker.release(job_id)

        self.assertTrue(released)
        self.assertEqual(self.broker.pending_count(), 1)
        self.assertEqual(self.settled, [])

        redelivered = self.broker.claim_next(wait_seconds=0)
        assert redelivered is not None
        self.assertEqual(redelivered.id, job_id)

    def test_a_released_job_keeps_its_waiter(self) -> None:
        # The difference from cancel(): the caller is still waiting. Only the handover
        # failed.
        job_id = self._submit()
        self.broker.claim_next(wait_seconds=0)

        self.broker.release(job_id)
        self.broker.claim_next(wait_seconds=0)
        self.broker.resolve(job_id, JobOutcome.done("Hello"))

        self.assertEqual(len(self.settled), 1)
        self.assertEqual(self.settled[0][1].text, "Hello")

    def test_releasing_rolls_back_the_attempt(self) -> None:
        # A job that was never delivered was never attempted. Otherwise two failed
        # handovers would burn both attempts and fail a job the extension never saw.
        job_id = self._submit()

        for _ in range(5):
            self.broker.claim_next(wait_seconds=0)
            self.broker.release(job_id)

        self.broker.claim_next(wait_seconds=0)
        self.clock.advance(LEASE_TIMEOUT_SECONDS + 1)
        self.broker.expire_leases()

        # Still on attempt 1, so the lease requeues rather than failing outright.
        self.assertEqual(self.settled, [])
        self.assertEqual(self.broker.pending_count(), 1)

    def test_a_released_job_goes_to_the_front_of_the_queue(self) -> None:
        # It was first in line before we popped it; a failed handover should not send
        # it to the back behind jobs submitted since.
        first = self._submit("first")
        self.broker.claim_next(wait_seconds=0)
        self._submit("second")

        self.broker.release(first)
        claimed = self.broker.claim_next(wait_seconds=0)

        assert claimed is not None
        self.assertEqual(claimed.id, first)

    def test_releasing_an_unclaimed_or_unknown_job_is_a_no_op(self) -> None:
        job_id = self._submit()

        self.assertFalse(self.broker.release("job-nobody-claimed"))
        self.assertFalse(self.broker.release(job_id))
        self.assertEqual(self.broker.pending_count(), 1)

    def test_releasing_a_cancelled_job_does_not_requeue_it(self) -> None:
        # The user closed the popup while the handover was failing. Nothing wants it.
        job_id = self._submit()
        self.broker.claim_next(wait_seconds=0)
        self.broker.cancel(job_id)

        self.assertFalse(self.broker.release(job_id))
        self.assertEqual(self.broker.pending_count(), 0)

    def test_a_cancelled_job_that_completes_late_is_not_delivered(self) -> None:
        # The extension has no cancel route, so this genuinely happens: the browser
        # finishes a translation the user already dismissed.
        job_id = self._submit()
        self.broker.claim_next(wait_seconds=0)
        self.broker.cancel(job_id)

        accepted = self.broker.resolve(job_id, JobOutcome.done("Hello"))

        self.assertFalse(accepted)
        self.assertEqual(self.settled, [])

    def test_a_resolved_job_leaves_no_phantom_behind(self) -> None:
        # Rust clears pending/claimed/waiting/attempts together, because a result can
        # land before the job was claimed and a leftover pending entry would later be
        # handed out as a phantom job.
        job_id = self._submit()

        self.broker.resolve(job_id, JobOutcome.done("Hello"))

        self.assertEqual(self.broker.pending_count(), 0)
        self.assertEqual(self.broker.waiting_count(), 0)
        self.assertIsNone(self.broker.claim_next(wait_seconds=0))

    def test_connection_state_follows_the_last_poll(self) -> None:
        self.assertFalse(self.broker.is_connected())

        self.broker.claim_next(wait_seconds=0)
        self.assertTrue(self.broker.is_connected())

        self.clock.advance(CONNECTION_TTL_SECONDS - 1)
        self.assertTrue(self.broker.is_connected())

        self.clock.advance(2)
        self.assertFalse(self.broker.is_connected())

    def test_touching_last_seen_marks_the_extension_connected(self) -> None:
        self.broker.touch_last_seen()

        self.assertTrue(self.broker.is_connected())

    def test_jobs_are_claimed_in_submission_order(self) -> None:
        first = self._submit("one")
        second = self._submit("two")

        claimed_first = self.broker.claim_next(wait_seconds=0)
        claimed_second = self.broker.claim_next(wait_seconds=0)

        assert claimed_first is not None and claimed_second is not None
        self.assertEqual(claimed_first.id, first)
        self.assertEqual(claimed_second.id, second)

    def test_the_callback_is_not_invoked_while_the_lock_is_held(self) -> None:
        # A callback that re-enters the broker would deadlock instantly if resolve()
        # dispatched under the lock. This is the regression guard for that.
        observed: list[int] = []

        def reentrant(job_id: str, outcome: JobOutcome) -> None:
            observed.append(self.broker.pending_count())

        self.broker.submit(
            source_text="hi",
            source_lang="en",
            target_lang="es",
            provider="deepl",
            on_settled=reentrant,
        )
        job = self.broker.claim_next(wait_seconds=0)
        assert job is not None

        finished = threading.Event()

        def resolve() -> None:
            self.broker.resolve(job.id, JobOutcome.done("hola"))
            finished.set()

        thread = threading.Thread(target=resolve, daemon=True)
        thread.start()

        self.assertTrue(finished.wait(timeout=5), "resolve() deadlocked in its callback")
        self.assertEqual(observed, [0])


class TimeoutInvariantTests(unittest.TestCase):
    """The timeout constants encode arithmetic about a client we cannot change.

    These are the assertions that keep that reasoning from being quietly edited away.
    """

    # The browser extension's own figures, from native-host.js. We do not control
    # these and cannot change them; every constant below is derived from them.
    EXTENSION_JOB_TIMEOUT = 75.0
    EXTENSION_RESULT_POST_TIMEOUT = 15.0
    EXTENSION_RESULT_POST_ATTEMPTS = 2
    EXTENSION_RESULT_POST_RETRY_DELAY = 1.0

    def _worst_case_fail_report(self) -> float:
        """Latest a legitimate /fail can land after the client claimed the job."""

        posting = self.EXTENSION_RESULT_POST_TIMEOUT * self.EXTENSION_RESULT_POST_ATTEMPTS
        retries = self.EXTENSION_RESULT_POST_RETRY_DELAY * (self.EXTENSION_RESULT_POST_ATTEMPTS - 1)
        return self.EXTENSION_JOB_TIMEOUT + posting + retries

    def test_the_lease_outlives_the_clients_worst_case_failure_report(self) -> None:
        # If the lease fired first we would hand the job to a second client while the
        # first client's /fail was still in flight, and that late failure would then
        # resolve a job whose retry was actively being translated.
        self.assertGreater(LEASE_TIMEOUT_SECONDS, self._worst_case_fail_report())

    def test_the_lease_outlives_the_clients_nominal_job_timeout(self) -> None:
        self.assertGreater(LEASE_TIMEOUT_SECONDS, self.EXTENSION_JOB_TIMEOUT)

    def test_the_request_deadline_outlives_the_clients_own_failure_reporting(self) -> None:
        # Otherwise we would report our own vague timeout in place of the specific
        # error the extension was about to hand us.
        self.assertGreater(REQUEST_TIMEOUT_SECONDS, self.EXTENSION_JOB_TIMEOUT)

    def test_the_long_poll_ceiling_stays_under_the_clients_socket_timeout(self) -> None:
        # native-host.js LONG_POLL_TIMEOUT_MS = 40000. Answering later reads as a
        # dead host and drops the client into reconnect backoff.
        extension_socket_timeout = 40.0

        self.assertLess(MAX_LONG_POLL_SECONDS, extension_socket_timeout)


class LongPollClampTests(unittest.TestCase):
    def test_clamps_into_the_range_the_client_expects(self) -> None:
        self.assertEqual(clamp_long_poll_seconds(25), 25.0)
        self.assertEqual(clamp_long_poll_seconds(0), 1.0)
        self.assertEqual(clamp_long_poll_seconds(-5), 1.0)
        self.assertEqual(clamp_long_poll_seconds(9_000), 30.0)

    def test_falls_back_for_values_that_are_not_numbers(self) -> None:
        self.assertEqual(clamp_long_poll_seconds("25"), 5.0)
        self.assertEqual(clamp_long_poll_seconds(None), 5.0)
        self.assertEqual(clamp_long_poll_seconds(True), 5.0)


if __name__ == "__main__":
    unittest.main()
