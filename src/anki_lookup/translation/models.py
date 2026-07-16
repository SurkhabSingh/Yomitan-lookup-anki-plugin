"""Translation value objects."""

from __future__ import annotations

from dataclasses import dataclass

GOOGLE_TRANSLATE = "google-translate"
DEEPL = "deepl"

#: Provider ids the browser extension accepts. It does **not** sanitize the
#: ``provider`` field of a job: an unknown non-empty string is not coerced to a
#: default, it fails the job outright. Anything we put on the wire must be in here.
ALLOWED_PROVIDERS = (GOOGLE_TRANSLATE, DEEPL)

PROVIDER_LABELS = {
    GOOGLE_TRANSLATE: "Google Translate",
    DEEPL: "DeepL",
}


@dataclass(frozen=True)
class TranslationJob:
    """One unit of work handed to the browser extension.

    Field names mirror the desktop app's ``BridgeJob``; ``as_payload`` converts to
    the camelCase the extension reads.
    """

    id: str
    provider: str
    source_text: str
    source_lang: str
    target_lang: str

    def as_payload(self) -> dict[str, str]:
        return {
            "id": self.id,
            "provider": self.provider,
            "sourceText": self.source_text,
            "sourceLang": self.source_lang,
            "targetLang": self.target_lang,
        }


@dataclass(frozen=True)
class JobOutcome:
    """Terminal state of a job.

    A frozen dataclass rather than a union so mypy's strict mode stays quiet at the
    call sites and the two cases cannot be confused for a bare string.
    """

    text: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @classmethod
    def done(cls, text: str) -> JobOutcome:
        return cls(text=text)

    @classmethod
    def failed(cls, error: str) -> JobOutcome:
        return cls(error=error or "The translation failed.")


def provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider)
