"""Transcript history window: search, copy, refresh. Offscreen-safe."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

_SNIPPET_MAX = 80

_EMPTY_TEXT = (
    "Nothing here yet. Hold your push-to-talk key, speak, and "
    "your words will appear here."
)


def _time_label(ts: object) -> str:
    if ts is None:
        return "unknown time"
    try:
        moment = datetime.fromtimestamp(float(ts))
    except (OSError, OverflowError, TypeError, ValueError):
        return "unknown time"
    if moment.date() == datetime.now().date():
        return moment.strftime("%H:%M:%S")
    return moment.strftime("%Y-%m-%d %H:%M")


def _snippet(text: str) -> str:
    snippet = " ".join(text.split())
    if len(snippet) > _SNIPPET_MAX:
        return snippet[: _SNIPPET_MAX - 3] + "..."
    return snippet


def format_row(entry: dict) -> str:
    """``HH:MM:SS — snippet`` today, ``YYYY-MM-DD HH:MM — snippet`` older."""
    return f"{_time_label(entry.get('ts'))} — {_snippet(str(entry.get('text') or ''))}"


class HistoryWindow(QWidget):
    """Searchable transcript list. Copy uses the integrator-provided ``copy_fn``.

    Parameters
    ----------
    store:
        A ``TranscriptStore`` (or duck-typed equivalent) exposing ``all()``
        and ``search(query)``, both returning newest-first ``{id, ts, text}``.
    copy_fn:
        Integrator clipboard hook, ``copy_fn(text: str) -> None``. This
        window does not touch the Qt clipboard itself.

    Safe to construct under ``QT_QPA_PLATFORM=offscreen``.
    """

    def __init__(
        self,
        store: object,
        copy_fn: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._copy_fn = copy_fn

        from .theme import window_icon

        self.setWindowTitle("flow-linux history")
        self.setMinimumSize(480, 400)
        self.setWindowIcon(window_icon())
        self.setProperty("flowWindow", True)

        header = QLabel("History")
        header.setProperty("role", "title")

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search everything you said…")
        self._search.setProperty("search", True)
        self._search.textChanged.connect(self._reload)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._copy_item)
        self._list.currentItemChanged.connect(self._show_item)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setAcceptRichText(False)
        self._detail.setPlaceholderText(
            "Select an entry to read the full transcript."
        )
        self._detail.setMaximumHeight(140)

        self._empty = QLabel(_EMPTY_TEXT)
        self._empty.setProperty("role", "empty")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._copy_btn = QPushButton("Copy selected")
        self._copy_btn.setProperty("primary", True)
        self._refresh_btn = QPushButton("Refresh")
        self._copy_btn.clicked.connect(self._copy_current)
        self._refresh_btn.clicked.connect(self._reload)

        self._status = QLabel("")
        self._status.setProperty("role", "confirm")
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.setInterval(3000)
        self._status_timer.timeout.connect(lambda: self._status.setText(""))

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self._copy_btn)
        buttons.addStretch(1)
        buttons.addWidget(self._status)
        buttons.addWidget(self._refresh_btn)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(header)
        root.addWidget(self._search)
        root.addWidget(self._list, 1)
        root.addWidget(self._empty)
        root.addWidget(self._detail)
        root.addLayout(buttons)

        self._reload()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt API
        if event.key() == Qt.Key.Key_Escape and self.isWindow():
            self.close()
            return
        super().keyPressEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API, ANN001
        # Drop row geometry committed while hidden/unstyled (a forced
        # pre-show layout can freeze rows at unstyled metrics): without
        # this, rows can overlap.
        self._list.scheduleDelayedItemsLayout()
        super().showEvent(event)

    def _visible(self) -> list[dict]:
        query = self._search.text()
        if query:
            return list(self._store.search(query))
        return list(self._store.all())

    def _show_item(
        self, current: QListWidgetItem | None, _previous: object = None
    ) -> None:
        text = self._text_of(current)
        self._detail.setPlainText(text or "")

    def _reload(self) -> None:
        self._list.clear()
        for entry in self._visible():
            item = QListWidgetItem(format_row(entry))
            item.setData(Qt.ItemDataRole.UserRole, str(entry.get("text") or ""))
            self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)
        else:
            self._detail.clear()
        if self._list.count() == 0 and self._search.text().strip():
            self._empty.setText(
                f"No matches for "
                f"\u201c{self._search.text().strip()}\u201d \u2014 "
                f"try different words."
            )
        else:
            self._empty.setText(_EMPTY_TEXT)
        self._empty.setVisible(self._list.count() == 0)

    def _text_of(self, item: QListWidgetItem | None) -> str | None:
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        if value is None:
            return None
        return str(value)

    def _copy_item(self, item: QListWidgetItem | None) -> None:
        text = self._text_of(item)
        if text is None:
            return
        self._copy_fn(text)
        self._status.setText("Copied to clipboard")
        self._status_timer.start()

    def _copy_current(self) -> None:
        self._copy_item(self._list.currentItem())
