"""Runtime service location and lifecycle."""

from __future__ import annotations

from pathlib import Path

from .dictionary import DictionaryService
from .translation.controller import BridgeController

_dictionary_service: DictionaryService | None = None
_bridge_controller: BridgeController | None = None


def dictionary_service() -> DictionaryService:
    global _dictionary_service
    if _dictionary_service is None:
        _dictionary_service = DictionaryService(_database_path())
    return _dictionary_service


def bridge_controller() -> BridgeController:
    global _bridge_controller
    if _bridge_controller is None:
        _bridge_controller = BridgeController(_translation_cache_path())
    return _bridge_controller


def _database_path() -> Path:
    return _user_files_directory() / "dictionaries.sqlite3"


def _translation_cache_path() -> Path:
    # A separate database from the dictionaries, so a cache problem can never put
    # imported dictionaries at risk and clearing the cache is a file delete.
    return _user_files_directory() / "translations.sqlite3"


def _user_files_directory() -> Path:
    from aqt import mw

    if mw is None:
        raise RuntimeError("Anki main window is not available")
    package = mw.addonManager.addonFromModule(__name__)
    addon_directory = Path(mw.addonManager.addonsFolder(package))
    return addon_directory / "user_files"
