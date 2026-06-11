"""Add-on bootstrap using supported Anki hooks."""

from typing import Any, Optional

from .metadata import ADDON_NAME, VERSION

_initialized = False
_about_action: Optional[Any] = None


def initialize() -> bool:
    """Register add-on hooks when imported by Anki.

    Returning ``False`` outside Anki keeps metadata and packaging tests independent
    from Anki's bundled Python environment.
    """

    global _initialized

    if _initialized:
        return True

    try:
        from aqt import gui_hooks
    except ImportError:
        return False

    gui_hooks.main_window_did_init.append(_on_main_window_did_init)
    _initialized = True
    return True


def _on_main_window_did_init() -> None:
    """Install the Phase 0 smoke-test menu action."""

    global _about_action

    if _about_action is not None:
        return

    from aqt import mw
    from aqt.qt import QAction
    from aqt.utils import showInfo

    if mw is None:
        return

    action = QAction(f"{ADDON_NAME}: About", mw)
    action.triggered.connect(
        lambda: showInfo(
            f"{ADDON_NAME} {VERSION}\n\n"
            "Phase 0 runtime and packaging harness is installed successfully."
        )
    )
    mw.form.menuTools.addAction(action)
    _about_action = action
