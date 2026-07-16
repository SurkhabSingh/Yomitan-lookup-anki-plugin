"""Map lookup results onto a deck, note type, and fields."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..config import runtime_config
from ..notes.field_mapping import normalize_mapping
from ..notes.markers import MarkerRegistry, build_registry

#: A guess per field name, so a first-time user opens the editor on a working preset
#: rather than a column of empty boxes. Matched against the whole field name, case
#: insensitively. Guessing wrong costs one edit; guessing nothing costs eight.
_FIELD_NAME_GUESSES = {
    "front": "{expression}",
    "expression": "{expression}",
    "word": "{expression}",
    "term": "{expression}",
    "vocab": "{expression}",
    "vocabulary": "{expression}",
    "kanji": "{expression}",
    "character": "{character}",
    "reading": "{reading}",
    "kana": "{reading}",
    "pronunciation": "{reading}",
    "furigana": "{furigana}",
    "back": "{glossary}",
    "definition": "{glossary}",
    "meaning": "{glossary}",
    "glossary": "{glossary}",
    "gloss": "{glossary}",
    "sentence": "{sentence}",
    "context": "{sentence}",
    "example": "{sentence}",
    # The reason the cloze markers exist: the sentence with the scanned word marked.
    "cloze": "{cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}",
    "translation": "{translation}",
    "dictionary": "{dictionary}",
    "source": "{source-deck}",
    "deck": "{source-deck}",
    "tags": "{tags}",
    "frequency": "{frequency-harmonic-rank}",
    "freq": "{frequency-harmonic-rank}",
    "pitch": "{pitch-accent-graphs}",
    "accent": "{pitch-accent-graphs}",
    "onyomi": "{onyomi}",
    "kunyomi": "{kunyomi}",
    "strokes": "{stroke-count}",
    # No "audio" guess: unknown markers are left as typed (they may be Anki template
    # references), so guessing {audio} before that marker exists would put the literal
    # text "{audio}" on every card with an Audio field.
}


def guess_value_for_field(field_name: str) -> str:
    """Guess a field's value from its name, or leave it blank."""

    return _FIELD_NAME_GUESSES.get(field_name.strip().casefold(), "")


