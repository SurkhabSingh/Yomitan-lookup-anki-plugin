"""Map lookup results onto a deck, note type, and fields."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from ..config import runtime_config
from ..notes.duplicates import SCOPE_COLLECTION, SCOPE_DECK
from ..notes.field_mapping import normalize_mapping
from ..notes.markers import MarkerRegistry, build_registry

#: Where to look for an existing note. "This deck" covers its subdecks, following
#: Anki's own deck: semantics.
DUPLICATE_SCOPES = (
    ("This deck and its subdecks", SCOPE_DECK),
    ("The whole collection", SCOPE_COLLECTION),
)

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
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QPushButton,
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

        # Static options, so unlike the field combo this is filled in here rather than
        # rebuilt whenever the note type changes.
        self.duplicate_scope = QComboBox()
        for label, value in DUPLICATE_SCOPES:
            self.duplicate_scope.addItem(label, value)
        self._select_data(self.duplicate_scope, self._preset["duplicate_scope"])
        self.duplicate_scope.setToolTip(
            "A word saved in another deck is not a duplicate of one you are adding "
            "here. Searching this deck also covers its subdecks, the same way deck: "
            "does in the card browser."
        )
        form.addRow("Look for them in", self.duplicate_scope)

        layout.addLayout(form)

        quick = QHBoxLayout()
        recommended_button = QPushButton("Use recommended note type")
        recommended_button.setToolTip(
            "Create (or reuse) the 'Anki Lookup' note type and fill its fields. Your "
            "deck choice is left as is."
        )
        recommended_button.clicked.connect(self._use_recommended_note_type)
        quick.addWidget(recommended_button)

        import_button = QPushButton("Import from Yomitan...")
        import_button.setToolTip(
            "Fill this preset from a Yomitan settings backup, so you do not have to "
            "redo the deck, note type, and field mapping."
        )
        import_button.clicked.connect(self._import_from_yomitan)
        quick.addWidget(import_button)
        quick.addStretch(1)
        layout.addLayout(quick)

        fields_label = QLabel("Fields")
        layout.addWidget(fields_label)

        self.fields_container = QWidget()
        self.fields_form = QFormLayout(self.fields_container)
        layout.addWidget(self.fields_container)

        self._registry: MarkerRegistry = build_registry(self._dictionary_titles())
        self._field_editors: dict[str, Any] = {}
        self._rebuild_fields()

        self.notetype.currentIndexChanged.connect(self._rebuild_fields)
        self.check_duplicates.stateChanged.connect(self._update_duplicate_controls)
        self._update_duplicate_controls()

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

    def _update_duplicate_controls(self) -> None:
        """Both duplicate controls are meaningless when checking is off."""

        enabled = self.check_duplicates.isChecked()
        self.duplicate_field.setEnabled(enabled)
        self.duplicate_scope.setEnabled(enabled)

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
        notes["duplicate_scope"] = self.duplicate_scope.currentData() or SCOPE_DECK

        self._addon_manager.writeConfig(self._package, candidate)
        self._apply_to_reviewer(runtime_config(candidate))
        self.dialog.accept()
        tooltip("Anki Lookup note preset saved.", parent=self.dialog)

    def _use_recommended_note_type(self) -> None:
        """Create (or reuse) the recommended note type and fill its fields.

        Nothing is written until Save — this only fills the editor, same as picking a
        note type by hand.
        """

        from aqt.utils import showWarning, tooltip

        from ..notes.recommended import NOTE_TYPE_NAME, ensure_note_type, preset_field_mapping

        try:
            notetype_id = ensure_note_type(self._mw.col)
        except Exception:
            showWarning(
                "Anki Lookup could not create the recommended note type.",
                parent=self.dialog,
            )
            return

        # The combo was populated at open time, so a note type created just now is not
        # in it yet; add it, then select it (which rebuilds the field rows).
        if self.notetype.findData(notetype_id) < 0:
            self.notetype.addItem(NOTE_TYPE_NAME, notetype_id)
        self._select_data(self.notetype, notetype_id)
        self._rebuild_fields()

        self._apply_field_values(preset_field_mapping())
        tooltip("Recommended note type ready. Review and Save.", parent=self.dialog)

    def _import_from_yomitan(self) -> None:
        """Fill the preset from a Yomitan settings backup. Fills only; never saves."""

        from aqt.qt import QFileDialog
        from aqt.utils import showInfo, showWarning

        from ..notes.yomitan_import import YomitanImportError, parse_backup

        path, _ = QFileDialog.getOpenFileName(
            self.dialog,
            "Import from Yomitan settings backup",
            "",
            "Yomitan settings (*.json);;All files (*)",
        )
        if not path:
            return

        try:
            text = Path(path).read_text(encoding="utf-8")
            result = parse_backup(text)
        except YomitanImportError as error:
            showWarning(str(error), parent=self.dialog)
            return
        except OSError as error:
            showWarning(f"Could not read the file: {error}", parent=self.dialog)
            return

        preset = self._choose_imported_preset(result.presets)
        if preset is None:
            return

        notetype_id = self._resolve_model(preset.model_name)
        if notetype_id is None:
            return  # _resolve_model has already explained why.

        deck_id = self._resolve_deck(preset.deck_name)
        if deck_id is None:
            return

        self._select_data(self.deck, deck_id)
        self._select_data(self.notetype, notetype_id)
        self._rebuild_fields()

        applied, unknown_fields = self._apply_field_values(preset.field_mapping)
        if preset.tags:
            self.tags.setText(" ".join(preset.tags))
        self.check_duplicates.setChecked(preset.check_duplicates)
        self._select_data(self.duplicate_scope, preset.duplicate_scope)
        self._update_duplicate_controls()

        showInfo(
            self._import_summary(preset, applied, unknown_fields),
            parent=self.dialog,
        )

    def _choose_imported_preset(self, presets: list[Any]) -> Any:
        """Pick which card format to import when the backup holds several."""

        if len(presets) == 1:
            return presets[0]

        from aqt.qt import QInputDialog

        labels = [f"{p.name} ({p.note_type})" for p in presets]
        choice, ok = QInputDialog.getItem(
            self.dialog,
            "Choose a note format",
            "This Yomitan backup has several. Which do you want to import?",
            labels,
            0,
            False,
        )
        if not ok:
            return None
        return presets[labels.index(choice)]

    def _resolve_model(self, model_name: str) -> int | None:
        """Map a Yomitan model name to a note type id, or explain why we cannot.

        We cannot invent a note type from an import: its fields are what the mapping
        targets. A missing one is a hard stop with a clear message, not a half-fill.
        """

        from aqt.utils import showWarning

        if not model_name:
            showWarning(
                "The Yomitan backup did not name a note type for this format.",
                parent=self.dialog,
            )
            return None

        model_id = self._mw.col.models.id_for_name(model_name)
        if model_id is None:
            showWarning(
                f"Your Yomitan settings use the note type '{model_name}', which this "
                "Anki profile does not have. Create it in Anki (or import the note type "
                "Yomitan expects), then import again.",
                parent=self.dialog,
            )
            return None
        return int(model_id)

    def _resolve_deck(self, deck_name: str) -> int | None:
        """Map a Yomitan deck name to a deck id, offering to create a missing one."""

        from aqt.utils import askUser

        if not deck_name:
            # No deck named; keep whatever the editor already had.
            return int(self.deck.currentData() or 0) or None

        existing = self._mw.col.decks.id_for_name(deck_name)
        if existing is not None:
            return int(existing)

        if not askUser(
            f"Your Yomitan settings use the deck '{deck_name}', which does not exist "
            "here yet. Create it?",
            parent=self.dialog,
        ):
            return int(self.deck.currentData() or 0) or None

        created = self._mw.col.decks.id(deck_name, create=True)
        if self.deck.findData(created) < 0:
            self.deck.addItem(deck_name, created)
        return int(created) if created is not None else None

    def _apply_field_values(self, mapping: list[dict[str, str]]) -> tuple[list[str], list[str]]:
        """Set the field editors from a mapping, by field name.

        Returns the fields that were filled and the mapped fields the note type does
        not have (so an import can report what could not be placed).
        """

        applied: list[str] = []
        unknown: list[str] = []
        for record in mapping:
            editor = self._field_editors.get(record["field"])
            if editor is None:
                unknown.append(record["field"])
                continue
            editor.setText(record["value"])
            applied.append(record["field"])
        return applied, unknown

    def _import_summary(self, preset: Any, applied: list[str], unknown_fields: list[str]) -> str:
        lines = [f"Imported '{preset.name}' from Yomitan.", ""]
        lines.append(f"Filled {len(applied)} field(s). Review, then Save.")

        if unknown_fields:
            lines += [
                "",
                "These fields were in your Yomitan setup but are not on this note type, "
                "so they were skipped:",
                "  " + ", ".join(unknown_fields),
            ]

        dropped = sorted({marker for _, marker in preset.dropped_markers})
        if dropped:
            lines += [
                "",
                "These Yomitan markers are not supported and were removed from the field values:",
                "  " + ", ".join("{" + marker + "}" for marker in dropped),
            ]

        return "\n".join(lines)

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
