"""Japanese deinflection using bounded, rule-aware candidate expansion."""

from __future__ import annotations

from dataclasses import dataclass

from .generic import GenericLanguageProfile
from .models import MorphologyCandidate


@dataclass(frozen=True)
class _SuffixRule:
    suffix: str
    replacement: str
    reason: str
    required_rules: frozenset[str]


def _polite_rules() -> tuple[_SuffixRule, ...]:
    endings = (
        ("ます", "polite"),
        ("ました", "polite past"),
        ("ません", "polite negative"),
        ("ませんでした", "polite negative past"),
    )
    godan_stems = (
        ("い", "う", "v5u"),
        ("き", "く", "v5k"),
        ("ぎ", "ぐ", "v5g"),
        ("し", "す", "v5s"),
        ("ち", "つ", "v5t"),
        ("に", "ぬ", "v5n"),
        ("び", "ぶ", "v5b"),
        ("み", "む", "v5m"),
        ("り", "る", "v5r"),
    )
    rules = []
    for ending, reason in endings:
        rules.append(_SuffixRule(ending, "る", reason, frozenset({"v1"})))
        for stem, dictionary_ending, rule in godan_stems:
            rules.append(
                _SuffixRule(
                    stem + ending,
                    dictionary_ending,
                    reason,
                    frozenset({rule}),
                )
            )
    return tuple(rules)


_RULES = (
    *_polite_rules(),
    _SuffixRule("しなかった", "する", "negative past", frozenset({"vs"})),
    _SuffixRule("しない", "する", "negative", frozenset({"vs"})),
    _SuffixRule("して", "する", "te-form", frozenset({"vs"})),
    _SuffixRule("した", "する", "past", frozenset({"vs"})),
    _SuffixRule("し", "する", "continuative", frozenset({"vs"})),
    _SuffixRule("こなかった", "くる", "negative past", frozenset({"vk"})),
    _SuffixRule("こない", "くる", "negative", frozenset({"vk"})),
    _SuffixRule("きて", "くる", "te-form", frozenset({"vk"})),
    _SuffixRule("きた", "くる", "past", frozenset({"vk"})),
    _SuffixRule("き", "くる", "continuative", frozenset({"vk"})),
    _SuffixRule("くなかった", "い", "negative past", frozenset({"adj-i"})),
    _SuffixRule("くない", "い", "negative", frozenset({"adj-i"})),
    _SuffixRule("かった", "い", "past", frozenset({"adj-i"})),
    _SuffixRule("くて", "い", "te-form", frozenset({"adj-i"})),
    _SuffixRule("して", "す", "te-form", frozenset({"v5s"})),
    _SuffixRule("した", "す", "past", frozenset({"v5s"})),
    _SuffixRule("いて", "く", "te-form", frozenset({"v5k"})),
    _SuffixRule("いた", "く", "past", frozenset({"v5k"})),
    _SuffixRule("いで", "ぐ", "te-form", frozenset({"v5g"})),
    _SuffixRule("いだ", "ぐ", "past", frozenset({"v5g"})),
    _SuffixRule("んで", "む", "te-form", frozenset({"v5m"})),
    _SuffixRule("んだ", "む", "past", frozenset({"v5m"})),
    _SuffixRule("んで", "ぶ", "te-form", frozenset({"v5b"})),
    _SuffixRule("んだ", "ぶ", "past", frozenset({"v5b"})),
    _SuffixRule("んで", "ぬ", "te-form", frozenset({"v5n"})),
    _SuffixRule("んだ", "ぬ", "past", frozenset({"v5n"})),
    _SuffixRule("って", "う", "te-form", frozenset({"v5u"})),
    _SuffixRule("った", "う", "past", frozenset({"v5u"})),
    _SuffixRule("って", "つ", "te-form", frozenset({"v5t"})),
    _SuffixRule("った", "つ", "past", frozenset({"v5t"})),
    _SuffixRule("って", "る", "te-form", frozenset({"v5r"})),
    _SuffixRule("った", "る", "past", frozenset({"v5r"})),
    _SuffixRule("て", "る", "te-form", frozenset({"v1"})),
    _SuffixRule("た", "る", "past", frozenset({"v1"})),
    _SuffixRule("わない", "う", "negative", frozenset({"v5u"})),
    _SuffixRule("かない", "く", "negative", frozenset({"v5k"})),
    _SuffixRule("がない", "ぐ", "negative", frozenset({"v5g"})),
    _SuffixRule("さない", "す", "negative", frozenset({"v5s"})),
    _SuffixRule("たない", "つ", "negative", frozenset({"v5t"})),
    _SuffixRule("なない", "ぬ", "negative", frozenset({"v5n"})),
    _SuffixRule("ばない", "ぶ", "negative", frozenset({"v5b"})),
    _SuffixRule("まない", "む", "negative", frozenset({"v5m"})),
    _SuffixRule("らない", "る", "negative", frozenset({"v5r"})),
    _SuffixRule("ない", "る", "negative", frozenset({"v1"})),
    _SuffixRule("い", "う", "continuative", frozenset({"v5u"})),
    _SuffixRule("き", "く", "continuative", frozenset({"v5k"})),
    _SuffixRule("ぎ", "ぐ", "continuative", frozenset({"v5g"})),
    _SuffixRule("し", "す", "continuative", frozenset({"v5s"})),
    _SuffixRule("ち", "つ", "continuative", frozenset({"v5t"})),
    _SuffixRule("に", "ぬ", "continuative", frozenset({"v5n"})),
    _SuffixRule("び", "ぶ", "continuative", frozenset({"v5b"})),
    _SuffixRule("み", "む", "continuative", frozenset({"v5m"})),
    _SuffixRule("り", "る", "continuative", frozenset({"v5r"})),
    _SuffixRule("", "る", "continuative", frozenset({"v1"})),
)


class JapaneseLanguageProfile(GenericLanguageProfile):
    def language_codes(self) -> tuple[str, ...]:
        return ("ja", "jpn")

    def expand_query(self, value: str) -> tuple[MorphologyCandidate, ...]:
        term = self.normalize(value)
        if not term:
            return ()

        results = [MorphologyCandidate(term)]
        seen = {term}
        for rule in _RULES:
            if rule.suffix:
                if not term.endswith(rule.suffix) or len(term) <= len(rule.suffix):
                    continue
                candidate = term[: -len(rule.suffix)] + rule.replacement
            else:
                candidate = term + rule.replacement
            if candidate in seen:
                continue
            seen.add(candidate)
            results.append(MorphologyCandidate(candidate, (rule.reason,), rule.required_rules))
            if len(results) >= 64:
                break
        return tuple(results)
