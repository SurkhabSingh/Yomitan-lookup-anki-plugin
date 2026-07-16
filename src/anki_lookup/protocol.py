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

#: Cap on text submitted for translation. Matches the sentence ceiling: the popup only
#: ever offers to translate a captured sentence, and anything larger is not something
#: the user selected by scanning a word.
MAXIMUM_TRANSLATION_LENGTH = MAXIMUM_SENTENCE_LENGTH

LOOKUP_ACTION = "lookup"
TRANSLATE_ACTION = "translate"
TRANSLATE_CANCEL_ACTION = "translate_cancel"
OPEN_EXTERNAL_ACTION = "open_external"
ADD_NOTE_ACTION = "add_note"
OPEN_NOTE_ACTION = "open_note"

ACTIONS = (
    LOOKUP_ACTION,
    TRANSLATE_ACTION,
    TRANSLATE_CANCEL_ACTION,
    OPEN_EXTERNAL_ACTION,
    ADD_NOTE_ACTION,
    OPEN_NOTE_ACTION,
)


@dataclass(frozen=True)
class LookupRequest:
    request_id: int
    term: str
    sentence: str = ""
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class TranslateRequest:
    """A request to translate captured text.

    ``popup_token`` identifies which popup asked. Depth is not a stable key — nested
    popups reuse it — and by the time a translation lands the popup that asked may be
    gone or replaced.
    """

    request_id: int
    popup_token: str
    text: str


@dataclass(frozen=True)
class TranslateCancelRequest:
    request_id: int
    popup_token: str


def parse_message(message: str) -> tuple[str, dict[str, Any]] | None:
    """Split a namespaced message into its action and payload.

    Returns ``None`` for another add-on's namespace. Raises ``ValueError`` for our
    namespace carrying something we do not implement.
    """

    if not message.startswith(MESSAGE_PREFIX):
        return None

    payload = json.loads(message[len(MESSAGE_PREFIX) :])
    if not isinstance(payload, dict):
        raise ValueError("Unsupported Anki Lookup action")

    action = payload.get("action")
    if action not in ACTIONS:
        raise ValueError("Unsupported Anki Lookup action")
    return str(action), payload


def parse_lookup_message(message: str) -> LookupRequest | None:
    """Parse a valid lookup message, or return ``None`` for another namespace."""

    parsed = parse_message(message)
    if parsed is None:
        return None

    action, payload = parsed
    if action != LOOKUP_ACTION:
        raise ValueError("Unsupported Anki Lookup action")
    return parse_lookup_payload(payload)


def parse_lookup_payload(payload: dict[str, Any]) -> LookupRequest:
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


def parse_translate_payload(payload: dict[str, Any]) -> TranslateRequest:
    request_id = _validated_request_id(payload.get("request_id"))
    popup_token = _validated_popup_token(payload.get("popup_token"))

    text = payload.get("text")
    if not isinstance(text, str):
        raise ValueError("text must be a string")

    normalized_text = " ".join(text.split())
    if not normalized_text:
        raise ValueError("text must not be empty")
    normalized_text = normalized_text[:MAXIMUM_TRANSLATION_LENGTH]

    return TranslateRequest(
        request_id=request_id,
        popup_token=popup_token,
        text=normalized_text,
    )


def parse_translate_cancel_payload(payload: dict[str, Any]) -> TranslateCancelRequest:
    return TranslateCancelRequest(
        request_id=_validated_request_id(payload.get("request_id")),
        popup_token=_validated_popup_token(payload.get("popup_token")),
    )


@dataclass(frozen=True)
class AddNoteRequest:
    """A request to create a note from a lookup result.

    Every text field is carried explicitly rather than re-derived from a cached lookup:
    the popup knows exactly which entry the user was looking at, and re-running the
    lookup could return something else by the time the button is pressed.
    """

    request_id: int
    popup_token: str
    expression: str
    reading: str = ""
    definition: str = ""
    translation: str = ""
    selected_text: str = ""
    sentence: str = ""
    dictionary: str = ""
    allow_duplicate: bool = False
    #: The surface form as it appeared on the card — 食べました, not the headword
    #: 食べる. Cloze quotes the sentence, and the sentence said the surface form.
    source_term: str = ""
    #: Where ``source_term`` starts inside ``sentence``, in **UTF-16 code units**,
    #: because that is what JavaScript counts. Converted to codepoints before use.
    sentence_offset: int = 0


