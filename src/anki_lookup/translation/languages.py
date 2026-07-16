"""Per-provider translation target languages.

The two lists are deliberately independent rather than one filtered by the other.
Neither is a superset: Norwegian is ``no`` for Google and ``nb`` for DeepL, which
rejects ``NO``. That is why switching provider re-checks the persisted code in both
directions instead of assuming Google's list covers DeepL's.

Codes stay lowercase ISO 639-1 because the extension interpolates them into a
provider URL verbatim (Google's ``?tl=``, DeepL's ``#<src>/<tgt>/<text>`` fragment).

``auto`` is absent from both on purpose: it is a source-detection sentinel and is
meaningless as a translation target.
"""

from __future__ import annotations

from .models import DEEPL

DEFAULT_TARGET_LANGUAGE = "en"

#: Google Translate's targets. Mirrors the desktop app's Whisper-derived list minus
#: the ``auto`` sentinel.
GOOGLE_TARGET_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("af", "Afrikaans"),
    ("am", "Amharic"),
    ("ar", "Arabic"),
    ("as", "Assamese"),
    ("az", "Azerbaijani"),
    ("ba", "Bashkir"),
    ("be", "Belarusian"),
    ("bg", "Bulgarian"),
    ("bn", "Bengali"),
    ("bo", "Tibetan"),
    ("br", "Breton"),
    ("bs", "Bosnian"),
    ("ca", "Catalan"),
    ("cs", "Czech"),
    ("cy", "Welsh"),
    ("da", "Danish"),
    ("de", "German"),
    ("el", "Greek"),
    ("en", "English"),
    ("es", "Spanish"),
    ("et", "Estonian"),
    ("eu", "Basque"),
    ("fa", "Persian"),
    ("fi", "Finnish"),
    ("fo", "Faroese"),
    ("fr", "French"),
    ("gl", "Galician"),
    ("gu", "Gujarati"),
    ("ha", "Hausa"),
    ("haw", "Hawaiian"),
    ("he", "Hebrew"),
    ("hi", "Hindi"),
    ("hr", "Croatian"),
    ("ht", "Haitian Creole"),
    ("hu", "Hungarian"),
    ("hy", "Armenian"),
    ("id", "Indonesian"),
    ("is", "Icelandic"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("jw", "Javanese"),
    ("ka", "Georgian"),
    ("kk", "Kazakh"),
    ("km", "Khmer"),
    ("kn", "Kannada"),
    ("ko", "Korean"),
    ("la", "Latin"),
    ("lb", "Luxembourgish"),
    ("ln", "Lingala"),
    ("lo", "Lao"),
    ("lt", "Lithuanian"),
    ("lv", "Latvian"),
    ("mg", "Malagasy"),
    ("mi", "Maori"),
    ("mk", "Macedonian"),
    ("ml", "Malayalam"),
    ("mn", "Mongolian"),
    ("mr", "Marathi"),
    ("ms", "Malay"),
    ("mt", "Maltese"),
    ("my", "Myanmar"),
    ("ne", "Nepali"),
    ("nl", "Dutch"),
    ("nn", "Nynorsk"),
    ("no", "Norwegian"),
    ("oc", "Occitan"),
    ("pa", "Punjabi"),
    ("pl", "Polish"),
    ("ps", "Pashto"),
    ("pt", "Portuguese"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sa", "Sanskrit"),
    ("sd", "Sindhi"),
    ("si", "Sinhala"),
    ("sk", "Slovak"),
    ("sl", "Slovenian"),
    ("sn", "Shona"),
    ("so", "Somali"),
    ("sq", "Albanian"),
    ("sr", "Serbian"),
    ("su", "Sundanese"),
    ("sv", "Swedish"),
    ("sw", "Swahili"),
    ("ta", "Tamil"),
    ("te", "Telugu"),
    ("tg", "Tajik"),
    ("th", "Thai"),
    ("tk", "Turkmen"),
    ("tl", "Tagalog"),
    ("tr", "Turkish"),
    ("tt", "Tatar"),
    ("uk", "Ukrainian"),
    ("ur", "Urdu"),
    ("uz", "Uzbek"),
    ("vi", "Vietnamese"),
    ("yi", "Yiddish"),
    ("yo", "Yoruba"),
    ("yue", "Cantonese"),
    ("zh", "Chinese"),
)

#: DeepL's targets, limited to the long-standing API v2 set. Anything newer or
#: beta-only is left out on purpose: a wrong entry here fails at translate time
#: rather than at selection time.
#:
#: Bare ``en``/``pt`` are correct despite DeepL wanting ``EN-US``/``PT-PT`` — the
#: extension holds that mapping itself and upper-cases everything else, so regional
#: variants must NOT be added.
DEEPL_TARGET_LANGUAGES: tuple[tuple[str, str], ...] = (
    ("ar", "Arabic"),
    ("bg", "Bulgarian"),
    ("cs", "Czech"),
    ("da", "Danish"),
    ("de", "German"),
    ("el", "Greek"),
    ("en", "English"),
    ("es", "Spanish"),
    ("et", "Estonian"),
    ("fi", "Finnish"),
    ("fr", "French"),
    ("hu", "Hungarian"),
    ("id", "Indonesian"),
    ("it", "Italian"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("lt", "Lithuanian"),
    ("lv", "Latvian"),
    ("nb", "Norwegian Bokmal"),
    ("nl", "Dutch"),
    ("pl", "Polish"),
    ("pt", "Portuguese"),
    ("ro", "Romanian"),
    ("ru", "Russian"),
    ("sk", "Slovak"),
    ("sl", "Slovenian"),
    ("sv", "Swedish"),
    ("tr", "Turkish"),
    ("uk", "Ukrainian"),
    ("zh", "Chinese"),
)


def target_languages_for(provider: str) -> tuple[tuple[str, str], ...]:
    """Return the ``(code, label)`` targets the given provider accepts."""

    if provider == DEEPL:
        return DEEPL_TARGET_LANGUAGES
    return GOOGLE_TARGET_LANGUAGES


def normalize_target_language(value: object, provider: str) -> str:
    """Return a target code the provider actually accepts.

    Unlike the desktop app — which normalizes format only and lets an unsupported
    code surface as a confusing bridge error at translate time — this checks the
    code against the provider's list and falls back to English. The add-on has no
    toast to correct the user with after the fact.
    """

    if not isinstance(value, str):
        return DEFAULT_TARGET_LANGUAGE

    code = value.strip().casefold()
    if any(code == candidate for candidate, _ in target_languages_for(provider)):
        return code
    return DEFAULT_TARGET_LANGUAGE


def target_language_label(code: str, provider: str) -> str:
    for candidate, label in target_languages_for(provider):
        if candidate == code:
            return label
    return code
