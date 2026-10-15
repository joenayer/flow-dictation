"""Dictated-notes scratchpad window (offscreen-safe)."""

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


class ScratchpadWindow(QWidget):
    """Notes list + editor with an integrator-provided Dictate hook.

    Parameters
    ----------
    store:
        A ``NoteStore`` (or duck-typed equivalent) used for persistence.
        The window calls ``create``, ``get``, ``list_all``, ``update``,
        and ``delete``.
    on_dictate:
        Integrator-provided callback with signature ``() -> str | None``.
        The integrator records audio and transcribes it; this window does
        not capture or run STT itself. A non-empty string is inserted at
        the originating note and cursor (recording is bound to where it
        began even if selection moved mid-speech).
    on_dictate_error:
        Optional ``() -> str | None`` describing the last falsy
        ``on_dictate`` result: an error message, or None for a plain
        user cancel. Shown in the status line so microphone/transcribe
        failures are never silent.

    Safe to construct under ``QT_QPA_PLATFORM=offscreen``.
    """

    def __init__(
        self,
        store: object,
        on_dictate: Callable[[], str | None],
        parent: QWidget | None = None,
        on_dictate_error: Callable[[], str | None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._store = store
        self._on_dictate = on_dictate
        self._on_dictate_error = on_dictate_error

        from .theme import window_icon

        self.setWindowTitle("flow-linux notes")
        self.setMinimumSize(520, 420)
        self.setWindowIcon(window_icon())
        self.setProperty("flowWindow", True)

        header = QLabel("Notes")
        header.setProperty("role", "title")

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_current_changed)

        self._empty = QLabel(
            "No notes yet. Press New, or Dictate and speak — "
            "your words will land here."
        )
        self._empty.setProperty("role", "empty")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title = QLineEdit()
        self._title.setPlaceholderText("Title")

        self._body = QTextEdit()
        self._body.setAcceptRichText(False)
        self._body.setPlaceholderText("Note body — or press Dictate and speak")

        # Debounced autosave: edits persist 800 ms after typing stops, so
        # nav-away and quit never lose a draft (L7). Guarded by _loading
        # so programmatic fills don't schedule writes.
        self._loading = True
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(800)
        self._autosave_timer.timeout.connect(self._autosave)
        self._title.textChanged.connect(self._schedule_autosave)
        self._body.textChanged.connect(self._schedule_autosave)

        self._trash: dict | None = None
        self._new_btn = QPushButton("New")
        self._delete_btn = QPushButton("Delete")
        self._undo_btn = QPushButton("Undo delete")
        self._undo_btn.setEnabled(False)
        self._undo_btn.setToolTip("Restore the last deleted note")
        self._save_btn = QPushButton("Save")
        self._dictate_btn = QPushButton("Dictate")
        self._dictate_btn.setProperty("primary", True)
        self._new_btn.clicked.connect(self._new_note)
        self._delete_btn.clicked.connect(self._delete_note)
        self._undo_btn.clicked.connect(self._undo_delete)
        self._save_btn.clicked.connect(self._save_note)
        self._dictate_btn.clicked.connect(self._dictate)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self._new_btn)
        buttons.addWidget(self._delete_btn)
        buttons.addWidget(self._undo_btn)
        buttons.addWidget(self._save_btn)
        buttons.addStretch(1)
        buttons.addWidget(self._dictate_btn)

        self._status = QLabel("")
        self._status.setProperty("role", "hint")
        self._status.setWordWrap(True)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)
        root.addWidget(header)
        root.addWidget(self._list, 1)
        root.addWidget(self._empty)
        root.addWidget(self._title)
        root.addWidget(self._body, 2)
        root.addLayout(buttons)
        root.addWidget(self._status)

        self._refresh_list()
        self._loading = False
        load_error = getattr(store, "load_error", None)
        if load_error:
            self._set_status(str(load_error), error=True)

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

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API, ANN001
        self.flush()  # page switch / window hide never loses a draft
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API, ANN001
        self.flush()
        super().closeEvent(event)

    def _schedule_autosave(self) -> None:
        if self._loading:
            return
        self._autosave_timer.start()

    def _autosave(self) -> None:
        self._autosave_timer.stop()
        note_id = self._current_id()
        title = self._title.text()
        body = self._body.toPlainText()
        if note_id:
            if (
                self._try_store(
                    lambda: self._store.update(note_id, title, body),
                    "save note",
                )
                is None
            ):
                return
            item = self._list.currentItem()
            if item is not None:
                note = self._store.get(note_id)
                if note is not None:
                    item.setText(self._item_label(note))
            return
        if not title.strip() and not body.strip():
            return
        # Draft with no note yet (empty list): adopt it as a new note.
        created = self._try_store(
            lambda: self._store.create(title.strip() or "Untitled"),
            "create note",
        )
        if created is None:
            return
        if (
            self._try_store(
                lambda: self._store.update(created, title, body),
                "save note",
            )
            is None
        ):
            return
        self._refresh_list(select_id=created)

    def flush(self) -> None:
        """Write any pending draft now (nav-away, hide, quit, transitions).

        Always runs the full autosave path so id-less drafts (empty list)
        are adopted as notes instead of dropped.
        """
        self._autosave()

    def _item_label(self, note: dict) -> str:
        title = str(note.get("title") or "").strip() or "(untitled)"
        try:
            stamp = datetime.fromtimestamp(float(note.get("ts") or 0.0))
            date = stamp.strftime("%Y-%m-%d %H:%M")
        except (OSError, OverflowError, TypeError, ValueError):
            date = ""
        if date:
            return f"{title}  {date}"
        return title

    def _current_id(self) -> str | None:
        item = self._list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        if value is None:
            return None
        return str(value)

    def _refresh_list(self, select_id: str | None = None) -> None:
        target = select_id or self._current_id()
        self._list.blockSignals(True)
        self._list.clear()
        current_item: QListWidgetItem | None = None
        for note in self._store.list_all():
            item = QListWidgetItem(self._item_label(note))
            item.setData(Qt.ItemDataRole.UserRole, note["id"])
            self._list.addItem(item)
            if target is not None and note["id"] == target:
                current_item = item
        if current_item is None and self._list.count() > 0:
            current_item = self._list.item(0)
        if current_item is not None:
            self._list.setCurrentItem(current_item)
        self._list.blockSignals(False)
        self._empty.setVisible(self._list.count() == 0)
        self._load_selected()

    def _load_selected(self) -> None:
        self._loading = True
        try:
            note_id = self._current_id()
            if not note_id:
                self._title.clear()
                self._body.clear()
                return
            note = self._store.get(note_id)
            if note is None:
                self._title.clear()
                self._body.clear()
                return
            self._title.setText(note.get("title") or "")
            self._body.setPlainText(note.get("body") or "")
        finally:
            self._loading = False

    def _on_current_changed(
        self,
        _current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        self._autosave_timer.stop()
        # Auto-save the note being left so switching never loses edits.
        if previous is not None:
            prev_id = previous.data(Qt.ItemDataRole.UserRole)
            if prev_id is not None:
                self._try_store(
                    lambda: self._store.update(
                        str(prev_id),
                        self._title.text(),
                        self._body.toPlainText(),
                    ),
                    "save note",
                )
        self._load_selected()

    def _new_note(self) -> None:
        # Persist the current draft first (including an id-less first
        # draft): _refresh_list blocks signals, so the switch auto-save
        # would not run for this transition.
        self.flush()
        note_id = self._try_store(
            lambda: self._store.create("Untitled"), "create note"
        )
        if note_id is None:
            return
        self._refresh_list(select_id=note_id)
        self._load_selected()
        self._title.selectAll()

    def _delete_note(self) -> None:
        self._autosave_timer.stop()
        note_id = self._current_id()
        if not note_id:
            return
        # Stash what the user sees (including unsaved edits) for Undo.
        self._trash = {
            "title": self._title.text(),
            "body": self._body.toPlainText(),
        }
        self._undo_btn.setEnabled(True)
        if (
            self._try_store(
                lambda: self._store.delete(note_id), "delete note"
            )
            is None
        ):
            return
        self._refresh_list()
        if self._list.count() == 0:
            self._title.clear()
            self._body.clear()
        else:
            self._load_selected()

    def _undo_delete(self) -> None:
        if not self._trash:
            return
        # Flush first: the restore rebuilds the list and replaces the
        # editor, which would orphan a pending draft in another note.
        self.flush()
        title = self._trash.get("title") or "Untitled"
        body = self._trash.get("body") or ""
        # Single atomic restore; the trash payload (and the Undo button)
        # is only cleared once the write has committed, so a failed
        # restore keeps the body for retry.
        create_full = getattr(self._store, "create_full", None)
        if create_full is None:  # duck-typed legacy stores in tests
            restore = lambda: self._store.create(title)  # noqa: E731
        else:
            restore = lambda: create_full(title, body)  # noqa: E731
        note_id = self._try_store(restore, "restore note")
        if note_id is None:
            return
        if create_full is None and (
            self._try_store(
                lambda: self._store.update(note_id, title, body),
                "restore note",
            )
            is None
        ):
            return
        self._trash = None
        self._undo_btn.setEnabled(False)
        self._refresh_list(select_id=note_id)
        self._load_selected()

    def _save_note(self) -> None:
        self._autosave_timer.stop()
        title = self._title.text()
        body = self._body.toPlainText()
        note_id = self._current_id()
        if not note_id:
            note_id = self._try_store(
                lambda: self._store.create(title), "create note"
            )
            if note_id is None:
                return
        if (
            self._try_store(
                lambda: self._store.update(note_id, title, body),
                "save note",
            )
            is None
        ):
            return
        self._refresh_list(select_id=note_id)
        self._load_selected()
        self._set_status("Note saved", error=False)

    def _dictate(self) -> None:
        # Bind the recording to its originating note: the service pumps UI
        # events while recording, so the user may switch notes mid-speech.
        origin_id = self._current_id()
        origin_pos = self._body.textCursor().position()
        self._set_status("Listening…", error=False)
        text = self._on_dictate()
        if not text:
            error = None
            if self._on_dictate_error is not None:
                try:
                    error = self._on_dictate_error()
                except Exception:  # noqa: BLE001 - status is best effort
                    error = None
            if error:
                self._set_status(f"Dictation failed: {error}", error=True)
            else:
                self._set_status("Dictation cancelled", error=False)
            return
        if origin_id and origin_id != self._current_id():
            # Selection moved mid-recording: flush the note being left and
            # return to the origin so speech lands where dictation began.
            # (If the origin was deleted meanwhile, fall through to the
            # current note rather than losing the transcript.)
            self.flush()
            self._select_note(origin_id)
        if origin_id and origin_id == self._current_id():
            cursor = self._body.textCursor()
            # Qt cursor positions count UTF-16 code units, not Python
            # code points: clamp in Qt coordinates so emoji before the
            # cursor cannot drag the insertion point into earlier text.
            limit = max(0, self._body.document().characterCount() - 1)
            cursor.setPosition(min(origin_pos, limit))
            self._body.setTextCursor(cursor)
        self._insert_dictated(text)
        self._set_status(
            f"Inserted {len(text)} characters", error=False
        )

    def _select_note(self, note_id: str) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == note_id:
                self._list.setCurrentItem(item)
                return

    def _insert_dictated(self, text: str) -> None:
        # Smart spacing: dictated text lands mid-sentence when the cursor
        # sits inside existing text, so pad with spaces unless already at
        # a word boundary ("hello|world" -> "hello spoken world").
        cursor = self._body.textCursor()
        doc = self._body.document()
        pos = cursor.position()
        before = str(doc.characterAt(pos - 1)) if pos > 0 else ""
        after = str(doc.characterAt(pos)) if pos < doc.characterCount() else ""
        prefix = " " if before and not before.isspace() else ""
        suffix = " " if after and not after.isspace() else ""
        cursor.insertText(f"{prefix}{text}{suffix}")
        self._body.setTextCursor(cursor)

    def _set_status(self, text: str, *, error: bool) -> None:
        self._status.setProperty("role", "error" if error else "hint")
        style = self._status.style()
        if style is not None:
            style.unpolish(self._status)
            style.polish(self._status)
        self._status.setText(text)

    def _try_store(self, action: Callable[[], object], what: str) -> object:
        """Run a NoteStore write; on OSError report red and return None.

        Autosave/flush/quit paths must never raise (a read-only disk would
        otherwise break window close), so every store mutation routes here.
        """
        try:
            return action()
        except OSError as exc:
            self._set_status(f"Could not {what}: {exc}", error=True)
            return None
