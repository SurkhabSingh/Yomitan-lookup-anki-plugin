"""No-key fallback: open the provider's official web translator.

This is the path that always works — no API key, no desktop app, no extension. The
roadmap's "Non-Negotiable Technical Constraint" blesses exactly this: no-key
Google/DeepL support means opening the official translator with the text prefilled.

The URL shapes mirror what the extension's own page-automation providers drive, so
the user lands on the same page they would have got inline.

The JavaScript half of this lives in ``web/scanner-core.js``. Both are driven by the
same fixture (``tests/fixtures/external_urls.json``) so they cannot drift.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from .models import DEEPL, GOOGLE_TRANSLATE

#: Cap on the text pushed into a URL. Browsers and the providers both start
#: truncating or rejecting somewhere past a couple of thousand characters, and a
#: captured sentence is a fraction of this. Kept under the protocol's own sentence
#: ceiling so a valid sentence always fits.
MAX_EXTERNAL_TEXT_LENGTH = 1_800

AUTO_SOURCE = "auto"


def truncate_for_external_url(text: str) -> str:
    return text[:MAX_EXTERNAL_TEXT_LENGTH]


def external_translate_url(
    provider: str,
    text: str,
    source_lang: str = AUTO_SOURCE,
    target_lang: str = "en",
) -> str:
    """Return the provider's web translator URL with ``text`` prefilled."""

    trimmed = truncate_for_external_url(text)
    source = source_lang or AUTO_SOURCE
    target = target_lang or "en"

    if provider == DEEPL:
        # DeepL carries the text in the fragment, not the query: #<src>/<tgt>/<text>.
        # The source sentinel is "auto" there too, but written as an empty segment is
        # invalid, so "auto" stays literal.
        return (
            "https://www.deepl.com/translator"
            f"#{quote(source, safe='')}/{quote(target, safe='')}/{quote(trimmed, safe='')}"
        )

    query = urlencode({"sl": source, "tl": target, "text": trimmed, "op": "translate"})
    return f"https://translate.google.com/?{query}"


def is_supported_provider(provider: object) -> bool:
    return provider in (GOOGLE_TRANSLATE, DEEPL)
