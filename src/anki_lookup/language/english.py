"""English inflection expansion for dictionary and reverse-gloss lookup."""

from __future__ import annotations

from .generic import GenericLanguageProfile
from .models import MorphologyCandidate


class EnglishLanguageProfile(GenericLanguageProfile):
    def language_codes(self) -> tuple[str, ...]:
        return ("en", "eng")

    def expand_query(self, value: str) -> tuple[MorphologyCandidate, ...]:
        term = self.normalize(value)
        if not term:
            return ()

        candidates = [MorphologyCandidate(term)]
        transformed: list[tuple[str, str, frozenset[str]]] = []
        if term.endswith("'s") and len(term) > 2:
            transformed.append((term[:-2], "possessive", frozenset({"n"})))
        if term.endswith("s'") and len(term) > 2:
            transformed.append((term[:-1], "possessive", frozenset({"n"})))
        if term.endswith("ies") and len(term) > 3:
            transformed.append((term[:-3] + "y", "plural", frozenset({"n", "v"})))
        if term.endswith("ves") and len(term) > 3:
            transformed.extend(
                (
                    (term[:-3] + "f", "plural", frozenset({"n"})),
                    (term[:-3] + "fe", "plural", frozenset({"n"})),
                )
            )
        if term.endswith("es") and len(term) > 2:
            transformed.append((term[:-2], "plural or third-person", frozenset({"n", "v"})))
        if term.endswith("s") and len(term) > 1:
            transformed.append((term[:-1], "plural or third-person", frozenset({"n", "v"})))
        if term.endswith("ied") and len(term) > 3:
            transformed.append((term[:-3] + "y", "past", frozenset({"v"})))
        if term.endswith("ed") and len(term) > 2:
            stem = term[:-2]
            if len(stem) > 2 and stem[-1] == stem[-2]:
                transformed.append((stem[:-1], "past", frozenset({"v"})))
            transformed.extend(
                (
                    (stem, "past", frozenset({"v"})),
                    (stem + "e", "past", frozenset({"v"})),
                )
            )
        if term.endswith("ying") and len(term) > 4:
            transformed.append((term[:-4] + "ie", "present participle", frozenset({"v"})))
        if term.endswith("ing") and len(term) > 3:
            stem = term[:-3]
            if len(stem) > 2 and stem[-1] == stem[-2]:
                transformed.append((stem[:-1], "present participle", frozenset({"v"})))
            transformed.extend(
                (
                    (stem, "present participle", frozenset({"v"})),
                    (stem + "e", "present participle", frozenset({"v"})),
                )
            )

        seen = {term}
        for transformed_term, reason, rules in transformed:
            if transformed_term and transformed_term not in seen:
                seen.add(transformed_term)
                candidates.append(MorphologyCandidate(transformed_term, (reason,), rules))
        return tuple(candidates)
