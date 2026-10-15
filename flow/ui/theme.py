"""Shared look: Wispr-style cream + ink theme for every window.

Usage: call ``apply_theme(app)`` once, and set the ``flowWindow``
dynamic property on each top-level window so the QSS below applies::

    window.setProperty("flowWindow", True)

Roles for labels: ``title`` (16/700), ``section`` (12/700), ``hint``
(11px muted). Primary buttons: ``setProperty("primary", True)``.
"""

from __future__ import annotations

PAPER = "#F4F1E8"  # window background
CARD = "#FBFAF5"  # inputs, lists, menus
INK = "#1C1B18"  # text, primary buttons, waveform bars
INK_SOFT = "#4A463C"  # secondary text
MUTED = "#6B6558"  # hints, placeholders (4.5:1 on PAPER, WCAG AA)
HAIRLINE = "#DED7C3"  # borders
SAND = "#EAE4D3"  # ghost button bg
SAND_HOVER = "#E0D7BF"
SAND_PRESS = "#D5CCB2"
RECORD_RED = "#C0352B"  # recording dot, errors
PROCESS_AMBER = "#B7791F"  # processing dot

STYLESHEET = f"""
QWidget[flowWindow="true"] {{
    background: {PAPER};
    color: {INK};
    font-size: 13px;
}}
QWidget[flowWindow="true"] QLabel[role="title"] {{
    font-size: 16px;
    font-weight: 700;
    color: {INK};
    margin: 2px 0 6px 0;
}}
QWidget[flowWindow="true"] QLabel[role="section"] {{
    font-size: 12px;
    font-weight: 700;
    color: {INK_SOFT};
    margin-top: 10px;
}}
QWidget[flowWindow="true"] QLabel[role="hint"] {{
    font-size: 11px;
    color: {MUTED};
}}
QWidget[flowWindow="true"] QLabel[role="error"] {{
    font-size: 12px;
    color: {RECORD_RED};
}}
QWidget[flowWindow="true"] QLabel[role="banner"] {{
    font-size: 12px;
    color: {INK};
    background: {CARD};
    border: 1px solid {HAIRLINE};
    border-radius: 8px;
    padding: 7px 10px;
}}
QWidget[flowWindow="true"] QLineEdit,
QWidget[flowWindow="true"] QTextEdit,
QWidget[flowWindow="true"] QComboBox {{
    background: {CARD};
    border: 1px solid {HAIRLINE};
    border-radius: 8px;
    padding: 7px 10px;
    color: {INK};
    selection-background-color: {INK};
    selection-color: {PAPER};
}}
QWidget[flowWindow="true"] QLineEdit:focus,
QWidget[flowWindow="true"] QTextEdit:focus,
QWidget[flowWindow="true"] QComboBox:focus {{
    border: 1px solid {INK};
    background: #FFFFFF;
}}
QWidget[flowWindow="true"] QLineEdit[search="true"] {{
    border-radius: 14px;
    padding-left: 14px;
}}
QWidget[flowWindow="true"] QPushButton {{
    background: {SAND};
    border: 1px solid {HAIRLINE};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 600;
    color: {INK};
}}
QWidget[flowWindow="true"] QPushButton:hover {{
    background: {SAND_HOVER};
}}
QWidget[flowWindow="true"] QPushButton:pressed {{
    background: {SAND_PRESS};
}}
QWidget[flowWindow="true"] QPushButton[primary="true"] {{
    background: {INK};
    border: none;
    color: {PAPER};
}}
QWidget[flowWindow="true"] QPushButton[primary="true"]:hover {{
    background: #33302A;
}}
QWidget[flowWindow="true"] QPushButton[primary="true"]:pressed {{
    background: #100F0D;
}}
QWidget[flowWindow="true"] QPushButton:disabled {{
    color: {MUTED};
    background: {SAND};
}}
QWidget[flowWindow="true"] QListWidget {{
    background: {CARD};
    border: 1px solid {HAIRLINE};
    border-radius: 10px;
    padding: 6px;
    outline: 0;
}}
QWidget[flowWindow="true"] QListWidget::item {{
    padding: 8px 10px;
    border-radius: 6px;
}}
QWidget[flowWindow="true"] QListWidget::item:selected {{
    background: {INK};
    color: {PAPER};
}}
QWidget[flowWindow="true"] QListWidget::item:hover:!selected {{
    background: {SAND};
}}
QWidget[flowWindow="true"] QListWidget[nav="true"] {{
    background: transparent;
    border: none;
    padding: 4px;
    outline: 0;
}}
QWidget[flowWindow="true"] QListWidget[nav="true"]::item {{
    padding: 10px 12px;
    border-radius: 8px;
    font-weight: 600;
    color: {INK_SOFT};
}}
QWidget[flowWindow="true"] QListWidget[nav="true"]::item:selected {{
    background: {INK};
    color: {PAPER};
}}
QWidget[flowWindow="true"] QListWidget[nav="true"]::item:hover:!selected {{
    background: {SAND};
    color: {INK};
}}
QWidget[flowWindow="true"] QLabel[role="status"] {{
    font-size: 20px;
    font-weight: 700;
    color: {INK};
}}
QWidget[flowWindow="true"] QLabel[role="transcript"],
QWidget[flowWindow="true"] QTextEdit[role="transcript"] {{
    font-size: 14px;
    color: {INK};
    background: {CARD};
    border: 1px solid {HAIRLINE};
    border-radius: 10px;
    padding: 12px;
}}
QWidget[flowWindow="true"] QLabel[role="empty"] {{
    font-size: 13px;
    color: {MUTED};
}}
QWidget[flowWindow="true"] QLabel[role="confirm"] {{
    font-size: 12px;
    font-weight: 600;
    color: {INK_SOFT};
}}
QWidget[flowWindow="true"] QFrame[card="true"] {{
    background: {CARD};
    border: 1px solid {HAIRLINE};
    border-radius: 12px;
}}
QWidget[flowWindow="true"] QPushButton[recording="true"] {{
    background: {RECORD_RED};
    border: none;
    color: #FFFFFF;
}}
QWidget[flowWindow="true"] QCheckBox {{
    spacing: 8px;
}}
QWidget[flowWindow="true"] QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 9px;
    border: 1px solid {HAIRLINE};
    background: {CARD};
}}
QWidget[flowWindow="true"] QCheckBox::indicator:checked {{
    background: {INK};
    border: 1px solid {INK};
}}
QWidget[flowWindow="true"] QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QWidget[flowWindow="true"] QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {HAIRLINE};
    selection-background-color: {INK};
    selection-color: {PAPER};
    outline: 0;
}}
QWidget[flowWindow="true"] QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}
QWidget[flowWindow="true"] QScrollBar::handle:vertical {{
    background: #C9C1AB;
    border-radius: 4px;
    min-height: 30px;
}}
QWidget[flowWindow="true"] QScrollBar::add-line:vertical,
QWidget[flowWindow="true"] QScrollBar::sub-line:vertical {{
    height: 0;
}}
QWidget[flowWindow="true"] QDialogButtonBox QPushButton {{
    min-width: 90px;
}}
QMenu[flowMenu="true"] {{
    background: {CARD};
    border: 1px solid {HAIRLINE};
    padding: 6px;
}}
QMenu[flowMenu="true"]::item {{
    padding: 7px 24px;
    border-radius: 6px;
}}
QMenu[flowMenu="true"]::item:selected {{
    background: {INK};
    color: {PAPER};
}}
QToolTip {{
    background: {INK};
    color: {PAPER};
    border: none;
    padding: 5px 8px;
}}
"""