def parse_add_note_payload(payload: dict[str, Any]) -> AddNoteRequest:
    request_id = _validated_request_id(payload.get("request_id"))
    popup_token = _validated_popup_token(payload.get("popup_token"))

    expression = _bounded_text(payload.get("expression"), MAXIMUM_TERM_LENGTH)
    if not expression:
        raise ValueError("expression must not be empty")

    return AddNoteRequest(
        request_id=request_id,
        popup_token=popup_token,
        expression=expression,
        reading=_bounded_text(payload.get("reading"), MAXIMUM_TERM_LENGTH),
        definition=_bounded_text(payload.get("definition"), MAXIMUM_SENTENCE_LENGTH),
        translation=_bounded_text(payload.get("translation"), MAXIMUM_SENTENCE_LENGTH),
        selected_text=_bounded_text(payload.get("selected_text"), MAXIMUM_TERM_LENGTH),
        # Verbatim, not whitespace-collapsed like the fields above. `sentence_offset`
        # was measured by the popup against this exact string; rewriting it here would
        # shift every offset and split the cloze in the wrong place. The popup has
        # already sanitised it.
        sentence=_bounded_verbatim(payload.get("sentence"), MAXIMUM_SENTENCE_LENGTH),
        sentence_offset=_bounded_offset(payload.get("sentence_offset")),
        source_term=_bounded_verbatim(payload.get("source_term"), MAXIMUM_TERM_LENGTH),
        dictionary=_bounded_text(payload.get("dictionary"), MAXIMUM_TERM_LENGTH),
        allow_duplicate=payload.get("allow_duplicate") is True,
    )


def parse_open_note_payload(payload: dict[str, Any]) -> int:
    note_id = payload.get("note_id")
    if isinstance(note_id, bool) or not isinstance(note_id, int) or note_id <= 0:
        raise ValueError("note_id must be a positive integer")
    return note_id


def note_result(
    request_id: int,
    popup_token: str,
    status: str,
    message: str = "",
    note_id: int = 0,
) -> dict[str, Any]:
    """Serialize a note-creation state for the webview.

    ``status`` is one of ``queued``, ``added``, ``duplicate``, ``not_configured``, or
    ``error``.
    """

    return {
        "request_id": request_id,
        "popup_token": popup_token,
        "kind": "note",
        "status": status,
        "message": message,
        "note_id": note_id,
    }


def _bounded_text(value: object, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _bounded_verbatim(value: object, limit: int) -> str:
    """Cap the length without touching the content.

    For anything an offset is measured against: collapsing whitespace would move
    every character after the first double space.
    """

    if not isinstance(value, str):
        return ""
    return value[:limit]


def _bounded_offset(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return min(value, MAXIMUM_SENTENCE_LENGTH)


def _validated_request_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("request_id must be a non-negative integer")
    return value


def _validated_popup_token(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("popup_token must be a string")
    token = value.strip()
    if not token or len(token) > 64:
        raise ValueError("popup_token must be a short non-empty string")
    return token


def translation_result(
    request_id: int,
    popup_token: str,
    status: str,
    text: str = "",
    message: str = "",
    provider: str = "",
    cached: bool = False,
    external_url: str = "",
) -> dict[str, Any]:
    """Serialize a translation state for the webview.

    ``status`` is one of ``pending``, ``ready``, ``unavailable``, or ``error``. The
    popup renders from this alone, so an ``unavailable`` result carries both the reason
    and the fallback URL rather than making JavaScript work either out.
    """

    return {
        "request_id": request_id,
        "popup_token": popup_token,
        "kind": "translation",
        "status": status,
        "text": text,
        "message": message,
        "provider": provider,
        "cached": cached,
        "external_url": external_url,
    }


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
                "frequencies": [
                    {
                        "dictionary": item.dictionary,
                        "value": item.value,
                        "display_value": item.display_value,
                        "frequency_mode": item.frequency_mode,
                    }
                    for item in entry.frequencies
                ],
                "pitch_accents": [
                    {
                        "dictionary": item.dictionary,
                        "reading": item.reading,
                        "position": item.position,
                        "nasal_positions": list(item.nasal_positions),
                        "devoice_positions": list(item.devoice_positions),
                        "tags": list(item.tags),
                    }
                    for item in entry.pitch_accents
                ],
                "ipa": [
                    {
                        "dictionary": item.dictionary,
                        "reading": item.reading,
                        "transcription": item.transcription,
                        "tags": list(item.tags),
                    }
                    for item in entry.ipa
                ],
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
