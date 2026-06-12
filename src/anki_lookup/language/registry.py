"""Language profile registry with a guaranteed generic fallback."""

from __future__ import annotations

from .base import LanguageProfile
from .english import EnglishLanguageProfile
from .generic import GenericLanguageProfile
from .japanese import JapaneseLanguageProfile


class LanguageProfileRegistry:
    def __init__(self) -> None:
        self._generic = GenericLanguageProfile()
        self._profiles: dict[str, LanguageProfile] = {}
        self.register(JapaneseLanguageProfile())
        self.register(EnglishLanguageProfile())

    @property
    def generic(self) -> LanguageProfile:
        return self._generic

    def register(self, profile: LanguageProfile) -> None:
        for code in profile.language_codes():
            if code == "*":
                raise ValueError("Only the built-in generic profile may use '*'")
            self._profiles[code.casefold()] = profile

    def for_language(self, language_code: str | None) -> LanguageProfile:
        if language_code:
            profile = self._profiles.get(language_code.casefold())
            if profile is not None:
                return profile
        return self._generic

    def for_text(self, value: str) -> LanguageProfile:
        if any(
            "\u3040" <= character <= "\u30ff" or "\u3400" <= character <= "\u9fff"
            for character in value
        ):
            return self.for_language("ja")
        if any("a" <= character.casefold() <= "z" for character in value):
            return self.for_language("en")
        return self._generic


language_profiles = LanguageProfileRegistry()
