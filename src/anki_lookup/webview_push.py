"""Push results into the reviewer webview after the fact.

The ``pycmd`` handler runs on the Qt main thread and must return immediately, so
anything that waits on a browser — a translation — has to be delivered later, from
whichever thread settled it. This is that channel.

Two rules, both load-bearing:

* **Hop to the main thread.** Touching a webview off the Qt main thread is undefined
  behaviour, and the callers here are HTTP server threads. ``taskman.run_on_main``
  is the supported way across.
* **Assume the page is gone.** Between submitting and settling, the user may have
  answered the card, closed the popup, or opened another. The ``&&`` guard covers a
  reloaded page; the popup token covers everything else, on the JavaScript side.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

#: The JavaScript entry point popup.js installs to receive pushed results.
RECEIVER = "window.AnkiLookupPushResult"


def encode_payload(payload: dict[str, Any]) -> str:
    """Encode a payload for embedding in a JavaScript context.

    Shared by every site that drops JSON into JavaScript — the ``web.eval`` expressions
    here and in the settings/preset dialogs, and the ``<script>`` body injected at
    reviewer load in ``hooks.py`` — so they all escape identically.

    ``ensure_ascii=True`` escapes U+2028 and U+2029 for free: both are valid inside JSON
    strings but are line terminators in JavaScript, which historically broke inline
    scripts. The ``</`` guard prevents a value from closing the surrounding ``<script>``
    element.
    """

    return json.dumps(payload, ensure_ascii=True).replace("</", "<\\/")


def push_to_reviewer(payload: dict[str, Any]) -> None:
    """Deliver a payload to the reviewer webview, from any thread. Never raises."""

    try:
        from aqt import mw

        if mw is None:
            return

        script = f"{RECEIVER} && {RECEIVER}({encode_payload(payload)});"
        mw.taskman.run_on_main(lambda: _eval_in_reviewer(script))
    except Exception:
        logger.exception("Could not push a result to the reviewer")


def _eval_in_reviewer(script: str) -> None:
    """Run on the Qt main thread only."""

    try:
        from aqt import mw

        reviewer = getattr(mw, "reviewer", None) if mw is not None else None
        web = getattr(reviewer, "web", None)
        if web is None:
            # The user left the reviewer. The result is already cached; nothing to do.
            return
        web.eval(script)
    except Exception:
        logger.exception("Could not evaluate a pushed result in the reviewer")
