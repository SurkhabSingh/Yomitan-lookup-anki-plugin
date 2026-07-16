"""Translation providers, job brokering, and the browser-extension bridge."""

from .base import SettledHandler, TranslationProvider
from .broker import JobBroker, QueueFullError
from .cache import TranslationCache
from .external import external_translate_url, is_supported_provider
from .languages import (
    DEFAULT_TARGET_LANGUAGE,
    normalize_target_language,
    target_language_label,
    target_languages_for,
)
from .models import (
    ALLOWED_PROVIDERS,
    DEEPL,
    GOOGLE_TRANSLATE,
    JobOutcome,
    TranslationJob,
    provider_label,
)

__all__ = [
    "ALLOWED_PROVIDERS",
    "DEEPL",
    "DEFAULT_TARGET_LANGUAGE",
    "GOOGLE_TRANSLATE",
    "JobBroker",
    "JobOutcome",
    "QueueFullError",
    "SettledHandler",
    "TranslationCache",
    "TranslationJob",
    "TranslationProvider",
    "external_translate_url",
    "is_supported_provider",
    "normalize_target_language",
    "provider_label",
    "target_language_label",
    "target_languages_for",
]
