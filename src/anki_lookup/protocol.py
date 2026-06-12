"""Namespaced webview bridge protocol for lookup requests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .dictionary import LookupEntry

MESSAGE_PREFIX = "anki_lookup:"
MAXIMUM_TERM_LENGTH = 500
MAXIMUM_SENTENCE_LENGTH = 2_000
MAXIMUM_LOOKUP_CANDIDATES = 20


@dataclass(frozen=True)
class LookupRequest:
    request_id: int
    term: str
    sentence: str = ""
    candidates: tuple[str, ...] = ()


def parse_lookup_message(message: str) -> LookupRequest | None:
    """Parse a valid lookup message, or return ``None`` for another namespace."""

    if not message.startswith(MESSAGE_PREFIX):
        return None

    payload = json.loads(message[len(MESSAGE_PREFIX) :])
    if not isinstance(payload, dict) or payload.get("action") != "lookup":
        raise ValueError("Unsupported Anki Lookup action")

    request_id = payload.get("request_id")
    term = payload.get("term")
    sentence = payload.get("sentence", "")
    candidates = payload.get("candidates", [])
    if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 0:
        raise ValueError("request_id must be a non-negative integer")
    if not isinstance(term, str):
        raise ValueError("term must be a string")
    if not isinstance(sentence, str):
        raise ValueError("sentence must be a string")
    if not isinstance(candidates, list):
        raise ValueError("candidates must be a list")

    normalized_term = " ".join(term.split())
    if not normalized_term:
        raise ValueError("term must not be empty")
    if len(normalized_term) > MAXIMUM_TERM_LENGTH:
        raise ValueError("term is too long")
    normalized_sentence = " ".join(sentence.split())
    if len(normalized_sentence) > MAXIMUM_SENTENCE_LENGTH:
        normalized_sentence = normalized_sentence[:MAXIMUM_SENTENCE_LENGTH]
    normalized_candidates: list[str] = []
    for candidate in candidates[:MAXIMUM_LOOKUP_CANDIDATES]:
        if not isinstance(candidate, str):
            raise ValueError("lookup candidates must be strings")
        normalized_candidate = " ".join(candidate.split())
        if (
            normalized_candidate
            and len(normalized_candidate) <= MAXIMUM_TERM_LENGTH
            and normalized_candidate not in normalized_candidates
        ):
            normalized_candidates.append(normalized_candidate)

    return LookupRequest(
        request_id=request_id,
        term=normalized_term,
        sentence=normalized_sentence,
        candidates=tuple(normalized_candidates),
    )


def lookup_result(
    request: LookupRequest, entries: list[LookupEntry], matched_term: str | None = None
) -> dict[str, Any]:
    """Serialize dictionary lookup entries for the webview."""

    status = "ready" if entries else "empty"
    return {
        "request_id": request.request_id,
        "status": status,
        "term": matched_term or request.term,
        "sentence": request.sentence,
        "entries": [
            {
                "expression": entry.expression,
                "reading": entry.reading,
                "dictionary": entry.dictionary,
                "term_tags": list(entry.term_tags),
                "definition_tags": list(entry.definition_tags),
                "definitions": list(entry.definitions),
                "match_type": entry.match_type,
                "score": entry.score,
                "entry_type": entry.entry_type,
                "metadata": dict(entry.metadata),
                "inflection_reasons": list(entry.inflection_reasons),
            }
            for entry in entries
        ],
    }


def error_result(message: str, request_id: int | None = None) -> dict[str, Any]:
    """Return a safe bridge error response."""

    return {
        "request_id": request_id,
        "status": "error",
        "message": message,
    }
