"""Native appearance and interaction settings dialog."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..config import DEFAULT_CONFIG, runtime_config, validated_shortcut
from ..runtime import dictionary_service
from ..translation.languages import target_languages_for
from ..translation.models import ALLOWED_PROVIDERS, provider_label

THEMES = (
    ("Follow Anki / system", "system"),
    ("Light", "light"),
    ("Dark", "dark"),
    ("High contrast", "high_contrast"),
)
TRANSLATION_PROVIDERS = tuple(
    (provider_label(provider), provider) for provider in ALLOWED_PROVIDERS
)
DICTIONARY_LAYOUTS = (
    ("Dictionary buttons in Sources", "source_rail"),
    ("Continuous dictionary results", "continuous"),
)
FREQUENCY_SORT_ORDERS = (
    ("Automatic from dictionary metadata", "auto"),
    ("Lower numbers first", "ascending"),
    ("Higher numbers first", "descending"),
)


class SettingsDialog:
    """Let users configure common popup options without editing JSON."""

    def __init__(self, parent: Any) -> None:
        from aqt import mw
        from aqt.qt import (
            QCheckBox,
            QComboBox,
            QDialog,
            QDialogButtonBox,
            QFont,
            QFontComboBox,
            QFormLayout,
            QGroupBox,
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
        self.dialog.resize(560, 400)
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

        self.frequency_sort_source = QComboBox()
        self.frequency_sort_source.addItem("No frequency ordering", 0)
        for source in dictionary_service().list_frequency_sources():
            label = f"{source.title} ({source.revision})"
            if source.frequency_mode:
                label += f" - {source.frequency_mode}"
            if not source.enabled:
                label += " - disabled"
            self.frequency_sort_source.addItem(label, source.id)
        frequency_source_index = self.frequency_sort_source.findData(
            config["lookup"]["frequency_sort_dictionary_id"]
        )
        self.frequency_sort_source.setCurrentIndex(max(0, frequency_source_index))
        self.frequency_sort_source.setToolTip(
            "Choose one imported frequency dictionary to order otherwise-equivalent lookup results."
        )
        form.addRow("Frequency ordering", self.frequency_sort_source)

        self.frequency_sort_order = QComboBox()
        for label, value in FREQUENCY_SORT_ORDERS:
            self.frequency_sort_order.addItem(label, value)
        frequency_order_index = self.frequency_sort_order.findData(
            config["lookup"]["frequency_sort_order"]
        )
        self.frequency_sort_order.setCurrentIndex(max(0, frequency_order_index))
        self.frequency_sort_order.setToolTip(
            "Automatic puts lower rank values first and higher occurrence values first. "
            "Sources without a declared mode use lower numbers first."
        )
        form.addRow("Frequency order", self.frequency_sort_order)

        self.pin_shortcut = QLineEdit(config["lookup"]["pin_shortcut"])
        self.pin_shortcut.setPlaceholderText("Ctrl+Shift+K")
        self.pin_shortcut.setToolTip(
            "Use modifiers plus one letter or number, for example Ctrl+Shift+K."
        )
        form.addRow("Pin / unpin shortcut", self.pin_shortcut)
        layout.addLayout(form)
        self.frequency_sort_source.currentIndexChanged.connect(self._update_frequency_order_state)
        self._update_frequency_order_state()

        note = QLabel(
            "Pinned popups stay open, are not replaced by later scans, and can be dragged "
            "by their header."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        translation_group = QGroupBox("Translation")
        translation_form = QFormLayout(translation_group)

        self.translation_provider = QComboBox()
        for label, value in TRANSLATION_PROVIDERS:
            self.translation_provider.addItem(label, value)
        provider_index = self.translation_provider.findData(config["translation"]["provider"])
        self.translation_provider.setCurrentIndex(max(0, provider_index))
        translation_form.addRow("Provider", self.translation_provider)

        self.translation_target = QComboBox()
        self._populate_target_languages(
            config["translation"]["provider"],
            config["translation"]["target_language"],
        )
        translation_form.addRow("Translate into", self.translation_target)

        self.translation_warning = QLabel()
        self.translation_warning.setWordWrap(True)
        self.translation_warning.hide()
        translation_form.addRow("", self.translation_warning)

        self.translation_cache_ttl = QSpinBox()
        self.translation_cache_ttl.setRange(0, 8_760)
        self.translation_cache_ttl.setSuffix(" hours")
        self.translation_cache_ttl.setSpecialValueText("Do not cache")
        self.translation_cache_ttl.setValue(config["translation"]["cache_ttl_hours"])
        self.translation_cache_ttl.setToolTip(
            "How long a translation is reused before it is requested again. Set to zero "
            "to turn caching off."
        )
        translation_form.addRow("Cache translations for", self.translation_cache_ttl)

        self.bridge_enabled = QCheckBox("Translate inside Anki using the browser extension")
        self.bridge_enabled.setChecked(config["translation"]["bridge_enabled"])
        self.bridge_enabled.setToolTip(
            "Requires the Wonder of U browser extension in App Support mode.\n"
            "Anki and the Wonder of U desktop app cannot both do this at once: they "
            "share one port, and whichever starts first gets it."
        )
        translation_form.addRow("", self.bridge_enabled)

        bridge_note = QLabel(
            "Leave this off unless you want to translate in Anki. It binds the same port "
            "the Wonder of U desktop app uses, and only one of the two can hold it. "
            "With it off, translation tabs open the provider's website instead."
        )
        bridge_note.setWordWrap(True)
        translation_form.addRow("", bridge_note)

        self.bridge_status = QLabel(self._bridge_status_text())
        self.bridge_status.setWordWrap(True)
        translation_form.addRow("Status", self.bridge_status)

        layout.addWidget(translation_group)
        self.translation_provider.currentIndexChanged.connect(self._on_provider_changed)

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
        translation = candidate.setdefault("translation", {})
        lookup["pin_shortcut"] = normalized_shortcut
        lookup["frequency_sort_dictionary_id"] = int(self.frequency_sort_source.currentData())
        lookup["frequency_sort_order"] = self.frequency_sort_order.currentData()
        appearance["theme"] = self.theme.currentData()
        appearance["font_family"] = self.font_family.currentFont().family()
        appearance["font_size_px"] = self.font_size.value()
        appearance["dictionary_layout"] = self.dictionary_layout.currentData()
        translation["provider"] = self.translation_provider.currentData()
        translation["target_language"] = self.translation_target.currentData()
        translation["cache_ttl_hours"] = self.translation_cache_ttl.value()
        translation["bridge_enabled"] = self.bridge_enabled.isChecked()

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
        self._apply_bridge_setting(validated)
        self._apply_to_reviewer(validated)
        self.dialog.accept()
        tooltip("Anki Lookup settings saved.", parent=self.dialog)

    def _apply_bridge_setting(self, config: dict[str, Any]) -> None:
        """Start or stop the bridge to match the saved setting.

        Failing here must not lose the user's other settings: they are already
        written, and a busy port is not a reason to refuse a font change.
        """

        from aqt.utils import showWarning

        from ..runtime import bridge_controller

        try:
            controller = bridge_controller()
            controller.apply_enabled(config["translation"]["bridge_enabled"])
        except Exception:
            showWarning(
                "Anki Lookup could not start the translation bridge. Your other "
                "settings were saved. See Tools > Anki Lookup: Diagnostics.",
                parent=self.dialog,
            )
            return

        if not config["translation"]["bridge_enabled"]:
            return

        reason = controller.unavailable_reason()
        if reason:
            showWarning(
                f"Translation in Anki is not available yet. {reason}\n\n"
                "Translation tabs will open the provider's website until it is.",
                parent=self.dialog,
            )

    def _apply_to_reviewer(self, config: dict[str, Any]) -> None:
        import json

        from aqt import mw

        from ..hooks import apply_runtime_config

        apply_runtime_config(config)
        reviewer = getattr(mw, "reviewer", None) if mw is not None else None
        web = getattr(reviewer, "web", None)
        if web is None:
            return
        payload = json.dumps(config, ensure_ascii=False).replace("</", "<\\/")
        web.eval(f"window.AnkiLookupApplyConfig && window.AnkiLookupApplyConfig({payload});")

    def _update_frequency_order_state(self) -> None:
        self.frequency_sort_order.setEnabled(bool(self.frequency_sort_source.currentData()))

    def _bridge_status_text(self) -> str:
        from ..runtime import bridge_controller

        try:
            reason = bridge_controller().unavailable_reason()
        except Exception:
            return "Unavailable. See Tools > Anki Lookup: Diagnostics."
        return reason or "Connected to the browser extension."

    def _populate_target_languages(self, provider: str, selected: str) -> None:
        self.translation_target.clear()
        for code, label in target_languages_for(provider):
            self.translation_target.addItem(label, code)
        index = self.translation_target.findData(selected)
        self.translation_target.setCurrentIndex(max(0, index))

    def _on_provider_changed(self) -> None:
        """Re-check the target language against the newly chosen provider.

        The two providers' target lists are not supersets of one another, so a code
        that was valid a moment ago may not be now. Reset it and say so, rather than
        silently swapping the user's language or leaving a code that would fail later
        at translate time with a confusing bridge error.
        """

        provider = self.translation_provider.currentData()
        previous_code = self.translation_target.currentData()
        previous_label = self.translation_target.currentText()

        supported = {code for code, _ in target_languages_for(provider)}
        if previous_code in supported:
            self._populate_target_languages(provider, previous_code)
            self.translation_warning.hide()
            return

        self._populate_target_languages(provider, DEFAULT_CONFIG["translation"]["target_language"])
        self.translation_warning.setText(
            f"{provider_label(provider)} cannot translate into {previous_label}. "
            f"Target language switched to {self.translation_target.currentText()}."
        )
        self.translation_warning.show()


def show_settings_dialog(parent: Any) -> None:
    SettingsDialog(parent).show()
