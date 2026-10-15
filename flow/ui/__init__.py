"""Pill overlay, tray icon, windows, and settings (unit 3)."""

from __future__ import annotations

from .settings import validate_shortcut

__all__ = [
    "DictatePage",
    "DictionaryDialog",
    "DictionaryWidget",
    "FlowMainWindow",
    "HistoryWindow",
    "PillController",
    "QtPill",
    "ScratchpadWindow",
    "SettingsDialog",
    "SettingsWidget",
    "TrayIcon",
    "validate_shortcut",
]


def __getattr__(name: str):
    if name in ("PillController", "QtPill"):
        from .pill import PillController, QtPill

        return PillController if name == "PillController" else QtPill
    if name == "TrayIcon":
        from .tray import TrayIcon

        return TrayIcon
    if name in ("SettingsDialog", "SettingsWidget"):
        from .settings import SettingsDialog, SettingsWidget

        return SettingsDialog if name == "SettingsDialog" else SettingsWidget
    if name in ("DictionaryDialog", "DictionaryWidget"):
        from .dictionary import DictionaryDialog, DictionaryWidget

        return DictionaryDialog if name == "DictionaryDialog" else DictionaryWidget
    if name == "HistoryWindow":
        from .history_window import HistoryWindow

        return HistoryWindow
    if name == "ScratchpadWindow":
        from .scratchpad import ScratchpadWindow

        return ScratchpadWindow
    if name in ("FlowMainWindow", "DictatePage"):
        from .main_window import DictatePage, FlowMainWindow

        return FlowMainWindow if name == "FlowMainWindow" else DictatePage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
