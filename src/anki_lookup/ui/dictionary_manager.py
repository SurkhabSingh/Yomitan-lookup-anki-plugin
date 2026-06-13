"""Native dictionary management dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..dictionary import BatchImportResult, DictionaryInfo
from ..runtime import dictionary_service


class DictionaryManager:
    """Own a Qt dialog without importing Qt outside Anki."""

    def __init__(self, parent: Any) -> None:
        from aqt.qt import (
            QAbstractItemView,
            QDialog,
            QDialogButtonBox,
            QFileDialog,
            QHBoxLayout,
            QLabel,
            QListWidget,
            QListWidgetItem,
            QPushButton,
            Qt,
            QVBoxLayout,
        )

        self._qt = {
            "QFileDialog": QFileDialog,
            "QListWidgetItem": QListWidgetItem,
            "Qt": Qt,
        }
        self._updating = False
        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("Anki Lookup Dictionaries")
        self.dialog.resize(720, 460)

        layout = QVBoxLayout(self.dialog)
        description = QLabel(
            "Import Yomitan format-3 term, kanji, frequency, pitch, and IPA dictionaries. "
            "Dictionary files stay on this computer and are indexed in Anki Lookup's "
            "user data."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.list_widget.itemChanged.connect(self._on_item_changed)
        self.list_widget.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.list_widget, 1)

        action_layout = QHBoxLayout()
        self.import_button = QPushButton("Import Dictionaries...")
        self.remove_button = QPushButton("Remove Selected")
        self.up_button = QPushButton("Move Up")
        self.down_button = QPushButton("Move Down")
        action_layout.addWidget(self.import_button)
        action_layout.addWidget(self.remove_button)
        action_layout.addStretch(1)
        action_layout.addWidget(self.up_button)
        action_layout.addWidget(self.down_button)
        layout.addLayout(action_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(buttons)

        self.import_button.clicked.connect(self._choose_import)
        self.remove_button.clicked.connect(self._remove_selected)
        self.up_button.clicked.connect(lambda: self._move_selected(-1))
        self.down_button.clicked.connect(lambda: self._move_selected(1))
        self.refresh()

    def show(self) -> None:
        self.dialog.exec()

    def refresh(self, select_id: int | None = None) -> None:
        dictionaries = dictionary_service().list_dictionaries()
        Qt = self._qt["Qt"]
        QListWidgetItem = self._qt["QListWidgetItem"]

        self._updating = True
        try:
            self.list_widget.clear()
            for dictionary in dictionaries:
                item = QListWidgetItem(_dictionary_label(dictionary))
                item.setData(Qt.ItemDataRole.UserRole, dictionary.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked if dictionary.enabled else Qt.CheckState.Unchecked
                )
                item.setToolTip(
                    f"Revision: {dictionary.revision}\n"
                    f"Format: {dictionary.format}\n"
                    f"Terms: {dictionary.term_count:,}\n"
                    f"Kanji: {dictionary.kanji_count:,}\n"
                    f"Metadata: {dictionary.metadata_count:,}\n"
                    f"Frequency mode: {dictionary.frequency_mode or 'not specified'}"
                )
                self.list_widget.addItem(item)
                if dictionary.id == select_id:
                    self.list_widget.setCurrentItem(item)
        finally:
            self._updating = False
        self._update_buttons()

    def _choose_import(self) -> None:
        QFileDialog = self._qt["QFileDialog"]
        filenames, _ = QFileDialog.getOpenFileNames(
            self.dialog,
            "Import Yomitan Dictionaries",
            "",
            "Yomitan dictionaries (*.zip);;ZIP archives (*.zip)",
        )
        if not filenames:
            return

        from aqt import mw
        from aqt.operations import QueryOp
        from aqt.utils import showWarning

        self._set_busy(True)
        (
            QueryOp(
                parent=self.dialog,
                op=lambda _collection: dictionary_service().import_archives(
                    [Path(filename) for filename in filenames],
                    should_cancel=lambda: bool(mw and mw.progress.want_cancel()),
                ),
                success=self._imports_finished,
            )
            .without_collection()
            .with_progress(f"Importing {len(filenames)} dictionaries...")
            .failure(lambda error: self._operation_failed(error, showWarning))
            .run_in_background()
        )

    def _imports_finished(self, result: BatchImportResult) -> None:
        from aqt.utils import showWarning, tooltip

        self._set_busy(False)
        selected_id = result.imported[-1].dictionary.id if result.imported else None
        self.refresh(selected_id)

        imported_count = len(result.imported)
        total_terms = sum(item.dictionary.term_count for item in result.imported)
        total_kanji = sum(item.dictionary.kanji_count for item in result.imported)
        total_metadata = sum(item.dictionary.metadata_count for item in result.imported)
        summary = (
            f"Imported {imported_count} "
            f"{'dictionary' if imported_count == 1 else 'dictionaries'}: "
            f"{total_terms:,} terms, {total_kanji:,} kanji, and "
            f"{total_metadata:,} metadata records."
        )
        if result.cancelled:
            summary += " Remaining imports were cancelled."
        if imported_count:
            tooltip(summary, parent=self.dialog)
        if result.failed:
            details = "\n".join(
                f"- {failure.filename}: {failure.message}" for failure in result.failed
            )
            showWarning(
                f"{summary}\n\n{len(result.failed)} import(s) failed:\n{details}",
                parent=self.dialog,
            )
        elif not imported_count:
            showWarning(summary, parent=self.dialog)

    def _remove_selected(self) -> None:
        selected_items = self.list_widget.selectedItems()
        dictionary_ids = self._selected_ids()
        if not dictionary_ids:
            return

        from aqt.operations import QueryOp
        from aqt.utils import askUser, showWarning

        if len(selected_items) == 1:
            prompt = f"Remove {selected_items[0].text()} and its local index?"
        else:
            prompt = f"Remove {len(selected_items)} selected dictionaries and their local indexes?"
        if not askUser(prompt, parent=self.dialog):
            return

        self._set_busy(True)
        (
            QueryOp(
                parent=self.dialog,
                op=lambda _collection: dictionary_service().remove_many(dictionary_ids),
                success=lambda _result: self._remove_succeeded(len(dictionary_ids)),
            )
            .without_collection()
            .with_progress(f"Removing {len(dictionary_ids)} dictionaries...")
            .failure(lambda error: self._operation_failed(error, showWarning))
            .run_in_background()
        )

    def _remove_succeeded(self, removed_count: int) -> None:
        from aqt.utils import tooltip

        self._set_busy(False)
        self.refresh()
        tooltip(
            f"Removed {removed_count} {'dictionary' if removed_count == 1 else 'dictionaries'}.",
            parent=self.dialog,
        )

    def _on_item_changed(self, item: Any) -> None:
        if self._updating:
            return
        Qt = self._qt["Qt"]
        dictionary_id = item.data(Qt.ItemDataRole.UserRole)
        enabled = item.checkState() == Qt.CheckState.Checked
        try:
            dictionary_service().set_enabled(int(dictionary_id), enabled)
        except Exception as error:
            from aqt.utils import showWarning

            showWarning(f"Could not update dictionary: {error}", parent=self.dialog)
            self.refresh(int(dictionary_id))

    def _move_selected(self, offset: int) -> None:
        dictionary_ids = self._selected_ids()
        if len(dictionary_ids) != 1:
            return
        dictionary_id = dictionary_ids[0]
        try:
            dictionary_service().move(dictionary_id, offset)
        except Exception as error:
            from aqt.utils import showWarning

            showWarning(f"Could not reorder dictionary: {error}", parent=self.dialog)
            return
        self.refresh(dictionary_id)

    def _selected_ids(self) -> list[int]:
        Qt = self._qt["Qt"]
        return [
            int(item.data(Qt.ItemDataRole.UserRole)) for item in self.list_widget.selectedItems()
        ]

    def _update_buttons(self) -> None:
        row = self.list_widget.currentRow()
        count = self.list_widget.count()
        selection_count = len(self.list_widget.selectedItems())
        self.remove_button.setEnabled(selection_count > 0)
        self.up_button.setEnabled(selection_count == 1 and row > 0)
        self.down_button.setEnabled(selection_count == 1 and row < count - 1)

    def _set_busy(self, busy: bool) -> None:
        self.import_button.setEnabled(not busy)
        if busy:
            self.remove_button.setEnabled(False)
            self.up_button.setEnabled(False)
            self.down_button.setEnabled(False)
        else:
            self._update_buttons()

    def _operation_failed(self, error: Exception, show_warning: Any) -> None:
        self._set_busy(False)
        show_warning(str(error), parent=self.dialog)


def show_dictionary_manager(parent: Any) -> None:
    DictionaryManager(parent).show()


def _dictionary_label(dictionary: DictionaryInfo) -> str:
    parts = []
    if dictionary.term_count:
        parts.append(f"{dictionary.term_count:,} terms")
    if dictionary.kanji_count:
        parts.append(f"{dictionary.kanji_count:,} kanji")
    if dictionary.metadata_count:
        parts.append(f"{dictionary.metadata_count:,} metadata")
    count_label = ", ".join(parts) or "no searchable entries"
    return f"{dictionary.title} - {count_label}"
