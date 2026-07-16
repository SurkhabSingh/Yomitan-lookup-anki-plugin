"""Translation provider contract.

Mirrors ``language/base.py``: a ``Protocol`` rather than an ABC, so a provider is
anything with the right shape and tests can pass a stub without inheriting.

Today the only inline provider is the browser-extension bridge. The contract exists
so the roadmap's "keep the provider layer extensible so offline translation can be
added later" does not require reworking the popup or the hooks: an offline provider,
or an authenticated API provider, implements this and nothing above it changes.
"""

from __future__ import annotations

from typing import Protocol

from .models import JobOutcome


class SettledHandler(Protocol):
    def __call__(self, request_id: str, outcome: JobOutcome) -> None:
        """Receive a terminal outcome for a previously submitted request."""


class TranslationProvider(Protocol):
    def provider_id(self) -> str:
        """Return the id used on the wire and in configuration."""

    def is_available(self) -> bool:
        """Return True when this provider can currently accept work."""

    def unavailable_reason(self) -> str:
        """Return a user-facing explanation of why it cannot, or an empty string."""

    def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
        on_settled: SettledHandler,
    ) -> str:
        """Start a translation and return its request id.

        Must not block: the caller may be Anki's Qt main thread. The result arrives
        through ``on_settled``, possibly on another thread.
        """

    def cancel(self, request_id: str) -> None:
        """Abandon a request. Late results for it must be ignored."""
