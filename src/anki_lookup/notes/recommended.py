"""A recommended Anki note type, and the preset that fills it.

The desktop app creates no note type of its own — it maps its data onto whatever note
type the user already has. So this note type is the shared convention both sides can
target: its field names are chosen so the app's roles (transcription, furigana, audio,
translation, source), our markers, and the preset editor's field-name guesser all line
up.

The field/marker table here is pure and testable. Creating the note type touches Anki
and lives in a function that imports ``aqt`` lazily, the same convention the rest of
``ui``/``notes`` follows.
"""

from __future__ import annotations

from typing import Any

#: The note type's name. Stable, because idempotency keys on it: creating twice finds
#: the existing one rather than making a second.
NOTE_TYPE_NAME = "Anki Lookup"

CARD_TEMPLATE_NAME = "Recognition"

#: (field name, the preset value that fills it). Order is the field order in Anki.
#:
#: Audio is intentionally blank: this add-on ships no ``{audio}`` marker, and the
#: field exists so the Wonder of U desktop app can fill it over AnkiConnect. The field
#: names match the editor's guess table, so importing or re-picking this note type
#: auto-fills the same values.
FIELDS: tuple[tuple[str, str], ...] = (
    ("Expression", "{expression}"),
    ("Reading", "{reading}"),
    ("Furigana", "{furigana-plain}"),
    ("Glossary", "{glossary}"),
    ("Sentence", "{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}"),
    ("Translation", "{translation}"),
    ("Pitch", "{pitch-accent-graphs}"),
    ("Frequency", "{frequency-harmonic-rank}"),
    ("Audio", ""),
    ("Source", "{source-deck}"),
)

FIELD_NAMES: tuple[str, ...] = tuple(name for name, _ in FIELDS)

#: The card front: the word alone, so the reviewer recalls the rest.
FRONT_TEMPLATE = '<div class="expression">{{Expression}}</div>'

#: The back. ``{{#Field}}…{{/Field}}`` guards make an empty field collapse, so a note
#: made without pitch or audio does not leave a labelled blank. ``{{furigana:Furigana}}``
#: is Anki's own filter, which is why the Furigana field uses ``{furigana-plain}``.
BACK_TEMPLATE = "\n".join(
    [
        "{{FrontSide}}",
        '<hr id="answer">',
        '{{#Reading}}<div class="reading">{{Reading}}</div>{{/Reading}}',
        '{{#Furigana}}<div class="furigana">{{furigana:Furigana}}</div>{{/Furigana}}',
        '{{#Pitch}}<div class="pitch">{{Pitch}}</div>{{/Pitch}}',
        '{{#Glossary}}<div class="glossary">{{Glossary}}</div>{{/Glossary}}',
        '{{#Sentence}}<div class="sentence">{{Sentence}}</div>{{/Sentence}}',
        '{{#Translation}}<div class="translation">{{Translation}}</div>{{/Translation}}',
        '{{#Frequency}}<div class="frequency">Frequency: {{Frequency}}</div>{{/Frequency}}',
        "{{#Audio}}{{Audio}}{{/Audio}}",
    ]
)

#: Self-contained: Anki cards do not see the add-on's stylesheet.
CARD_CSS = "\n".join(
    [
        ".card {",
        "  font-family: sans-serif;",
        "  font-size: 20px;",
        "  text-align: center;",
        "  color: black;",
        "  background: white;",
        "}",
        ".expression { font-size: 40px; }",
        ".reading { color: #666; }",
        ".glossary { text-align: left; margin: 12px auto; max-width: 40em; }",
        ".sentence { margin: 12px auto; max-width: 40em; }",
        ".translation { color: #666; margin: 8px auto; max-width: 40em; }",
        ".frequency { color: #999; font-size: 15px; }",
        ".nightMode.card { color: white; background: #2b2b2b; }",
        ".nightMode .reading, .nightMode .translation { color: #aaa; }",
    ]
)


def preset_field_mapping() -> list[dict[str, str]]:
    """The field mapping that fills this note type. Our ``{"field", "value"}`` shape."""

    return [{"field": name, "value": value} for name, value in FIELDS]


def ensure_note_type(col: Any) -> int:
    """Return the id of the recommended note type, creating it if absent.

    Idempotent: keyed on the name, so a second call returns the same id rather than
    making a duplicate. Anki does not enforce unique note-type names, so the guard is
    ours to make.
    """

    existing = col.models.id_for_name(NOTE_TYPE_NAME)
    if existing is not None:
        return int(existing)

    models = col.models
    notetype = models.new(NOTE_TYPE_NAME)
    for name in FIELD_NAMES:
        models.add_field(notetype, models.new_field(name))

    template = models.new_template(CARD_TEMPLATE_NAME)
    template["qfmt"] = FRONT_TEMPLATE
    template["afmt"] = BACK_TEMPLATE
    models.add_template(notetype, template)

    notetype["css"] = CARD_CSS

    changes = models.add(notetype)
    return int(changes.id)