class NotePresetEditor:
    """Configure which lookup values land in which note fields."""

    def __init__(self, parent: Any) -> None:
        from aqt import mw
        from aqt.qt import (
            QCheckBox,
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFormLayout,
            QLabel,
            QLineEdit,
            QVBoxLayout,
            QWidget,
        )

        if mw is None or mw.col is None:
            raise RuntimeError("Anki is unavailable")

        self._mw = mw
        self._addon_manager = mw.addonManager
        self._package = self._addon_manager.addonFromModule(__name__)
        raw_config = self._addon_manager.getConfig(self._package)
        self._raw_config = deepcopy(raw_config) if isinstance(raw_config, dict) else {}
        self._preset = runtime_config(raw_config)["notes"]

        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("Anki Lookup Note Preset")
        self.dialog.resize(560, 460)
        layout = QVBoxLayout(self.dialog)

        description = QLabel(
            "Choose where a note created from a lookup result should go, and which "
            "lookup value fills each field. Notes are added with Anki's normal undo "
            "support, and the card you are reviewing is never modified."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()

        self.deck = QComboBox()
        for deck in sorted(mw.col.decks.all_names_and_ids(), key=lambda item: item.name):
            self.deck.addItem(deck.name, deck.id)
        self._select_data(self.deck, self._preset["deck_id"])
        form.addRow("Deck", self.deck)

        self.notetype = QComboBox()
        for notetype in sorted(mw.col.models.all_names_and_ids(), key=lambda item: item.name):
            self.notetype.addItem(notetype.name, notetype.id)
        self._select_data(self.notetype, self._preset["notetype_id"])
        form.addRow("Note type", self.notetype)

        self.tags = QLineEdit(" ".join(self._preset["tags"]))
        self.tags.setPlaceholderText("anki-lookup")
        self.tags.setToolTip("Space-separated tags added to every note created here.")
        form.addRow("Tags", self.tags)

        self.check_duplicates = QCheckBox("Warn before adding a note that already exists")
        self.check_duplicates.setChecked(self._preset["check_duplicates"])
        form.addRow("", self.check_duplicates)

        self.duplicate_field = QComboBox()
        form.addRow("Check for duplicates in", self.duplicate_field)

        layout.addLayout(form)

        fields_label = QLabel("Fields")
        layout.addWidget(fields_label)

        self.fields_container = QWidget()
        self.fields_form = QFormLayout(self.fields_container)
        layout.addWidget(self.fields_container)

        self._registry: MarkerRegistry = build_registry(self._dictionary_titles())
        self._field_editors: dict[str, Any] = {}
        self._rebuild_fields()

        self.notetype.currentIndexChanged.connect(self._rebuild_fields)
        self.check_duplicates.stateChanged.connect(self._update_duplicate_field_state)
        self._update_duplicate_field_state()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(buttons)

    def show(self) -> None:
        self.dialog.exec()

    def _select_data(self, combo: Any, value: Any) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))

    def _dictionary_titles(self) -> tuple[str, ...]:
        """Installed dictionary names, for the per-dictionary glossary markers."""

        from ..runtime import dictionary_service

        try:
            return tuple(item.title for item in dictionary_service().list_dictionaries())
        except Exception:
            # No dictionaries yet, or the database is unreachable. The built-in markers
            # are still worth offering.
            return ()

    def _current_field_names(self) -> list[str]:
        notetype_id = self.notetype.currentData()
        if notetype_id is None:
            return []
        notetype = self._mw.col.models.get(notetype_id)
        if notetype is None:
            return []
        return [field["name"] for field in notetype["flds"]]

    def _rebuild_fields(self) -> None:
        """Rebuild the per-field rows for the selected note type.

        Existing values are kept where the field still exists, so switching note types
        to look and switching back does not discard the user's work.
        """

        from aqt.qt import QHBoxLayout, QLineEdit, QPushButton, QWidget

        existing = {record["field"]: record["value"] for record in self._current_mapping()}

        while self.fields_form.rowCount():
            self.fields_form.removeRow(0)
        self._field_editors = {}

        for field_name in self._current_field_names():
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)

            editor = QLineEdit(existing.get(field_name, guess_value_for_field(field_name)))
            editor.setPlaceholderText("{expression}")
            editor.setToolTip(
                "Text with {markers} in it. Anything else is kept as typed, so a field "
                "can combine them: {cloze-prefix}<b>{cloze-body}</b>{cloze-suffix}"
            )
            row_layout.addWidget(editor)

            insert = QPushButton("Insert...")
            insert.setToolTip("Insert a marker at the cursor")
            insert.clicked.connect(
                lambda _=False, target=editor, b=insert: self._insert_marker(target, b)
            )
            row_layout.addWidget(insert)

            self.fields_form.addRow(field_name, row)
            self._field_editors[field_name] = editor

        self._rebuild_duplicate_field()

    def _insert_marker(self, editor: Any, button: Any) -> None:
        """Offer the markers, grouped, and insert the chosen one at the cursor.

        Built from the registry rather than a list kept alongside it: a menu that is
        maintained separately drifts, and ends up offering markers that render nothing.
        Appends rather than replaces, because a field is text that may hold several.
        """

        from aqt.qt import QMenu

        menu = QMenu(self.dialog)
        entry_type = "kanji" if self._notetype_looks_like_kanji() else "term"

        for group, markers in self._registry.grouped(entry_type):
            submenu = menu.addMenu(group)
            for marker in markers:
                action = submenu.addAction(marker.name)
                action.setToolTip(marker.description)
                action.triggered.connect(
                    lambda _=False, name=marker.name, target=editor: target.insert(f"{{{name}}}")
                )

        menu.exec(button.mapToGlobal(button.rect().bottomLeft()))

    def _notetype_looks_like_kanji(self) -> bool:
        """Whether to offer kanji markers or term markers.

        A guess from the note type's name, and deliberately a loose one: the preset is
        per note type but a lookup can return either kind, so this only decides which
        markers are *offered*. Rendering already skips a marker that does not apply.
        """

        name = str(self.notetype.currentText() or "").casefold()
        return "kanji" in name or "漢字" in name

    def _rebuild_duplicate_field(self) -> None:
        previous = self.duplicate_field.currentData()
        self.duplicate_field.clear()
        field_names = self._current_field_names()
        for field_name in field_names:
            self.duplicate_field.addItem(field_name, field_name)

        target = previous if previous in field_names else self._preset["duplicate_field"]
        index = self.duplicate_field.findData(target)
        self.duplicate_field.setCurrentIndex(max(0, index))

    def _update_duplicate_field_state(self) -> None:
        self.duplicate_field.setEnabled(self.check_duplicates.isChecked())

    def _current_mapping(self) -> list[dict[str, str]]:
        if not self._field_editors:
            return normalize_mapping(self._preset["field_mapping"])
        return [
            {"field": field_name, "value": editor.text()}
            for field_name, editor in self._field_editors.items()
        ]

    def _save(self) -> None:
        from aqt.utils import showWarning, tooltip

        mapping = [record for record in self._current_mapping() if record["value"].strip()]
        if not mapping:
            showWarning(
                "Give at least one field a value, otherwise a created note would be empty.",
                parent=self.dialog,
            )
            return

        candidate = deepcopy(self._raw_config)
        notes = candidate.setdefault("notes", {})
        notes["deck_id"] = int(self.deck.currentData() or 0)
        notes["notetype_id"] = int(self.notetype.currentData() or 0)
        notes["field_mapping"] = self._current_mapping()
        notes["tags"] = self.tags.text().split()
        notes["check_duplicates"] = self.check_duplicates.isChecked()
        notes["duplicate_field"] = self.duplicate_field.currentData() or ""

        self._addon_manager.writeConfig(self._package, candidate)
        self._apply_to_reviewer(runtime_config(candidate))
        self.dialog.accept()
        tooltip("Anki Lookup note preset saved.", parent=self.dialog)

    def _apply_to_reviewer(self, config: dict[str, Any]) -> None:
        import json

        from ..hooks import apply_runtime_config

        apply_runtime_config(config)
        reviewer = getattr(self._mw, "reviewer", None)
        web = getattr(reviewer, "web", None)
        if web is None:
            return
        payload = json.dumps(config, ensure_ascii=False).replace("</", "<\\/")
        web.eval(f"window.AnkiLookupApplyConfig && window.AnkiLookupApplyConfig({payload});")


def show_note_preset_editor(parent: Any) -> None:
    NotePresetEditor(parent).show()
