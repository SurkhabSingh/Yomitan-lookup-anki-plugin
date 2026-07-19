"""Reviewer webview integration."""

from __future__ import annotations

import json
import logging
import threading
from typing import Any

from .config import runtime_config
from .dictionary import FrequencySortPolicy
from .protocol import (
    ADD_NOTE_ACTION,
    LOOKUP_ACTION,
    OPEN_EXTERNAL_ACTION,
    OPEN_NOTE_ACTION,
    TRANSLATE_ACTION,
    TRANSLATE_CANCEL_ACTION,
    error_result,
    lookup_result,
    note_result,
    parse_add_note_payload,
    parse_lookup_payload,
    parse_message,
    parse_open_note_payload,
    parse_translate_cancel_payload,
    parse_translate_payload,
    translation_result,
)
from .runtime import dictionary_service
from .translation.models import JobOutcome
from .translation.service import ERROR, PENDING, READY

_registered = False
_frequency_sort_policy: FrequencySortPolicy | None = None
_translation_settings: dict[str, Any] = {}
_notes_settings: dict[str, Any] = {}

#: Job id -> the popup that asked for it, so a settled job can be routed back. Guarded
#: because jobs settle on bridge server threads.
_translation_jobs: dict[str, tuple[int, str, str]] = {}
_translation_lock = threading.Lock()

logger = logging.getLogger(__name__)


def register_hooks(gui_hooks: Any) -> None:
    """Register webview hooks exactly once."""

    global _registered
    if _registered:
        return

    gui_hooks.webview_will_set_content.append(on_webview_will_set_content)
    gui_hooks.webview_did_receive_js_message.append(on_webview_did_receive_js_message)
    _registered = True


def on_webview_will_set_content(web_content: Any, context: object | None) -> None:
    """Inject scoped Phase 1 assets into reviewer card webviews."""

    if not _is_reviewer(context):
        return

    from aqt import mw

    if mw is None:
        return

    addon_package = mw.addonManager.addonFromModule(__name__)
    config = runtime_config(mw.addonManager.getConfig(addon_package))
    apply_runtime_config(config)
    config_json = json.dumps(config, ensure_ascii=False).replace("</", "<\\/")

    web_content.head += f"<script>window.AnkiLookupConfig={config_json};</script>"
    web_content.css.append(f"/_addons/{addon_package}/web/popup.css")
    web_content.js.append(f"/_addons/{addon_package}/web/scanner-core.js")
    web_content.js.append(f"/_addons/{addon_package}/web/popup.js")


def on_webview_did_receive_js_message(
    handled: tuple[bool, Any], message: str, context: Any
) -> tuple[bool, Any]:
    """Handle namespaced lookup messages from reviewer JavaScript."""

    if handled[0] or not _is_reviewer(context):
        return handled

    try:
        parsed = parse_message(message)
    except (ValueError, json.JSONDecodeError) as error:
        if message.startswith("anki_lookup:"):
            return (True, error_result(str(error)))
        return handled

    if parsed is None:
        return handled

    action, payload = parsed
    try:
        if action == LOOKUP_ACTION:
            return (True, _handle_lookup(payload))
        if action == TRANSLATE_ACTION:
            return (True, _handle_translate(payload))
        if action == TRANSLATE_CANCEL_ACTION:
            return (True, _handle_translate_cancel(payload))
        if action == OPEN_EXTERNAL_ACTION:
            return (True, _handle_open_external(payload))
        if action == ADD_NOTE_ACTION:
            return (True, _handle_add_note(payload))
        if action == OPEN_NOTE_ACTION:
            return (True, _handle_open_note(payload))
    except (ValueError, json.JSONDecodeError) as error:
        return (True, error_result(str(error)))

    return handled


