"""System tray icon with Settings and Quit hooks."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


def _drawn_icon(size: int = 64) -> QIcon:
    from .theme import INK, PAPER

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    # Cream disc, ink ring, ink waveform bars.
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(PAPER))
    painter.drawEllipse(1, 1, size - 2, size - 2)
    pen = painter.pen()
    pen.setColor(QColor(INK))
    pen.setWidth(max(2, size // 24))
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(INK))
    heights = (0.55, 1.0, 0.75, 0.45)
    area = size * 0.56
    gap = max(1, round(size / 22))
    bar = max(2, round((area - gap * (len(heights) - 1)) / len(heights)))
    total = bar * len(heights) + gap * (len(heights) - 1)
    x0 = round((size - total) / 2)
    for i, h in enumerate(heights):
        bh = max(bar, round(h * size * 0.5))
        x = x0 + i * (bar + gap)
        y = round((size - bh) / 2)
        painter.drawRoundedRect(x, y, bar, bh, bar // 2, bar // 2)
    painter.end()
    return QIcon(pixmap)


class TrayIcon:
    """QSystemTrayIcon wrapper. Safe to construct under offscreen Qt."""

    def __init__(
        self,
        *,
        on_settings: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
        actions: tuple[tuple[str, Callable[[], None]], ...] = (),
        parent: QWidget | None = None,
    ) -> None:
        self._on_settings = on_settings
        self._on_quit = on_quit
        self._actions = actions
        self._icon = _drawn_icon()
        self._tray = QSystemTrayIcon(self._icon, parent)
        self._tray.setToolTip("flow-linux")

        menu = QMenu(parent)
        settings_act = menu.addAction("Settings")
        settings_act.triggered.connect(self._emit_settings)
        for label, callback in self._actions:
            act = menu.addAction(label)
            act.triggered.connect(callback)
        menu.addSeparator()
        quit_act = menu.addAction("Quit")
        quit_act.triggered.connect(self._emit_quit)
        self._tray.setContextMenu(menu)
        self._menu = menu
        self._tray.show()

    @property
    def icon(self) -> QSystemTrayIcon:
        return self._tray

    def _emit_settings(self) -> None:
        if self._on_settings is not None:
            self._on_settings()

    def _emit_quit(self) -> None:
        if self._on_quit is not None:
            self._on_quit()

    def notify(self, title: str, message: str) -> None:
        """Desktop balloon (used for copied-to-clipboard notices)."""
        self._tray.showMessage(title, message)
