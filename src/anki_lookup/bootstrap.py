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

    from .hooks import register_hooks

    gui_hooks.main_window_did_init.append(_on_main_window_did_init)
    register_hooks(gui_hooks)
    _initialized = True
    return True


def _on_main_window_did_init() -> None:
    """Install web assets and the add-on information action."""

    global _about_action

    if _about_action is not None:
        return

    from aqt import mw
    from aqt.qt import QAction
    from aqt.utils import showInfo

    if mw is None:
        return

    mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")

    action = QAction(f"{ADDON_NAME}: About", mw)
    action.triggered.connect(
        lambda: showInfo(
            f"{ADDON_NAME} {VERSION}\n\n"
            "Hold Shift and move across text while reviewing a card to open "
            "the Phase 1 lookup popup."
        )
    )
    mw.form.menuTools.addAction(action)
    _about_action = action
