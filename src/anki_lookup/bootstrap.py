"""Add-on bootstrap using supported Anki hooks."""

import logging
from typing import Any, Optional

from .metadata import ADDON_NAME, VERSION

logger = logging.getLogger(__name__)

_initialized = False

#: Strong references to the Qt objects we hand to the Tools menu. Without these the
#: wrappers are garbage-collected and the entries go dead. ``_menu`` doubles as the
#: idempotency guard.
_menu: Optional[Any] = None
_actions: list[Any] = []


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
    """Install web assets, the Tools submenu, and the local servers."""

    global _menu

    if _menu is not None:
        return

    from aqt import mw

    if mw is None:
        return

    from .api_server import start_api_server

    start_api_server()
    _start_translation_bridge()
    mw.addonManager.setWebExports(__name__, r"web/.*\.(css|js)")
    _install_menu(mw)
    _install_config_action(mw)


def _install_menu(mw: Any) -> None:
    """Add one submenu to Tools rather than five siblings.

    Five top-level entries is a lot of someone else's menu to take for one add-on,
    and the ``Anki Lookup: `` prefix each one carried existed only to disambiguate
    them there. Inside a submenu the names stand on their own.
    """

    global _menu

    from aqt.qt import QAction, QMenu
    from aqt.utils import showInfo

    from .ui.diagnostics import show_diagnostics
    from .ui.dictionary_manager import show_dictionary_manager
    from .ui.note_preset_editor import show_note_preset_editor
    from .ui.settings_dialog import show_settings_dialog

    menu = QMenu(ADDON_NAME, mw)

    entries: tuple[tuple[str, Any], ...] = (
        ("Manage Dictionaries...", lambda: show_dictionary_manager(mw)),
        ("Note Preset...", lambda: show_note_preset_editor(mw)),
        ("Settings...", lambda: show_settings_dialog(mw)),
        ("Diagnostics...", lambda: show_diagnostics(mw)),
        ("About", lambda: showInfo(_about_text())),
    )

    for label, handler in entries:
        action = QAction(label, mw)
        action.triggered.connect(handler)
        menu.addAction(action)
        _actions.append(action)

    mw.form.menuTools.addMenu(menu)
    _menu = menu


def _install_config_action(mw: Any) -> None:
    """Point Anki's own Config button at the settings dialog.

    Tools > Add-ons > Anki Lookup > Config is where users expect an add-on's settings
    to live. Without this Anki falls back to a raw JSON editor over ``config.json``,
    which is exactly what the settings dialog exists to avoid.
    """

    try:
        from .ui.settings_dialog import show_settings_dialog

        mw.addonManager.setConfigAction(__name__, lambda: show_settings_dialog(mw))
    except Exception:
        logger.exception("Could not register the %s config action", ADDON_NAME)


def _about_text() -> str:
    return (
        f"{ADDON_NAME} {VERSION}\n\n"
        "Hold Shift and move the pointer across text while reviewing a card to look "
        "up the word under it.\n\n"
        "Ctrl+Shift+L looks up the current selection. Ctrl+Shift+K pins a popup."
    )


def _start_translation_bridge() -> None:
    """Follow the configured bridge setting, without ever raising.

    Anything escaping here would abort ``_on_main_window_did_init`` and take every
    Tools menu action below it with it — the add-on would look completely broken
    because a port was busy. ``start_api_server`` is equally unraisable for the same
    reason.
    """

    try:
        from aqt import mw

        from .config import runtime_config
        from .runtime import bridge_controller

        if mw is None:
            return

        package = mw.addonManager.addonFromModule(__name__)
        config = runtime_config(mw.addonManager.getConfig(package))
        bridge_controller().apply_enabled(config["translation"]["bridge_enabled"])
    except Exception:
        logger.exception("Could not start the %s translation bridge", ADDON_NAME)
