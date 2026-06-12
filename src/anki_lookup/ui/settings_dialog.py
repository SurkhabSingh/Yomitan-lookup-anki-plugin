"""Native appearance and interaction settings dialog."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..config import DEFAULT_CONFIG, runtime_config, validated_shortcut

THEMES = (
    ("Follow Anki / system", "system"),
    ("Light", "light"),
    ("Dark", "dark"),
    ("High contrast", "high_contrast"),
)
DICTIONARY_LAYOUTS = (
    ("Dictionary buttons in Sources", "source_rail"),
    ("Continuous dictionary results", "continuous"),
)


class SettingsDialog:
    """Let users configure common popup options without editing JSON."""

    def __init__(self, parent: Any) -> None:
        from aqt import mw
        from aqt.qt import (
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFont,
            QFontComboBox,
            QFormLayout,
            QLabel,
            QLineEdit,
            QSpinBox,
            QVBoxLayout,
        )

        if mw is None:
            raise RuntimeError("Anki main window is unavailable")

        self._addon_manager = mw.addonManager
        self._package = self._addon_manager.addonFromModule(__name__)
        raw_config = self._addon_manager.getConfig(self._package)
        self._raw_config = deepcopy(raw_config) if isinstance(raw_config, dict) else {}
        config = runtime_config(raw_config)

        self.dialog = QDialog(parent)
        self.dialog.setWindowTitle("Anki Lookup Settings")
        self.dialog.resize(520, 320)
        layout = QVBoxLayout(self.dialog)

        description = QLabel(
            "Appearance changes are applied immediately to the current reviewer. "
            "Refresh the reviewer if a card webview is not currently active."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        form = QFormLayout()
        self.theme = QComboBox()
        for label, value in THEMES:
            self.theme.addItem(label, value)
        theme_index = self.theme.findData(config["appearance"]["theme"])
        self.theme.setCurrentIndex(max(0, theme_index))
        form.addRow("Theme", self.theme)

        self.font_family = QFontComboBox()
        configured_family = config["appearance"]["font_family"]
        if configured_family:
            self.font_family.setCurrentFont(QFont(configured_family))
        form.addRow("Popup font", self.font_family)

        self.font_size = QSpinBox()
        self.font_size.setRange(10, 32)
        self.font_size.setSuffix(" px")
        self.font_size.setValue(config["appearance"]["font_size_px"])
        form.addRow("Font size", self.font_size)

        self.dictionary_layout = QComboBox()
        for label, value in DICTIONARY_LAYOUTS:
            self.dictionary_layout.addItem(label, value)
        layout_index = self.dictionary_layout.findData(config["appearance"]["dictionary_layout"])
        self.dictionary_layout.setCurrentIndex(max(0, layout_index))
        form.addRow("Dictionary layout", self.dictionary_layout)

        self.pin_shortcut = QLineEdit(config["lookup"]["pin_shortcut"])
        self.pin_shortcut.setPlaceholderText("Ctrl+Shift+K")
        self.pin_shortcut.setToolTip(
            "Use modifiers plus one letter or number, for example Ctrl+Shift+K."
        )
        form.addRow("Pin / unpin shortcut", self.pin_shortcut)
        layout.addLayout(form)

        note = QLabel(
            "Pinned popups stay open, are not replaced by later scans, and can be dragged "
            "by their header."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.dialog.reject)
        layout.addWidget(buttons)

    def show(self) -> None:
        self.dialog.exec()

    def _save(self) -> None:
        from aqt.utils import showWarning, tooltip

        raw_shortcut = self.pin_shortcut.text().strip()
        normalized_shortcut = validated_shortcut(raw_shortcut, "")
        if not normalized_shortcut:
            showWarning(
                "Enter a shortcut containing at least one modifier and one letter or "
                "number, for example Ctrl+Shift+K.",
                parent=self.dialog,
            )
            return

        candidate = deepcopy(self._raw_config)
        lookup = candidate.setdefault("lookup", {})
        appearance = candidate.setdefault("appearance", {})
        lookup["pin_shortcut"] = normalized_shortcut
        appearance["theme"] = self.theme.currentData()
        appearance["font_family"] = self.font_family.currentFont().family()
        appearance["font_size_px"] = self.font_size.value()
        appearance["dictionary_layout"] = self.dictionary_layout.currentData()

        validated = runtime_config(candidate)
        if validated["lookup"]["pin_shortcut"] != normalized_shortcut:
            showWarning(
                f"The pin shortcut conflicts with another Anki Lookup shortcut. "
                f"Choose a different shortcut from "
                f"{DEFAULT_CONFIG['lookup']['selection_shortcut']}.",
                parent=self.dialog,
            )
            return

        self._addon_manager.writeConfig(self._package, candidate)
        self._apply_to_reviewer(validated)
        self.dialog.accept()
        tooltip("Anki Lookup settings saved.", parent=self.dialog)

    def _apply_to_reviewer(self, config: dict[str, Any]) -> None:
        import json

        from aqt import mw

        reviewer = getattr(mw, "reviewer", None) if mw is not None else None
        web = getattr(reviewer, "web", None)
        if web is None:
            return
        payload = json.dumps(config, ensure_ascii=False).replace("</", "<\\/")
        web.eval(f"window.AnkiLookupApplyConfig && window.AnkiLookupApplyConfig({payload});")


def show_settings_dialog(parent: Any) -> None:
    SettingsDialog(parent).show()
