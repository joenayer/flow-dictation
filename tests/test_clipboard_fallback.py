"""Qt clipboard copy used when typing into the focused app fails."""

import pytest

pytest.importorskip("PySide6.QtGui")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from flow.flowd import qt_copy_to_clipboard  # noqa: E402


def test_qt_copy_roundtrip():
    QApplication.instance() or QApplication([])
    assert qt_copy_to_clipboard("hello flow") is True
    assert QGuiApplication.clipboard().text() == "hello flow"