def _handle_add_note(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a note from a lookup result, sentence and all.

    This is where ``request.sentence`` finally lands. The scanner has captured it and
    the popup has displayed it since the first version; there was simply no note to put
    it in until now.
    """

    from .notes.creator import (
        DUPLICATE,
        NOT_CONFIGURED,
        NOT_CONFIGURED_MESSAGE,
        NoteCreationError,
        add_note_from_lookup,
    )
    from .webview_push import push_to_reviewer

    request = parse_add_note_payload(payload)
    preset = _notes_preset()
    context = _note_context(request)
    registry = _marker_registry()

    def _on_done(status: str, note_id: int, message: str) -> None:
        push_to_reviewer(
            note_result(
                request.request_id,
                request.popup_token,
                status=status,
                message=message,
                note_id=note_id,
            )
        )

    try:
        status, note_id = add_note_from_lookup(
            context,
            preset,
            registry,
            on_done=_on_done,
            allow_duplicate=request.allow_duplicate,
        )
    except NoteCreationError as error:
        return note_result(request.request_id, request.popup_token, "error", str(error))
    except Exception:
        logger.exception("Anki Lookup could not add a note")
        return note_result(
            request.request_id,
            request.popup_token,
            "error",
            "The note could not be created.",
        )

    if status == NOT_CONFIGURED:
        return note_result(
            request.request_id, request.popup_token, NOT_CONFIGURED, NOT_CONFIGURED_MESSAGE
        )
    if status == DUPLICATE:
        return note_result(
            request.request_id,
            request.popup_token,
            DUPLICATE,
            _duplicate_message(preset),
            note_id=note_id,
        )

    return note_result(request.request_id, request.popup_token, "queued")


def _handle_open_note(payload: dict[str, Any]) -> dict[str, Any]:
    note_id = parse_open_note_payload(payload)
    try:
        from .notes.creator import open_note_in_browser

        open_note_in_browser(note_id)
    except Exception:
        logger.exception("Anki Lookup could not open a note")
        return error_result("Could not open the note.")
    return {"status": "opened", "note_id": note_id}


def _duplicate_message(preset: dict[str, Any]) -> str:
    """Say where the existing note was found.

    The only feedback the user gets, so it has to name the scope that was actually
    searched: "already exists" alone leaves them wondering why a word they have never
    added to this deck is being refused.
    """

    from .notes.duplicates import SCOPE_DECK, duplicate_scope

    if duplicate_scope(preset) == SCOPE_DECK:
        return "This note is already in this deck."
    return "This note is already in your collection."


def _note_context(request: Any) -> Any:
    """Assemble everything the markers read.

    The entry is **re-resolved from our own dictionaries** rather than taken from the
    popup. The popup names which entry the user pressed Add on — expression, reading,
    dictionary — and we look it up again. Sending the whole entry back would mean
    trusting frequencies, pitch data and glossary text that had been through the
    webview, to write into the user's collection; and it would put a few kilobytes of
    JSON on a pycmd round trip to save one indexed query.
    """

    from .notes.markers import context_for
    from .notes.markers.cloze import build_cloze, utf16_offset_to_codepoint

    entries = _resolve_entries(request)
    entry = _select_entry(entries, request)

    offset = utf16_offset_to_codepoint(request.sentence, request.sentence_offset)
    cloze = build_cloze(request.sentence, offset, request.source_term or request.expression)
    cloze = _with_body_kana(cloze, entry)

    # context_for guarantees the selected entry is among entries, so a marker can
    # never see a narrower world than the one the note is built from.
    return context_for(
        entry=entry,
        entries=entries,
        cloze=cloze,
        source_term=request.source_term or request.selected_text or request.expression,
        translation=request.translation,
        source_deck=_current_deck_name(),
        media=_resolve_media(request, entry, cloze),
    )


def _resolve_entries(request: Any) -> tuple[Any, ...]:
    """Look the headword up again, to give the markers every dictionary's entry.

    **By the headword, not the scanned surface.** The two travel together in the
    payload but have different jobs: ``source_term`` is the surface form as it
    appeared in the sentence (食べました, or a fragment like アンフ when the segmenter
    split a compound) and exists to quote the sentence in a cloze; ``expression`` is
    the headword of the entry the user pressed Add on, and is the only term
    guaranteed to hit the dictionaries that entry came from. Resolving by the surface
    form is how a compound the segmenter split ended up with entries from the wrong
    dictionary entirely.
    """

    try:
        _, entries = dictionary_service().lookup_candidates(
            (request.expression,), request.expression
        )
        return tuple(entries)
    except Exception:
        logger.exception("Anki Lookup could not re-resolve a lookup for a note")
        return ()


def _select_entry(entries: tuple[Any, ...], request: Any) -> Any:
    """Find the entry the popup named, or synthesise one from what it sent.

    The fallback matters: dictionaries can be disabled or removed between the lookup
    and the Add, and a note built from the text already on screen is better than a
    refusal the user cannot act on.
    """

    from .dictionary.models import LookupEntry

    for entry in entries:
        if entry.expression == request.expression and entry.dictionary == request.dictionary:
            return entry
    for entry in entries:
        if entry.expression == request.expression:
            return entry

    return LookupEntry(
        expression=request.expression,
        reading=request.reading,
        dictionary=request.dictionary,
        term_tags=(),
        definition_tags=(),
        definitions=(request.definition,) if request.definition else (),
        match_type="exact",
        score=0.0,
    )


def _with_body_kana(cloze: Any, entry: Any) -> Any:
    """Fill in the kana form of the scanned word where we can be sure of it.

    Only when the scanned surface *is* the headword: 食べました is an inflected form
    whose kana tail the headword's reading does not cover, and guessing it would put a
    wrong reading on the card.
    """

    from .notes.markers.context import Cloze

    if not cloze.body or not entry.reading:
        return cloze
    if cloze.body != entry.expression:
        return cloze
    return Cloze(
        sentence=cloze.sentence,
        prefix=cloze.prefix,
        body=cloze.body,
        suffix=cloze.suffix,
        body_kana=entry.reading,
    )


def _resolve_media(request: Any, entry: Any, cloze: Any) -> tuple[tuple[str, str], ...]:
    """Render the markers that need the dictionary rather than just the entry.

    Only what the preset actually asks for: the used markers are known by regex before
    anything renders, so a preset with no furigana field never pays for the alignment
    pass over its sentence.
    """

    from .furigana import render_furigana_plain, render_furigana_ruby
    from .notes.field_mapping import markers_used

    wanted = set(markers_used(_notes_preset().get("field_mapping")))
    if not wanted & {"furigana", "furigana-plain", "sentence-furigana"}:
        return ()

    media: list[tuple[str, str]] = []
    try:
        service = dictionary_service()
        if "furigana" in wanted:
            media.append(("furigana", render_furigana_ruby(entry.expression, service)))
        if "furigana-plain" in wanted:
            media.append(("furigana-plain", render_furigana_plain(entry.expression, service)))
        if "sentence-furigana" in wanted and cloze.sentence:
            media.append(("sentence-furigana", render_furigana_ruby(cloze.sentence, service)))
    except Exception:
        logger.exception("Anki Lookup could not render furigana for a note")
        return tuple(media)

    return tuple(media)


def _marker_registry() -> Any:
    from .notes.markers import build_registry

    try:
        titles = tuple(item.title for item in dictionary_service().list_dictionaries())
    except Exception:
        logger.exception("Anki Lookup could not list dictionaries for markers")
        titles = ()
    return build_registry(titles)


def _notes_preset() -> dict[str, Any]:
    return dict(_notes_settings or runtime_config({})["notes"])


def _current_deck_name() -> str:
    """The deck being reviewed, for a source_deck field mapping."""

    try:
        from aqt import mw

        if mw is None or mw.col is None:
            return ""
        current = mw.col.decks.current()
        return str(current.get("name", "")) if current else ""
    except Exception:
        return ""


def _handle_lookup(payload: dict[str, Any]) -> dict[str, Any]:
    request = parse_lookup_payload(payload)
    try:
        matched_term, entries = dictionary_service().lookup_candidates(
            request.candidates,
            request.term,
            frequency_sort=_frequency_sort_policy,
        )
    except Exception:
        logger.exception("Anki Lookup dictionary lookup failed")
        return error_result("Dictionary lookup failed.", request.request_id)
    return lookup_result(request, entries, matched_term)


def _handle_translate(payload: dict[str, Any]) -> dict[str, Any]:
    """Start a translation and answer at once with whatever we know.

    Runs on the Qt main thread. Everything here must be non-blocking: a ``PENDING``
    answer is a promise to push the result later, not an invitation to wait for it.
    """

    request = parse_translate_payload(payload)
    provider, target_lang, cache_ttl = _translation_config()

    try:
        from .translation.service import TranslationService

        service = TranslationService(_bridge_controller())
        outcome = service.translate(
            text=request.text,
            provider=provider,
            target_lang=target_lang,
            cache_ttl_hours=cache_ttl,
            on_settled=_on_translation_settled,
        )
    except Exception:
        logger.exception("Anki Lookup translation request failed")
        return translation_result(
            request.request_id,
            request.popup_token,
            status=ERROR,
            message="The translation could not be started.",
            provider=provider,
        )

    if outcome.status == PENDING:
        with _translation_lock:
            _translation_jobs[outcome.job_id] = (
                request.request_id,
                request.popup_token,
                request.text,
            )

    return translation_result(
        request.request_id,
        request.popup_token,
        status=outcome.status,
        text=outcome.text,
        message=outcome.message,
        provider=provider,
        cached=outcome.cached,
        external_url=outcome.external_url,
    )


def _handle_translate_cancel(payload: dict[str, Any]) -> dict[str, Any]:
    request = parse_translate_cancel_payload(payload)

    with _translation_lock:
        job_ids = [
            job_id
            for job_id, (request_id, token, _) in _translation_jobs.items()
            if request_id == request.request_id and token == request.popup_token
        ]
        for job_id in job_ids:
            del _translation_jobs[job_id]

    try:
        controller = _bridge_controller()
        for job_id in job_ids:
            controller.broker.cancel(job_id)
    except Exception:
        logger.exception("Anki Lookup translation cancel failed")

    return {"status": "cancelled", "request_id": request.request_id}


def _handle_open_external(payload: dict[str, Any]) -> dict[str, Any]:
    """Open the provider's web translator with the text prefilled.

    Routed through Python rather than an ``<a href>`` in the webview: Anki's webviews
    intercept navigation inconsistently across versions, and coming through here means
    the clamped provider and target language win over anything the page believes.
    """

    request = parse_translate_payload(payload)
    provider, target_lang, _ = _translation_config()

    try:
        from aqt.utils import openLink

        from .translation.external import external_translate_url

        url = external_translate_url(provider, request.text, "auto", target_lang)
        openLink(url)
    except Exception:
        logger.exception("Anki Lookup could not open the external translator")
        return error_result("Could not open the translator.", request.request_id)

    return {"status": "opened", "request_id": request.request_id}


def _on_translation_settled(job_id: str, outcome: JobOutcome) -> None:
    """Route a settled job back to the popup that asked. Runs off the main thread."""

    from .webview_push import push_to_reviewer

    with _translation_lock:
        tracked = _translation_jobs.pop(job_id, None)

    if tracked is None:
        # Cancelled, or from a previous session. Still worth caching below.
        tracked = (0, "", "")

    request_id, popup_token, source_text = tracked
    provider, target_lang, cache_ttl = _translation_config()

    if outcome.ok and source_text:
        try:
            from .translation.service import TranslationService

            TranslationService(_bridge_controller()).store(
                source_text, provider, target_lang, outcome.text, cache_ttl
            )
        except Exception:
            logger.exception("Could not cache a settled translation")

    if not popup_token:
        return

    push_to_reviewer(
        translation_result(
            request_id,
            popup_token,
            status=READY if outcome.ok else ERROR,
            text=outcome.text,
            message=outcome.error,
            provider=provider,
        )
    )


def _translation_config() -> tuple[str, str, int]:
    settings = _translation_settings or runtime_config({})["translation"]
    return (
        str(settings["provider"]),
        str(settings["target_language"]),
        int(settings["cache_ttl_hours"]),
    )


def _bridge_controller() -> Any:
    from .runtime import bridge_controller

    return bridge_controller()


def apply_runtime_config(config: dict[str, Any]) -> None:
    global _frequency_sort_policy, _translation_settings, _notes_settings

    _translation_settings = dict(config["translation"])
    _notes_settings = dict(config["notes"])

    lookup = config["lookup"]
    dictionary_id = lookup["frequency_sort_dictionary_id"]
    _frequency_sort_policy = (
        FrequencySortPolicy(
            dictionary_id=dictionary_id,
            order=lookup["frequency_sort_order"],
        )
        if dictionary_id > 0
        else None
    )


def _is_reviewer(context: object | None) -> bool:
    try:
        from aqt.reviewer import Reviewer
    except ImportError:
        return False
    return isinstance(context, Reviewer)
