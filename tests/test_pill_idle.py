"""Idle means no bubble: pill hides on IDLE, shows otherwise."""

import pytest

pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtWidgets import QApplication  # noqa: E402

from flow.events import SessionState  # noqa: E402
from flow.ui.pill import QtPill  # noqa: E402


@pytest.fixture()
def pill(qapp=None):
    _app = QApplication.instance() or QApplication([])
    widget = QtPill()
    widget.show()
    yield widget
    widget.close()


def test_idle_hides_pill(pill):
    pill.set_state(SessionState.IDLE)
    assert pill.isHidden()


def test_recording_shows_pill(pill):
    pill.set_state(SessionState.IDLE)
    pill.set_state(SessionState.RECORDING)
    assert pill.isVisible()


def test_message_shows_pill(pill):
    pill.set_state(SessionState.IDLE)
    pill.show_message("hello")
    assert pill.isVisible()
