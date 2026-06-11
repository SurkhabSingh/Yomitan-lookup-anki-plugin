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
    from aqt.qt import QApplication, QMainWindow, QMenu

    application = QApplication.instance() or QApplication([])
    module = importlib.import_module(arguments.package)
    bootstrap = importlib.import_module(f"{arguments.package}.bootstrap")
    callback = bootstrap._on_main_window_did_init
    if callback not in gui_hooks.main_window_did_init._hooks:
        raise RuntimeError("Anki Lookup did not register its main-window hook")

    main_window = QMainWindow()
    main_window.form = SimpleNamespace(menuTools=QMenu(main_window))
    aqt.mw = main_window
    callback()
    action_names = [action.text() for action in main_window.form.menuTools.actions()]

    expected_action = "Anki Lookup: About"
    if expected_action not in action_names:
        raise RuntimeError(f"Expected Tools action was not installed: {action_names}")

    print(
        json.dumps(
            {
                "anki_version": importlib.metadata.version("anki"),
                "addon_module": module.__name__,
                "hook_registered": True,
                "action_visible": True,
                "action_name": expected_action,
            }
        )
    )
    application.quit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
