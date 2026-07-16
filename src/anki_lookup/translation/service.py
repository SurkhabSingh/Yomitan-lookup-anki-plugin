"""Translation orchestration: cache, bridge, and fallback in one place.

Kept out of ``hooks.py`` so it can be tested without Anki, and so the main-thread
contract lives somewhere it can be stated: :meth:`TranslationService.translate` must
return immediately, always. It is called from Anki's ``pycmd`` handler on the Qt main
thread, and it is waiting on a browser.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from .broker import QueueFullError
from .controller import BridgeController
from .external import external_translate_url
from .models import JobOutcome

#: Source language for every request. The providers detect it themselves, and the
#: add-on has no reliable signal for it: card text is mixed-language often enough that
#: guessing from the scanned term would be worse than asking the provider.
SOURCE_LANGUAGE = "auto"

PENDING = "pending"
READY = "ready"
UNAVAILABLE = "unavailable"
ERROR = "error"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranslationOutcome:
    """What the caller should tell the popup right now.

    ``PENDING`` means a result will arrive later through the settled callback; every
    other status is terminal and complete on its own.
    """

    status: str
    text: str = ""
    message: str = ""
    cached: bool = False
    job_id: str = ""
    external_url: str = ""


#: Receives the job id and its outcome, from whichever thread settled it.
SettledCallback = Callable[[str, JobOutcome], None]


class TranslationService:
    """Resolves a translation from the cache, the bridge, or neither."""

    def __init__(self, controller: BridgeController) -> None:
        self._controller = controller

    def translate(
        self,
        text: str,
        provider: str,
        target_lang: str,
        cache_ttl_hours: int,
        on_settled: SettledCallback,
    ) -> TranslationOutcome:
        """Start a translation. Returns immediately; never blocks.

        Order matters: the cache is checked before the bridge's availability, so a
        previously translated sentence still resolves instantly when the Wonder of U
        desktop app has the port. There is no reason to punish the user for a port
        conflict when we already know the answer.
        """

        cached = self._cached(text, provider, target_lang, cache_ttl_hours)
        if cached is not None:
            return TranslationOutcome(status=READY, text=cached, cached=True)

        reason = self._controller.unavailable_reason()
        if reason:
            return TranslationOutcome(
                status=UNAVAILABLE,
                message=reason,
                external_url=self._external_url(provider, text, target_lang),
            )

        try:
            job_id = self._controller.broker.submit(
                source_text=text,
                source_lang=SOURCE_LANGUAGE,
                target_lang=target_lang,
                provider=provider,
                on_settled=on_settled,
            )
        except QueueFullError as error:
            return TranslationOutcome(
                status=ERROR,
                message=str(error),
                external_url=self._external_url(provider, text, target_lang),
            )

        return TranslationOutcome(status=PENDING, job_id=job_id)

    def cancel(self, job_id: str) -> None:
        self._controller.broker.cancel(job_id)

    def store(
        self,
        text: str,
        provider: str,
        target_lang: str,
        translated: str,
        cache_ttl_hours: int,
    ) -> None:
        """Record a completed translation. Never raises.

        Worth doing even for a cancelled job: the browser already did the work, and a
        user who dismissed a popup often scans the same sentence again.
        """

        if not translated:
            return
        try:
            self._controller.cache.store(provider, target_lang, text, translated, cache_ttl_hours)
        except Exception:
            logger.exception("Could not cache a translation")

    def external_url(self, provider: str, text: str, target_lang: str) -> str:
        return self._external_url(provider, text, target_lang)

    def _cached(
        self, text: str, provider: str, target_lang: str, cache_ttl_hours: int
    ) -> str | None:
        try:
            return self._controller.cache.get(provider, target_lang, text, cache_ttl_hours)
        except Exception:
            # A broken cache must not break translation; it is an optimisation.
            logger.exception("Could not read the translation cache")
            return None

    def _external_url(self, provider: str, text: str, target_lang: str) -> str:
        return external_translate_url(provider, text, SOURCE_LANGUAGE, target_lang)
