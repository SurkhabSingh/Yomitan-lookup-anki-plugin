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

        def setWebExports(self, module_name: str, pattern: str) -> None:
            self.web_exports = (module_name, pattern)

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
    action_names = [action.text() for action in main_window.form.menuTools.actions()]

    expected_action = "Anki Lookup: About"
    if expected_action not in action_names:
        raise RuntimeError(f"Expected Tools action was not installed: {action_names}")
    dictionary_action = "Anki Lookup: Manage Dictionaries..."
    if dictionary_action not in action_names:
        raise RuntimeError(f"Dictionary manager action was not installed: {action_names}")
    settings_action = "Anki Lookup: Settings..."
    if settings_action not in action_names:
        raise RuntimeError(f"Settings action was not installed: {action_names}")

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
                "action_visible": True,
                "action_name": expected_action,
                "dictionary_manager_action_visible": True,
                "dictionary_manager_constructed": True,
                "dictionary_multi_selection": True,
                "dictionary_batch_actions": True,
                "settings_action_visible": True,
                "settings_dialog_constructed": True,
                "appearance_controls": True,
                "dictionary_layout_controls": True,
                "pin_shortcut_config": True,
                "smooth_scan_config": True,
                "nested_popup_config": True,
                "reviewer_assets_injected": True,
                "lookup_bridge_handled": True,
            }
        )
    )
    application.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