def window_icon(size: int = 64):
    """App icon for window/taskbar use (lazy import avoids a cycle)."""
    from .tray import _drawn_icon

    return _drawn_icon(size)


def apply_theme(app) -> None:
    """Apply the shared stylesheet + selection palette to the app."""
    app.setStyleSheet(STYLESHEET)
    try:
        from PySide6.QtGui import QColor, QPalette

        palette = app.palette()
        palette.setColor(QPalette.ColorRole.Highlight, QColor(INK))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(PAPER))
        app.setPalette(palette)
    except Exception:
        pass


class WaveformWidget:
    """Factory holder; real widget defined below once Qt is available."""

    @staticmethod
    def create(bars: int = 18, parent=None):
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPainter
        from PySide6.QtWidgets import QWidget

        class _Waveform(QWidget):
            def __init__(self) -> None:
                super().__init__(parent)
                self._levels = [0.15] * bars
                self._color = QColor(INK)
                gap, bar = 3, 3
                self.setFixedSize(bars * (bar + gap), 24)

            def set_levels(self, levels) -> None:
                self._levels = [max(0.06, min(1.0, float(v))) for v in levels][
                    :bars
                ]
                self.update()

            def set_color(self, name: str) -> None:
                self._color = QColor(name)
                self.update()

            def paintEvent(self, event) -> None:  # noqa: N802 - Qt API
                painter = QPainter(self)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._color)
                gap, bar, h = 3, 3, self.height()
                for i, level in enumerate(self._levels):
                    bh = max(3.0, level * h)
                    x = i * (bar + gap)
                    y = (h - bh) / 2
                    painter.drawRoundedRect(
                        int(x), int(y), bar, int(bh), bar / 2, bar / 2
                    )
                painter.end()

        return _Waveform()
