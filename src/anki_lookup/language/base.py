"""Language profile contract."""

from __future__ import annotations

from typing import Protocol

from .models import MorphologyCandidate


class LanguageProfile(Protocol):
    def language_codes(self) -> tuple[str, ...]:
        """Return language codes handled by this profile."""

    def normalize(self, value: str) -> str:
        """Return the normalized lookup form."""

    def expand_query(self, value: str) -> tuple[MorphologyCandidate, ...]:
        """Return morphology-derived candidates, including the normalized input."""

    def text_direction(self, value: str) -> str:
        """Return ``ltr``, ``rtl``, or ``auto``."""
