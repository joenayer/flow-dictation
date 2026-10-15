"""Offscreen QApplication smoke tests for pill and tray."""

from __future__ import annotations

import importlib.util
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 not installed",
)
pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from flow.events import SessionState  # noqa: E402
from flow.config import Settings  # noqa: E402
from flow.ui.pill import PillController, QtPill  # noqa: E402
from flow.ui.settings import SettingsDialog, validate_shortcut  # noqa: E402
from flow.ui.tray import TrayIcon  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["flow-linux-ui-smoke"])
    return app


def test_pill_set_state_all_states(qapp: QApplication) -> None:
    pill = QtPill()
    assert isinstance(pill, PillController)
    for state in SessionState:
        pill.set_state(state)
    pill.show_message("hello from test")


def test_tray_construct(qapp: QApplication) -> None:
    calls: list[str] = []
    tray = TrayIcon(
        on_settings=lambda: calls.append("settings"),
        on_quit=lambda: calls.append("quit"),
    )
    assert tray.icon is not None
    assert tray.icon.contextMenu() is not None


def test_settings_dialog_construct(qapp: QApplication) -> None:
    snapshot = ["hello", "world"]
    refreshed = {"n": 0}

    def refresh() -> list[str]:
        refreshed["n"] += 1
        return ["refreshed"]

    dlg = SettingsDialog(
        Settings(),
        history=snapshot,
        on_refresh_history=refresh,
    )
    assert dlg._history_list.count() == 2
    dlg._refresh_history()
    assert refreshed["n"] == 1
    assert dlg._history_list.count() == 1
    ok, _reason = validate_shortcut("Ctrl+Super+d")
    assert ok is True
