"""Frameless always-on-top status pill (idle / recording / processing).

Wispr-style: cream pill, ink waveform bars that dance with the mic while
recording, a sweep shimmer while processing. Hidden when idle.
"""

from __future__ import annotations

import abc
import math
import random
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QPainter, QPainterPath
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from ..events import SessionState
from .theme import INK, PAPER, WaveformWidget

#: Transient ``show_message`` text auto-dismisses after this long.
MESSAGE_DISMISS_MS = 4000


class _QtAbcMeta(type(QWidget), abc.ABCMeta):
    """Combine Qt and ABC metaclasses so QtPill can implement PillController."""


class PillController(abc.ABC):
    @abc.abstractmethod
    def set_state(self, state: SessionState) -> None:
        """Update the pill to reflect ``state``."""

    @abc.abstractmethod
    def show_message(self, msg: str) -> None:
        """Replace the label with a transient / status message."""


_BARS = 16


class QtPill(QWidget, PillController, metaclass=_QtAbcMeta):
    """Cream pill with a live waveform and status label."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = SessionState.IDLE
        self._targets = [0.15] * _BARS
        self._shown = [0.15] * _BARS
        self._phase = 0.0

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedHeight(46)
        self.setMinimumWidth(190)

        self._wave = WaveformWidget.create(_BARS, self)
        self._label = QLabel("Listening…", self)
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self._label.setStyleSheet(
            "color: %s; font-size: 13px; font-weight: 600;"
            " background: transparent;" % INK
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 8, 20, 8)
        layout.setSpacing(10)
        layout.addWidget(self._wave, 0, Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self._label, 1, Qt.AlignmentFlag.AlignVCenter)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(50)

        self._dismiss = QTimer(self)
        self._dismiss.setSingleShot(True)
        self._dismiss.setInterval(MESSAGE_DISMISS_MS)
        self._dismiss.timeout.connect(self._dismiss_message)
        self._transient = False
        self._rec_start = 0.0
        self._rec_shown_second = -1

        self.set_state(SessionState.IDLE)

    def _base_label(self) -> str:
        if self._state == SessionState.RECORDING:
            return self._recording_label()
        if self._state == SessionState.PROCESSING:
            return "Writing…"
        return ""

    def _recording_label(self) -> str:
        if self._rec_start <= 0.0:
            return "Listening…"
        elapsed = max(0, int(time.monotonic() - self._rec_start))
        return f"Listening… {elapsed // 60}:{elapsed % 60:02d}"

    def set_state(self, state: SessionState) -> None:
        self._state = state
        self._transient = False
        self._dismiss.stop()
        if state == SessionState.IDLE:
            self._timer.stop()
            self._rec_start = 0.0
            self._rec_shown_second = -1
            self.hide()
            return
        if state == SessionState.RECORDING:
            self._rec_start = time.monotonic()
            self._rec_shown_second = -1
        self._label.setText(self._base_label())
        self._reposition()
        self.update()
        self.show()
        if not self._timer.isActive():
            self._timer.start()

    def show_message(self, msg: str) -> None:
        self._transient = True
        self._label.setText(msg)
        self._reposition()
        self.update()
        self.show()
        if not self._timer.isActive():
            self._timer.start()
        self._dismiss.start()

    def _dismiss_message(self) -> None:
        """Restore the state label (or hide when idle)."""
        if not self._transient:
            return
        self._transient = False
        if self._state == SessionState.IDLE:
            self._timer.stop()
            self.hide()
            return
        # Restore the state label without resetting the recording clock.
        self._label.setText(self._base_label())
        self._reposition()
        self.update()

    def set_level(self, rms: float) -> None:
        """Feed mic energy (0..inf); only used while RECORDING."""
        base = max(0.12, min(1.0, rms / 2500.0))
        self._targets = [
            max(0.08, min(1.0, base * random.uniform(0.55, 1.25)))
            for _ in range(_BARS)
        ]

    def _tick(self) -> None:
        if self._state == SessionState.RECORDING and not self._transient:
            elapsed = max(0, int(time.monotonic() - self._rec_start))
            if elapsed != self._rec_shown_second:
                self._rec_shown_second = elapsed
                self._label.setText(self._recording_label())
                self._reposition()
        if self._state == SessionState.PROCESSING:
            self._phase += 0.45
            self._shown = [
                0.25 + 0.55 * (0.5 + 0.5 * math.sin(self._phase - i * 0.55))
                for i in range(_BARS)
            ]
        else:
            self._phase += 0.18
            idle = 0.10 + 0.04 * math.sin(self._phase)
            self._shown = [
                shown + (target - shown) * 0.35
                for shown, target in zip(self._shown, self._targets, strict=True)
            ]
            if self._state != SessionState.RECORDING:
                self._shown = [max(idle, v * 0.9) for v in self._shown]
        self._wave.set_levels(self._shown)

    def _reposition(self) -> None:
        self.adjustSize()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        x = geo.x() + (geo.width() - self.width()) // 2
        y = geo.y() + 16
        self.move(max(geo.x(), x), y)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(
            self.rect().adjusted(1, 1, -1, -1), 22, 22
        )
        painter.fillPath(path, QColor(PAPER))
        pen = painter.pen()
        pen.setColor(QColor(INK))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.end()
