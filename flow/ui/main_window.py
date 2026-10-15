"""Main window: sidebar navigation over Dictate/History/Notes/Dictionary/Settings.

The Dictate home page shows live mic state, a level meter, and the last
transcript. The other pages embed the existing History, Notes, Dictionary,
and Settings widgets so standalone windows and the main window share logic.
"""

from __future__ import annotations

import os
import random
from collections.abc import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..config import Settings
from ..events import SessionState
from .dictionary import DictionaryWidget
from .history_window import HistoryWindow
from .scratchpad import ScratchpadWindow
from .settings import SettingsWidget
from .theme import WaveformWidget, window_icon

PAGES: tuple[tuple[str, str], ...] = (
    ("dictate", "Dictate"),
    ("history", "History"),
    ("notes", "Notes"),
    ("dictionary", "Dictionary"),
    ("settings", "Settings"),
)

_UNSAVED_TEXT = "Unsaved changes"


def default_copy(text: str) -> None:
    """Clipboard hook used when the integrator passes no ``copy_fn``."""
    try:
        QApplication.clipboard().setText(text)
    except Exception:  # noqa: BLE001 - clipboard is best effort
        pass


class DictatePage(QWidget):
    """Home page: capture controls + level meter + editable transcript.

    Start/Stop/Cancel drive the normal service recording path through the
    integrator callbacks, so click-to-dictate works with no hotkeys
    (Wayland, failed grabs). The transcript is editable; Copy and Insert
    act on the edited text, and the insert line reports typed / copied /
    held-for-review explicitly.
    """

    _BARS = 28

    def __init__(
        self,
        *,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
        on_cancel: Callable[[], None] | None = None,
        on_insert: Callable[[str], None] | None = None,
        copy_fn: Callable[[str], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_cancel = on_cancel
        self._on_insert = on_insert
        self._copy_fn = copy_fn or default_copy
        self._targets = [0.12] * self._BARS
        self._shown = [0.12] * self._BARS

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(12)

        title = QLabel("Dictate")
        title.setProperty("role", "title")
        root.addWidget(title)

        self._status = QLabel("Ready")
        self._status.setProperty("role", "status")
        root.addWidget(self._status)

        self._hint = QLabel("")
        self._hint.setProperty("role", "hint")
        self._hint.setWordWrap(True)
        root.addWidget(self._hint)

        self._wave = WaveformWidget.create(self._BARS, self)
        wave_row = QHBoxLayout()
        wave_row.addWidget(self._wave)
        wave_row.addStretch(1)
        root.addLayout(wave_row)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._start_btn = QPushButton("Start dictation")
        self._start_btn.setProperty("primary", True)
        self._stop_btn = QPushButton("Stop")
        self._cancel_btn = QPushButton("Cancel")
        self._start_btn.clicked.connect(self._click_start)
        self._stop_btn.clicked.connect(self._click_stop)
        self._cancel_btn.clicked.connect(self._click_cancel)
        controls.addWidget(self._start_btn)
        controls.addWidget(self._stop_btn)
        controls.addWidget(self._cancel_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        last_title = QLabel("Last transcript (editable)")
        last_title.setProperty("role", "section")
        root.addWidget(last_title)

        self._last = QTextEdit()
        self._last.setProperty("role", "transcript")
        self._last.setAcceptRichText(False)
        self._last.setPlaceholderText("Your last dictation will appear here.")
        self._last.setMinimumHeight(90)
        root.addWidget(self._last)

        self._insert_status = QLabel("")
        self._insert_status.setProperty("role", "hint")
        self._insert_status.setWordWrap(True)
        root.addWidget(self._insert_status)

        review = QHBoxLayout()
        review.setSpacing(8)
        self._copy_btn = QPushButton("Copy")
        self._insert_btn = QPushButton("Type into app")
        self._insert_btn.setToolTip(
            "Type the text above at the cursor (for held-for-review results)"
        )
        self._copy_btn.clicked.connect(self._click_copy)
        self._insert_btn.clicked.connect(self._click_insert)
        review.addWidget(self._copy_btn)
        review.addWidget(self._insert_btn)
        review.addStretch(1)
        root.addLayout(review)
        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(80)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self.set_shortcuts("Alt+W", "Alt+E")
        self.set_state(SessionState.IDLE)

    def set_shortcuts(self, ptt: str, handsfree: str) -> None:
        self._hint.setText(
            f"Hold {ptt} to talk, release to type. "
            f"{handsfree} toggles hands-free. Speak anywhere."
        )

    def set_state(self, state: SessionState) -> None:
        if state == SessionState.RECORDING:
            self._status.setText("Listening…")
        elif state == SessionState.PROCESSING:
            self._status.setText("Writing…")
        else:
            self._status.setText("Ready")
            self._targets = [0.12] * self._BARS
        recording = state == SessionState.RECORDING
        busy = state != SessionState.IDLE
        self._start_btn.setEnabled(not busy)
        self._stop_btn.setEnabled(recording)
        self._cancel_btn.setEnabled(busy)

    def set_level(self, rms: float) -> None:
        base = max(0.12, min(1.0, rms / 2500.0))
        self._targets = [
            max(0.08, min(1.0, base * random.uniform(0.55, 1.25)))
            for _ in range(self._BARS)
        ]

    def set_last_transcript(self, text: str) -> None:
        self._last.setPlainText(text)
        self._last.moveCursor(QTextCursor.MoveOperation.End)

    def reviewed_text(self) -> str:
        """Current editor content (may differ from the transcript)."""
        return self._last.toPlainText()

    def set_insert_status(self, text: str) -> None:
        self._insert_status.setText(text)

    def _click_start(self) -> None:
        if self._on_start is not None:
            self._on_start()

    def _click_stop(self) -> None:
        if self._on_stop is not None:
            self._on_stop()

    def _click_cancel(self) -> None:
        if self._on_cancel is not None:
            self._on_cancel()

    def _click_copy(self) -> None:
        text = self.reviewed_text()
        if text.strip():
            self._copy_fn(text)
            self.set_insert_status("Copied to clipboard")

    def _click_insert(self) -> None:
        if self._on_insert is not None and self.reviewed_text().strip():
            self._on_insert(self.reviewed_text())

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API, ANN001
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API, ANN001
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        self._shown = [
            shown + (target - shown) * 0.3
            for shown, target in zip(self._shown, self._targets, strict=True)
        ]
        self._targets = [max(0.10, v * 0.92) for v in self._targets]
        self._wave.set_levels(self._shown)


class FlowMainWindow(QMainWindow):
    """One integrated window; tray entries call ``show_page`` on it."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        history_store=None,
        note_store=None,
        dict_store=None,
        on_save_settings: Callable[[Settings], None] | None = None,
        on_save_dictionary=None,
        on_dictate: Callable[[], str | None] | None = None,
        on_dictate_error: Callable[[], str | None] | None = None,
        on_dictate_start: Callable[[], None] | None = None,
        on_dictate_stop: Callable[[], None] | None = None,
        on_dictate_cancel: Callable[[], None] | None = None,
        on_insert_text: Callable[[str], None] | None = None,
        on_refresh_history: Callable[[], list[str]] | None = None,
        copy_fn: Callable[[str], None] | None = None,
        initial_autostart: bool = False,
        on_autostart_toggle: Callable[[bool], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings or Settings()
        self._on_save_settings = on_save_settings
        self._on_save_dictionary = on_save_dictionary

        self.setWindowTitle("flow-linux")
        self.setMinimumSize(880, 580)
        self.setWindowIcon(window_icon())
        self.setProperty("flowWindow", True)

        if history_store is None:
            from ..history import TranscriptStore

            history_store = TranscriptStore()
        if note_store is None:
            from ..notes import NoteStore

            note_store = NoteStore()
        if dict_store is None:
            from ..dictionary import DictionaryStore

            dict_store = DictionaryStore(
                os.path.expanduser("~/.config/flow-linux/hotwords.txt")
            )

        central = QWidget(self)
        central.setProperty("flowWindow", True)
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(8)
        self._banner = QLabel("")
        self._banner.setProperty("role", "banner")
        self._banner.setWordWrap(True)
        self._banner.setVisible(False)
        outer.addWidget(self._banner)
        body = QHBoxLayout()
        body.setSpacing(16)
        outer.addLayout(body)

        # -- sidebar -------------------------------------------------
        side = QVBoxLayout()
        side.setSpacing(8)
        brand = QLabel("flow")
        brand.setProperty("role", "title")
        side.addWidget(brand)
        self._nav = QListWidget()
        self._nav.setProperty("nav", True)
        self._nav.setFixedWidth(168)
        self._nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._nav.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        for key, label in PAGES:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, key)
            # Explicit height: QSS padding is not in the size hint and rows
            # would otherwise overlap when the selected pill paints.
            item.setSizeHint(QSize(150, 44))
            self._nav.addItem(item)
        self._nav.setFixedHeight(self._nav.sizeHintForRow(0) * len(PAGES) + 12)
        self._nav.currentRowChanged.connect(self._on_nav)
        side.addWidget(self._nav)
        side.addStretch(1)
        self._side_state = QLabel("Ready")
        self._side_state.setProperty("role", "hint")
        side.addWidget(self._side_state)
        body.addLayout(side)

        # -- pages ---------------------------------------------------
        self._stack = QStackedWidget()
        body.addWidget(self._stack, 1)
        self._pages: dict[str, QWidget] = {}
        self._index: dict[str, int] = {}

        self._dictate = DictatePage(
            on_start=on_dictate_start,
            on_stop=on_dictate_stop,
            on_cancel=on_dictate_cancel,
            on_insert=on_insert_text,
            copy_fn=copy_fn or default_copy,
            parent=self,
        )
        self._dictate.set_shortcuts(
            self._settings.ptt_shortcut, self._settings.handsfree_shortcut
        )
        self._add_page("dictate", self._dictate)

        self._history_win = HistoryWindow(
            history_store, copy_fn or default_copy, parent=self
        )
        self._add_page("history", self._history_win)

        self._notes_win = ScratchpadWindow(
            note_store,
            on_dictate or (lambda: None),
            parent=self,
            on_dictate_error=on_dictate_error,
        )
        self._add_page("notes", self._notes_win)

        dict_page = QWidget(self)
        dict_layout = QVBoxLayout(dict_page)
        dict_layout.setContentsMargins(28, 24, 28, 24)
        dict_layout.setSpacing(10)
        dict_title = QLabel("Dictionary")
        dict_title.setProperty("role", "title")
        dict_layout.addWidget(dict_title)
        self._dict_form = DictionaryWidget(dict_store, dict_page)
        dict_layout.addWidget(self._dict_form, 1)
        dict_btn_row = QHBoxLayout()
        dict_btn_row.addStretch(1)
        self._dict_save_btn = QPushButton("Save")
        self._dict_save_btn.setProperty("primary", True)
        self._dict_save_btn.clicked.connect(self._save_dictionary)
        dict_btn_row.addWidget(self._dict_save_btn)
        dict_layout.addLayout(dict_btn_row)
        self._add_page("dictionary", dict_page)

        settings_page = QWidget(self)
        settings_layout = QVBoxLayout(settings_page)
        settings_layout.setContentsMargins(28, 24, 28, 24)
        settings_layout.setSpacing(10)
        settings_title = QLabel("Settings")
        settings_title.setProperty("role", "title")
        settings_layout.addWidget(settings_title)
        self._settings_form = SettingsWidget(
            self._settings,
            on_refresh_history=on_refresh_history,
            initial_autostart=initial_autostart,
            on_autostart_toggle=on_autostart_toggle,
            parent=settings_page,
        )
        # Scroll instead of squeeze: at small heights the shortcut rows
        # keep their styled size hints instead of overlapping.
        self._settings_scroll = QScrollArea(settings_page)
        self._settings_scroll.setWidgetResizable(True)
        self._settings_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self._settings_scroll.setWidget(self._settings_form)
        settings_layout.addWidget(self._settings_scroll, 1)
        settings_btn_row = QHBoxLayout()
        self._settings_status = QLabel("")
        self._settings_status.setProperty("role", "confirm")
        settings_btn_row.addWidget(self._settings_status)
        settings_btn_row.addStretch(1)
        self._settings_save_btn = QPushButton("Save")
        self._settings_save_btn.setProperty("primary", True)
        self._settings_save_btn.clicked.connect(self._save_settings)
        self._settings_form._save_btn = self._settings_save_btn
        # The form's inline error sits at the bottom of the scroll area and
        # is often below the fold while Save is disabled with no visible
        # reason: mirror it into the always-visible status line and scroll
        # the inline error into view.
        self._mirrored_error = ""
        self._settings_form._validated.connect(self._mirror_form_error)
        for editor in self._settings_form._editors.values():
            editor.textChanged.connect(self._sync_saved_status)
        self._settings_form._engine.currentTextChanged.connect(
            self._sync_saved_status
        )
        self._settings_form._revalidate()
        settings_btn_row.addWidget(self._settings_save_btn)
        settings_layout.addLayout(settings_btn_row)
        self._add_page("settings", settings_page)

        self._nav.setCurrentRow(0)

    # -- navigation --------------------------------------------------
    def _add_page(self, key: str, widget: QWidget) -> None:
        self._index[key] = self._stack.addWidget(widget)
        self._pages[key] = widget

    def _on_nav(self, row: int) -> None:
        item = self._nav.item(row)
        if item is None:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if key in self._index:
            self._notes_win.flush()  # never lose a draft on page switch
            self._stack.setCurrentIndex(self._index[key])

    def flush_drafts(self) -> None:
        """Persist notes draft + dictionary edits (quit path). Never raises."""
        try:
            self._notes_win.flush()
        except Exception:  # noqa: BLE001 - quitting must not fail
            pass
        try:
            self._dict_form.flush()
        except Exception:  # noqa: BLE001 - quitting must not fail
            pass

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API, ANN001
        self.flush_drafts()
        super().closeEvent(event)

    def show_page(self, key: str) -> None:
        """Show the window with ``key`` selected; unknown keys are ignored."""
        if key not in self._index:
            key = "dictate"
        for row in range(self._nav.count()):
            item = self._nav.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == key:
                self._nav.setCurrentRow(row)
                break
        self._stack.setCurrentIndex(self._index[key])
        self.show()
        self.raise_()
        self.activateWindow()

    def set_banner(self, text: str) -> None:
        """Show a full-width notice (e.g. hotkeys unavailable)."""
        self._banner.setText(text)
        self._banner.setVisible(True)

    def clear_banner(self) -> None:
        self._banner.setText("")
        self._banner.setVisible(False)

    # -- live service hooks (called from flowd bus handlers) ---------
    def set_state(self, state: SessionState) -> None:
        self._dictate.set_state(state)
        if state == SessionState.RECORDING:
            self._side_state.setText("Listening…")
        elif state == SessionState.PROCESSING:
            self._side_state.setText("Writing…")
        else:
            self._side_state.setText("Ready")

    def set_level(self, rms: float) -> None:
        self._dictate.set_level(rms)

    def on_transcript(self, text: str) -> None:
        self._dictate.set_last_transcript(text)
        self._history_win._reload()

    def on_insert(self, pair: tuple) -> None:
        """Show explicit insertion status from the service "insert" event."""
        method, detail = pair
        if method == "typed":
            short = str(detail).removesuffix("Typer")
            self._dictate.set_insert_status(f"Typed into app via {short}")
        elif method == "copied":
            self._dictate.set_insert_status(
                "No text field — copied to clipboard"
            )
        elif method == "held":
            self._dictate.set_insert_status(str(detail))
        else:
            self._dictate.set_insert_status(f"Insert failed: {detail}")

    def refresh_settings(self, settings: Settings) -> None:
        """Sync the settings form + dictate hints after a live apply."""
        self._settings = settings
        for field, editor in self._settings_form._editors.items():
            editor.setText(getattr(settings, field))
        self._settings_form._engine.setCurrentText(settings.engine)
        self._settings_form._settings = settings
        self._dictate.set_shortcuts(
            settings.ptt_shortcut, settings.handsfree_shortcut
        )

    # -- page actions ------------------------------------------------
    def _mirror_form_error(self, text: str) -> None:
        """Mirror the scrolled form error into the visible status line."""
        if text:
            first_sight = not self._mirrored_error
            self._mirrored_error = text
            self._set_settings_status(text, role="error")
            if first_sight:
                # Scroll once on appearance; every keystroke after that
                # would yank the view while the user is still typing.
                self._settings_scroll.ensureWidgetVisible(
                    self._settings_form._error, 0, 0
                )
        elif self._settings_status.text() == self._mirrored_error:
            self._mirrored_error = ""
            self._set_settings_status("", role="confirm")

    def _set_settings_status(self, text: str, role: str = "confirm") -> None:
        self._settings_status.setProperty("role", role)
        style = self._settings_status.style()
        if style is not None:
            style.unpolish(self._settings_status)
            style.polish(self._settings_status)
        self._settings_status.setText(text)

    def _sync_saved_status(self) -> None:
        """Replace a stale Saved message with an unsaved-changes marker."""
        form = self._settings_form
        if not form.is_valid():
            return  # error mirror owns the status line
        if form.values() != self._settings:
            if self._settings_status.text() != _UNSAVED_TEXT:
                self._set_settings_status(_UNSAVED_TEXT, role="hint")
        elif self._settings_status.text() == _UNSAVED_TEXT:
            self._set_settings_status("", role="confirm")

    def _save_settings(self) -> None:
        self._settings_form._revalidate()
        if not self._settings_form.is_valid():
            self._set_settings_status(
                self._settings_form._error.text(), role="error"
            )
            return
        values = self._settings_form.values()
        try:
            if self._on_save_settings is not None:
                self._on_save_settings(values)
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            self._set_settings_status(f"Save failed: {exc}", role="error")
            return
        self._settings = values
        self._settings_form._settings = values
        self._dictate.set_shortcuts(
            values.ptt_shortcut, values.handsfree_shortcut
        )
        self._set_settings_status("Saved — applied immediately")

    def _save_dictionary(self) -> None:
        self._dict_form.save_with_feedback(self._on_save_dictionary)
