"""Language-aware lookup candidate models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MorphologyCandidate:
    term: str
    reasons: tuple[str, ...] = ()
    required_rules: frozenset[str] = frozenset()
