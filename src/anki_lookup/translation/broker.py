"""Translation job broker.

A Python port of the desktop app's ``translation_bridge.rs`` broker, with one
deliberate difference: **there is no blocking await.**

The Rust version has the caller block a worker thread on a condition variable until
the result lands. Here the caller is Anki's ``pycmd`` handler, which runs on the Qt
main thread — blocking it for even a second freezes the whole application, and this
waits on a browser. So the broker is callback-driven and exposes no blocking API at
all. Not "a blocking API you should avoid": none, so it cannot be reached by
accident.

That inversion also lets us delete state the Rust version needs. There, a result can
land before the caller starts waiting, so outcomes are parked in a ``results`` map.
Here the waiter is registered inside :meth:`submit` under the same lock, before the
job is ever visible to :meth:`claim_next`, so "result before waiter" is unreachable.
:meth:`resolve` pops the waiter atomically — that *is* first-writer-wins, and a
retried POST becomes a harmless no-op.

Callbacks are never invoked while the lock is held.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from .models import JobOutcome, TranslationJob

#: How recently the extension must have polled for the bridge to count as connected.
#: The client long-polls with ``wait=25``, so it refreshes this at least that often;
#: the window has to be comfortably wider than one poll or a single slow round trip
#: reads as a disconnection.
CONNECTION_TTL_SECONDS = 60.0

#: Ceiling on a long poll. The client's socket timeout is 40s and it asks for
#: ``wait=25``; answering later than that reads as a dead host.
MAX_LONG_POLL_SECONDS = 30.0
DEFAULT_LONG_POLL_SECONDS = 5.0
MIN_LONG_POLL_SECONDS = 1.0

#: How long a claimed job may go unanswered before it is handed back out.
#:
#: This must clear the client's *worst case*, not its nominal timeout. The extension
#: gives the browser 75s (``JOB_TIMEOUT_MS``) and then reports the failure itself —
#: but that report is an HTTP POST with a 15s timeout and one retry a second later,
#: so a legitimate ``/fail`` can land ~106s after the claim. A lease shorter than
#: that would hand the job out again while the client's own failure report is still
#: in flight, and the late ``/fail`` would then resolve a job whose second attempt is
#: actively being translated. 135s mirrors the desktop app and clears the real
#: figure with room to spare.
#:
#: Under normal operation the lease never fires: it exists for the case where the
#: client process dies mid-job.
LEASE_TIMEOUT_SECONDS = 135.0

#: One retry. A job that two separate claims could not translate is not going to
#: start working on a third.
#:
#: Note that for the interactive path this rarely fires: REQUEST_TIMEOUT_SECONDS is
#: deliberately shorter than the lease (see below), so a popup translation gets a
#: definite answer and a Retry button rather than a silent second attempt three
#: minutes in. The retry still bounds the queue for any non-interactive caller.
MAX_ATTEMPTS = 2

#: How long a caller waits before it is told the translation did not happen.
#:
#: Replaces the Rust ``await_result`` timeout. That version could rely on the blocking
#: caller to give up; with callbacks, nothing else would ever settle a job that sits
#: in ``pending`` because the client went away and never came back — the popup would
#: spin forever.
#:
#: Chosen for a human staring at a spinner, not to accommodate the retry: the
#: extension reports its own failures at ~75s, so anything past this is a dead client,
#: and a dead client is better handled by an honest error and a Retry button than by
#: an invisible second attempt the user has stopped waiting for.
REQUEST_TIMEOUT_SECONDS = 90.0

#: Back-pressure. Translation is lazy — one job per popup tab activation — so the
#: queue only grows past a handful if something is badly wrong.
MAX_QUEUE_DEPTH = 64

QUEUE_FULL_ERROR = "The translation queue is full. Try again shortly."
CLIENT_GONE_ERROR = "The browser extension stopped responding while translating."
TIMED_OUT_ERROR = "The translation timed out."

#: Called with the job id and its outcome, from whichever thread settled it. Never
#: called with the broker lock held.
SettledCallback = Callable[[str, JobOutcome], None]


@dataclass
class _ClaimedJob:
    job: TranslationJob
    claimed_at: float
    attempts: int


class JobBroker:
    """Thread-safe queue of translation jobs awaiting the browser extension.

    The clock is injected so lease and connection expiry can be tested by aging time
    rather than sleeping. Nothing in here may call ``time.monotonic()`` directly.
    """

    def __init__(self, now: Callable[[], float] | None = None) -> None:
        self._now = now if now is not None else time.monotonic
        self._lock = threading.Lock()
        self._signal = threading.Condition(self._lock)
        self._pending: list[TranslationJob] = []
        self._claimed: dict[str, _ClaimedJob] = {}
        self._waiters: dict[str, SettledCallback] = {}
        self._attempts: dict[str, int] = {}
        self._submitted_at: dict[str, float] = {}
        self._sequence = 0
        self._last_seen_at: float | None = None

    # -- producer side (main thread) --------------------------------------------

    def submit(
        self,
        source_text: str,
        source_lang: str,
        target_lang: str,
        provider: str,
        on_settled: SettledCallback,
        job_id: str | None = None,
    ) -> str:
        """Queue a job and register its callback. Returns the job id.

        Raises :class:`QueueFullError` when the queue is at capacity. The callback is
        registered before the job becomes visible to :meth:`claim_next`, which is what
        makes a result-before-waiter race impossible.
        """

        with self._lock:
            if len(self._pending) >= MAX_QUEUE_DEPTH:
                raise QueueFullError(QUEUE_FULL_ERROR)

            self._sequence += 1
            identifier = job_id if job_id is not None else f"job-{self._sequence}"
            job = TranslationJob(
                id=identifier,
                provider=provider,
                source_text=source_text,
                source_lang=source_lang,
                target_lang=target_lang,
            )
            self._waiters[identifier] = on_settled
            self._attempts[identifier] = 0
            self._submitted_at[identifier] = self._now()
            self._pending.append(job)
            self._signal.notify_all()
            return identifier

    def cancel(self, job_id: str) -> bool:
        """Stop tracking a job. Returns True if a waiter was dropped.

        The extension has no cancel route, so a cancelled job may still be translated
        and completed later. That is fine: :meth:`resolve` will find no waiter and
        report the result as unaccepted, and the caller is free to cache it anyway.
        """

        with self._lock:
            had_waiter = self._waiters.pop(job_id, None) is not None
            self._forget(job_id)
            return had_waiter

    # -- consumer side (bridge server threads) ----------------------------------

    def claim_next(self, wait_seconds: float) -> TranslationJob | None:
        """Long-poll for the next pending job, blocking up to ``wait_seconds``.

        Called only from a bridge server thread serving the extension's poll — never
        from the main thread.
        """

        settled: list[tuple[SettledCallback, str, JobOutcome]] = []
        job: TranslationJob | None = None

        with self._lock:
            self._last_seen_at = self._now()
            deadline = self._now() + wait_seconds

            while True:
                settled.extend(self._requeue_expired_leases())

                if self._pending:
                    job = self._pending.pop(0)
                    attempts = self._attempts.get(job.id, 0) + 1
                    self._attempts[job.id] = attempts
                    self._claimed[job.id] = _ClaimedJob(
                        job=job,
                        claimed_at=self._now(),
                        attempts=attempts,
                    )
                    break

                remaining = deadline - self._now()
                if remaining <= 0:
                    break

                # Wake at least once a second so an expired lease is noticed even
                # when no new job arrives to signal us.
                self._signal.wait(min(remaining, 1.0))

        _dispatch(settled)
        return job

    def release(self, job_id: str) -> bool:
        """Undo a claim whose job never reached the client. Returns True if undone.

        Distinct from :meth:`cancel`, which drops the waiter: here the caller is still
        waiting and the work simply was not handed over. A long-poll client
        disconnecting between the claim and the write is routine, and without this the
        job would sit in ``claimed`` until the 135s lease expired — the caller waiting
        the whole time for a job no one had.

        The job goes back to the **front** of the queue, because it was first in line
        before we popped it, and the attempt is rolled back, because an attempt that
        was never delivered was not an attempt. The request deadline remains the
        backstop against a job we can never manage to hand over.
        """

        with self._lock:
            claimed = self._claimed.pop(job_id, None)
            if claimed is None:
                return False
            if job_id not in self._waiters:
                # Cancelled or settled while in flight. Nothing wants it.
                self._forget(job_id)
                return False

            self._attempts[job_id] = max(0, claimed.attempts - 1)
            self._pending.insert(0, claimed.job)
            self._signal.notify_all()
            return True

    def resolve(self, job_id: str, outcome: JobOutcome) -> bool:
        """Record a completion or failure. Returns True if someone was waiting.

        An unknown id is not an error: a result nobody is waiting for is a duplicate
        post, a late one, or a cancelled job. The extension is told 200 either way —
        it does not read the body, and there is nothing useful it could do.
        """

        with self._lock:
            self._claimed.pop(job_id, None)
            waiter = self._waiters.pop(job_id, None)
            self._forget(job_id)

        if waiter is None:
            return False

        waiter(job_id, outcome)
        return True

    def touch_last_seen(self) -> None:
        with self._lock:
            self._last_seen_at = self._now()

    def is_connected(self) -> bool:
        """True when the extension has contacted the bridge recently."""

        with self._lock:
            if self._last_seen_at is None:
                return False
            return (self._now() - self._last_seen_at) < CONNECTION_TTL_SECONDS

    def tick(self) -> None:
        """Expire leases and request deadlines. Called about once a second by the reaper.

        Both halves matter. Lease expiry hands a job back when the client died holding
        it; deadline expiry settles a caller whose job is sitting in ``pending`` that
        nothing will ever claim, which is the only thing standing between a vanished
        extension and a popup that spins forever.
        """

        with self._lock:
            settled = self._requeue_expired_leases()
            settled.extend(self._expire_deadlines())
        _dispatch(settled)

    def expire_leases(self) -> None:
        """Hand back or fail jobs whose client went away."""

        with self._lock:
            settled = self._requeue_expired_leases()
        _dispatch(settled)

    def expire_deadlines(self) -> None:
        """Settle callers whose job has outlived REQUEST_TIMEOUT_SECONDS."""

        with self._lock:
            settled = self._expire_deadlines()
        _dispatch(settled)

    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    def claimed_count(self) -> int:
        """Jobs handed to a client and not yet answered for."""

        with self._lock:
            return len(self._claimed)

    def waiting_count(self) -> int:
        with self._lock:
            return len(self._waiters)

    # -- internals (call with the lock held) ------------------------------------

    def _requeue_expired_leases(self) -> list[tuple[SettledCallback, str, JobOutcome]]:
        """Hand a job back out when the client took it and never answered.

        One retry, then it is failed rather than looped forever. Returns the
        callbacks to run once the lock is released.
        """

        now = self._now()
        expired = [
            job_id
            for job_id, claimed in self._claimed.items()
            if (now - claimed.claimed_at) >= LEASE_TIMEOUT_SECONDS
        ]

        settled: list[tuple[SettledCallback, str, JobOutcome]] = []
        for job_id in expired:
            claimed = self._claimed.pop(job_id)
            waiter = self._waiters.get(job_id)

            if waiter is None:
                # Nobody is listening any more; drop it.
                self._forget(job_id)
                continue

            if claimed.attempts >= MAX_ATTEMPTS:
                del self._waiters[job_id]
                self._forget(job_id)
                settled.append((waiter, job_id, JobOutcome.failed(CLIENT_GONE_ERROR)))
                continue

            self._pending.append(claimed.job)

        return settled

    def _expire_deadlines(self) -> list[tuple[SettledCallback, str, JobOutcome]]:
        """Settle every waiter whose job has outlived its request deadline."""

        now = self._now()
        overdue = [
            job_id
            for job_id, submitted_at in self._submitted_at.items()
            if (now - submitted_at) >= REQUEST_TIMEOUT_SECONDS and job_id in self._waiters
        ]

        settled: list[tuple[SettledCallback, str, JobOutcome]] = []
        for job_id in overdue:
            waiter = self._waiters.pop(job_id)
            self._forget(job_id)
            settled.append((waiter, job_id, JobOutcome.failed(TIMED_OUT_ERROR)))

        return settled

    def _forget(self, job_id: str) -> None:
        """Clear a job from everywhere except ``_waiters``.

        Not just from the map that prompted the call: a job left in ``_pending``
        after its waiter is gone would later be handed out as a phantom job.
        """

        self._pending = [job for job in self._pending if job.id != job_id]
        self._claimed.pop(job_id, None)
        self._attempts.pop(job_id, None)
        self._submitted_at.pop(job_id, None)


class QueueFullError(RuntimeError):
    """Raised by :meth:`JobBroker.submit` when the queue is at capacity."""


def clamp_long_poll_seconds(value: object) -> float:
    """Return a long-poll duration inside the range the client expects."""

    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return DEFAULT_LONG_POLL_SECONDS
    return min(MAX_LONG_POLL_SECONDS, max(MIN_LONG_POLL_SECONDS, float(value)))


def _dispatch(settled: list[tuple[SettledCallback, str, JobOutcome]]) -> None:
    for waiter, job_id, outcome in settled:
        waiter(job_id, outcome)
