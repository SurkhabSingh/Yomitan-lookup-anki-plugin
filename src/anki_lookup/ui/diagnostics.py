"""Diagnostics: what is connected, what is not, and what to do about it."""

from __future__ import annotations

from typing import Any

from ..metadata import ADDON_NAME, VERSION
from ..translation.bridge_server import BOUND, DISABLED, FOREIGN_BRIDGE, PORT_CONFLICT

#: Keyed by bridge mode. Every one of these names a fix, because each mode has a
#: different one — that is the whole reason they are separate modes rather than a
#: single "translation unavailable".
_MODE_ADVICE = {
    DISABLED: (
        "Off",
        "Turn on 'Translate inside Anki using the browser extension' in "
        "Anki Lookup: Settings. Translation tabs currently open the provider's "
        "website instead.",
    ),
    BOUND: (
        "Listening",
        "Waiting for the Wonder of U browser extension to connect. Open the "
        "extension and put it in App Support mode.",
    ),
    FOREIGN_BRIDGE: (
        "Another bridge has the port",
        "The Wonder of U desktop app is using this port for translation, and only "
        "one program can. Quit it if you want to translate in Anki instead; the "
        "bridge picks the port up on its own within a minute.",
    ),
    PORT_CONFLICT: (
        "Port unavailable",
        "Another program is using the port and it is not a translation bridge. "
        "The browser extension cannot be pointed at a different port, so "
        "translation in Anki is unavailable until that program releases it.",
    ),
}


def diagnostics_report() -> str:
    """Build the report text. Pure enough to eyeball; Qt lives in the caller."""

    from ..runtime import bridge_controller, dictionary_service

    lines = [f"{ADDON_NAME} {VERSION}", ""]

    try:
        dictionaries = dictionary_service().list_dictionaries()
        enabled = sum(1 for dictionary in dictionaries if dictionary.enabled)
        lines.append(f"Dictionaries: {len(dictionaries)} imported, {enabled} enabled")
    except Exception as error:
        lines.append(f"Dictionaries: unavailable ({error})")

    lines.append("")

    try:
        status = bridge_controller().status()
        headline, advice = _MODE_ADVICE.get(status.mode, ("Unknown", ""))

        lines.append(f"Translation bridge: {headline}")
        lines.append(f"  Port: 127.0.0.1:{status.port}")

        if status.mode == BOUND:
            connected = "yes" if status.extension_connected else "no"
            lines.append(f"  Browser extension connected: {connected}")
        if status.peer_name:
            peer = f"{status.peer_name} {status.peer_version}".strip()
            lines.append(f"  Port held by: {peer}")
        if status.last_error:
            lines.append(f"  Last error: {status.last_error}")
        if advice and not (status.mode == BOUND and status.extension_connected):
            lines.extend(["", advice])
    except Exception as error:
        lines.append(f"Translation bridge: unavailable ({error})")

    return "\n".join(lines)


def show_diagnostics(parent: Any) -> None:
    from aqt.qt import (
        QDialog,
        QDialogButtonBox,
        QPlainTextEdit,
        QVBoxLayout,
    )

    dialog = QDialog(parent)
    dialog.setWindowTitle(f"{ADDON_NAME} Diagnostics")
    dialog.resize(520, 320)
    layout = QVBoxLayout(dialog)

    report = QPlainTextEdit(diagnostics_report())
    report.setReadOnly(True)
    layout.addWidget(report)

    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
    buttons.rejected.connect(dialog.reject)
    buttons.accepted.connect(dialog.accept)
    layout.addWidget(buttons)

    dialog.exec()
