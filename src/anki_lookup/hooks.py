"""Reviewer webview integration."""

from __future__ import annotations

import json
import logging
from typing import Any

from .config import runtime_config
from .dictionary import FrequencySortPolicy
from .protocol import error_result, lookup_result, parse_lookup_message
from .runtime import dictionary_service

_registered = False
_frequency_sort_policy: FrequencySortPolicy | None = None
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
        request = parse_lookup_message(message)
    except (ValueError, json.JSONDecodeError) as error:
        if message.startswith("anki_lookup:"):
            return (True, error_result(str(error)))
        return handled

    if request is None:
        return handled

    try:
        matched_term, entries = dictionary_service().lookup_candidates(
            request.candidates,
            request.term,
            frequency_sort=_frequency_sort_policy,
        )
    except Exception:
        logger.exception("Anki Lookup dictionary lookup failed")
        return (True, error_result("Dictionary lookup failed.", request.request_id))
    return (True, lookup_result(request, entries, matched_term))


def apply_runtime_config(config: dict[str, Any]) -> None:
    global _frequency_sort_policy

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
