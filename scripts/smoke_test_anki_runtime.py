"""Exercise the installed add-on with Anki's bundled Python and Qt runtime."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import sys
from pathlib import Path
from types import SimpleNamespace


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--addons-directory", type=Path, required=True)
    parser.add_argument("--package", required=True)
    arguments = parser.parse_args()

    sys.path.insert(0, str(arguments.addons_directory.resolve()))

    import aqt
    from aqt import gui_hooks
    from aqt.qt import QAbstractItemView, QApplication, QMainWindow, QMenu
    from aqt.reviewer import Reviewer
    from aqt.webview import WebContent

    application = QApplication.instance() or QApplication([])
    module = importlib.import_module(arguments.package)
    bootstrap = importlib.import_module(f"{arguments.package}.bootstrap")
    callback = bootstrap._on_main_window_did_init
    if callback not in gui_hooks.main_window_did_init._hooks:
        raise RuntimeError("Anki Lookup did not register its main-window hook")

    class FakeAddonManager:
        def __init__(self) -> None:
            self.web_exports: tuple[str, str] | None = None
            self.config_action_registered = False

        def setWebExports(self, module_name: str, pattern: str) -> None:
            self.web_exports = (module_name, pattern)

        def setConfigAction(self, module_name: str, fn: object) -> None:
            self.config_action_registered = True

        def addonFromModule(self, module_name: str) -> str:
            return arguments.package

        def getConfig(self, module_name: str) -> dict[str, object]:
            return {
                "lookup": {
                    "modifier": "Shift",
                    "release_behavior": "remain_open",
                }
            }

        def writeConfig(self, module_name: str, config: dict[str, object]) -> None:
            self.saved_config = (module_name, config)

        def addonsFolder(self, module_name: str) -> str:
            return str(arguments.addons_directory / arguments.package)

    main_window = QMainWindow()
    main_window.form = SimpleNamespace(menuTools=QMenu(main_window))
    main_window.addonManager = FakeAddonManager()
    aqt.mw = main_window
    callback()

    # One submenu, not five siblings: Tools belongs to Anki, not to us.
    top_level = main_window.form.menuTools.actions()
    submenus = [action.menu() for action in top_level if action.menu() is not None]
    if len(top_level) != 1 or not submenus:
        raise RuntimeError(
            f"Expected exactly one Tools submenu, found: {[a.text() for a in top_level]}"
        )

    menu = submenus[0]
    if menu.title() != "Anki Lookup":
        raise RuntimeError(f"Submenu is misnamed: {menu.title()}")

    action_names = [action.text() for action in menu.actions()]
    for expected in (
        "Manage Dictionaries...",
        "Note Preset...",
        "Settings...",
        "Diagnostics...",
        "About",
    ):
        if expected not in action_names:
            raise RuntimeError(f"Submenu entry missing: {expected} (have {action_names})")

    # Anki's own Config button must reach the settings dialog rather than falling back
    # to a raw JSON editor over config.json.
    if not main_window.addonManager.config_action_registered:
        raise RuntimeError("setConfigAction was not registered")

    # The bridge is off by default, so reaching this point proves the Tools actions
    # above survived _start_translation_bridge() rather than being aborted by it.
    diagnostics_module = importlib.import_module(f"{arguments.package}.ui.diagnostics")
    report = diagnostics_module.diagnostics_report()
    if "Translation bridge" not in report:
        raise RuntimeError(f"Diagnostics did not report bridge status: {report}")

    dictionary_manager_module = importlib.import_module(
        f"{arguments.package}.ui.dictionary_manager"
    )
    manager = dictionary_manager_module.DictionaryManager(main_window)
    if manager.dialog.windowTitle() != "Anki Lookup Dictionaries":
        raise RuntimeError("Dictionary manager dialog did not initialize correctly")
    if manager.list_widget.selectionMode() != QAbstractItemView.SelectionMode.ExtendedSelection:
        raise RuntimeError("Dictionary manager does not support multi-selection")
    if manager.import_button.text() != "Import Dictionaries...":
        raise RuntimeError("Dictionary manager does not expose batch import")
    if manager.remove_button.text() != "Remove Selected":
        raise RuntimeError("Dictionary manager does not expose batch removal")
    manager.dialog.close()

    settings_module = importlib.import_module(f"{arguments.package}.ui.settings_dialog")
    settings = settings_module.SettingsDialog(main_window)
    if settings.dialog.windowTitle() != "Anki Lookup Settings":
        raise RuntimeError("Settings dialog did not initialize correctly")
    if settings.theme.count() < 4:
        raise RuntimeError("Settings dialog does not expose multiple themes")
    if settings.dictionary_layout.count() != 2:
        raise RuntimeError("Settings dialog does not expose both dictionary layouts")
    if settings.frequency_sort_source.count() < 1:
        raise RuntimeError("Settings dialog does not expose frequency source selection")
    if settings.frequency_sort_order.count() != 3:
        raise RuntimeError("Settings dialog does not expose frequency sort direction")
    if settings.font_size.minimum() != 10 or settings.font_size.maximum() != 32:
        raise RuntimeError("Settings dialog has invalid font size bounds")
    if settings.pin_shortcut.text() != "Ctrl+Shift+K":
        raise RuntimeError("Settings dialog does not expose the pin shortcut")
    settings.dialog.close()

    reviewer = object.__new__(Reviewer)
    web_content = WebContent()
    hooks = importlib.import_module(f"{arguments.package}.hooks")
    hooks.on_webview_will_set_content(web_content, reviewer)
    if '"debounce_ms": 20' not in web_content.head:
        raise RuntimeError("Reviewer did not receive the smooth scanning configuration")
    if '"allow_nested_popups": true' not in web_content.head:
        raise RuntimeError("Reviewer did not receive nested popup configuration")
    if '"pin_shortcut": "Ctrl+Shift+K"' not in web_content.head:
        raise RuntimeError("Reviewer did not receive the popup pin shortcut")
    if not any(path.endswith("/web/popup.js") for path in web_content.js):
        raise RuntimeError(f"Popup JavaScript was not injected: {web_content.js}")
    if not any(path.endswith("/web/popup.css") for path in web_content.css):
        raise RuntimeError(f"Popup CSS was not injected: {web_content.css}")
    popup_script = (arguments.addons_directory / arguments.package / "web" / "popup.js").read_text(
        encoding="utf-8"
    )
    if 'data-popup-action="pin"' not in popup_script:
        raise RuntimeError("Popup does not expose the compact pin control")
    if 'data-popup-action="close"' not in popup_script:
        raise RuntimeError("Popup does not expose the compact close control")
    if "createLexicalMetadata" not in popup_script:
        raise RuntimeError("Popup does not expose frequency and pronunciation metadata")
    popup_styles = (arguments.addons_directory / arguments.package / "web" / "popup.css").read_text(
        encoding="utf-8"
    )
    header_style = popup_styles.split(".anki-lookup-popup .anki-lookup__header {", maxsplit=1)[
        1
    ].split("}", maxsplit=1)[0]
    if "justify-content: flex-start;" not in header_style or "direction: ltr;" not in header_style:
        raise RuntimeError("Popup header controls are not anchored to the physical left")

    bridge_message = 'anki_lookup:{"action":"lookup","request_id":1,"term":"runtime"}'
    handled, result = hooks.on_webview_did_receive_js_message(
        (False, None), bridge_message, reviewer
    )
    if (
        not handled
        or result.get("term") != "runtime"
        or result.get("status") not in {"ready", "empty"}
    ):
        raise RuntimeError(f"Lookup bridge did not return a result: {result}")

    print(
        json.dumps(
            {
                "anki_version": importlib.metadata.version("anki"),
                "addon_module": module.__name__,
                "hook_registered": True,
                "tools_submenu": menu.title(),
                "submenu_entries": action_names,
                "config_action_registered": True,
                "dictionary_manager_action_visible": True,
                "dictionary_manager_constructed": True,
                "dictionary_multi_selection": True,
                "dictionary_batch_actions": True,
                "settings_action_visible": True,
                "settings_dialog_constructed": True,
                "appearance_controls": True,
                "dictionary_layout_controls": True,
                "frequency_sort_controls": True,
                "pin_shortcut_config": True,
                "smooth_scan_config": True,
                "nested_popup_config": True,
                "reviewer_assets_injected": True,
                "popup_header_controls": True,
                "popup_controls_left_aligned": True,
                "lexical_metadata_rendering": True,
                "lookup_bridge_handled": True,
            }
        )
    )
    application.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
