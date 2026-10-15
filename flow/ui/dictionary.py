"""Custom vocabulary dialog (and embeddable widget). Offscreen-safe.

Integrator: construct ``DictionaryDialog(store, on_save=...)`` where
``on_save`` reloads the STT engine after the store is written so
``{models_dir}/hotwords.txt`` is picked up on the next ``load()``.
``DictionaryWidget`` holds the same UI for embedding in the main window.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from ..dictionary import DictionaryStore, normalize_phrase

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QDialogButtonBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    _HAS_QT = True
except ImportError:  # pragma: no cover - optional for headless unit tests
    _HAS_QT = False
    QDialog = object  # type: ignore[misc, assignment]
    QWidget = object  # type: ignore[misc, assignment]

HINT_TEXT = (
    "Words here are boosted during transcription. "
    "Hotwords apply to the Parakeet engine; Moonshine ignores them."
)


class DictionaryWidget(QWidget):
    """Dictionary list + add/remove UI, embeddable in any window."""

    def __init__(self, store: DictionaryStore, parent: QWidget | None = None) -> None:
        if not _HAS_QT:
            raise RuntimeError("PySide6 is required for DictionaryWidget")
        super().__init__(parent)
        self._store = store
        self._saved_words = store.words()
        self._applied_words = store.words()
        self._saving = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        hint = QLabel(HINT_TEXT)
        hint.setProperty("role", "hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._list = QListWidget()
        self._list.addItems(store.words())
        root.addWidget(self._list, 1)

        self._empty = QLabel(
            "No custom words yet. Add names and jargon you dictate often."
        )
        self._empty.setProperty("role", "empty")
        self._empty.setWordWrap(True)
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setVisible(self._list.count() == 0)
        root.addWidget(self._empty)

        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self._edit = QLineEdit()
        self._edit.setPlaceholderText("Add word or phrase (1–5 words)")
        self._edit.returnPressed.connect(self._add)
        add_row.addWidget(self._edit, 1)
        self._add_btn = QPushButton("Add")
        self._add_btn.clicked.connect(self._add)
        add_row.addWidget(self._add_btn)
        root.addLayout(add_row)

        self._remove_btn = QPushButton("Remove selected")
        self._remove_btn.clicked.connect(self._remove)
        root.addWidget(self._remove_btn)

        self._status = QLabel("")
        self._status.setProperty("role", "confirm")
        root.addWidget(self._status)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setProperty("role", "error")
        root.addWidget(self._error)

        load_error = getattr(store, "load_error", None)
        if load_error:
            self._error.setText(str(load_error))

    def is_dirty(self) -> bool:
        """True when add/remove edits are not yet saved to disk."""
        return self._store.words() != self._saved_words

    def is_applied(self) -> bool:
        """True when the running engine has the current words."""
        return self._store.words() == self._applied_words

    def flush(self) -> None:
        """Persist unsaved edits without an engine reload (quit path)."""
        if self.is_dirty():
            self._store.save()
            self._saved_words = self._store.words()
            self._mark_dirty()  # now "saved, not yet applied"

    def _refresh_list(self) -> None:
        self._list.clear()
        self._list.addItems(self._store.words())
        self._empty.setVisible(self._list.count() == 0)

    def _mark_dirty(self) -> None:
        if self.is_dirty():
            self._status.setText("Unsaved changes — press Save to apply")
        elif not self.is_applied():
            self._status.setText(
                "Saved — press Save to apply to the speech engine"
            )
        else:
            self._status.setText("")

    def _add(self) -> None:
        raw = self._edit.text()
        if normalize_phrase(raw) is None:
            self._error.setText(
                "invalid phrase: 1–5 words, letters/apostrophes/hyphens only"
            )
            return
        if not self._store.add(raw):
            self._error.setText("already in dictionary or invalid")
            return
        self._error.setText("")
        self._edit.clear()
        self._refresh_list()
        self._mark_dirty()

    def _remove(self) -> None:
        item = self._list.currentItem()
        if item is None:
            self._error.setText("select a word to remove")
            return
        self._store.remove(item.text())
        self._error.setText("")
        self._refresh_list()
        self._mark_dirty()

    def save_with_feedback(
        self, on_save: Callable[[DictionaryStore], None] | None
    ) -> bool:
        """Validate, persist, and run ``on_save`` (engine reload).

        Shows progress while the (potentially slow) reload runs off the
        GUI thread with events pumped, and surfaces failures instead of
        closing. Returns True on success.
        """
        if self._saving:
            return False  # reentry (double Save click): first run wins
        for phrase in self._store.words():
            if normalize_phrase(phrase) is None:
                self._error.setText(f"invalid phrase: {phrase}")
                return False
        self._error.setText("")
        self._saving = True
        self._set_controls_enabled(False)
        self._status.setText("Saving… reloading speech engine")
        QApplication.processEvents()
        try:
            self._store.save()
            if on_save is not None:
                outcome: dict = {}

                def _reload() -> None:
                    try:
                        on_save(self._store)
                    except Exception as exc:  # noqa: BLE001 - below
                        outcome["error"] = exc

                worker = threading.Thread(target=_reload, daemon=True)
                worker.start()
                while worker.is_alive():
                    QApplication.processEvents()
                    time.sleep(0.01)
                worker.join()
                if "error" in outcome:
                    raise outcome["error"]
        except Exception as exc:  # noqa: BLE001 - surfaced in the UI
            self._status.setText("")
            self._error.setText(f"engine reload failed: {exc}")
            return False
        finally:
            self._saving = False
            self._set_controls_enabled(True)
        self._saved_words = self._store.words()
        self._applied_words = self._store.words()
        self._status.setText("Dictionary saved — engine reloaded")
        return True

    def _set_controls_enabled(self, enabled: bool) -> None:
        self._edit.setEnabled(enabled)
        self._add_btn.setEnabled(enabled)
        self._remove_btn.setEnabled(enabled)


class DictionaryDialog(QDialog):
    """QListWidget + add line + Remove + Save. Validates before save."""

    def __init__(
        self,
        store: DictionaryStore,
        on_save: Callable[[DictionaryStore], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        if not _HAS_QT:
            raise RuntimeError("PySide6 is required for DictionaryDialog")
        super().__init__(parent)
        self._store = store
        self._on_save = on_save

        from .theme import window_icon

        self.setWindowTitle("flow-linux dictionary")
        self.setModal(True)
        self.setWindowIcon(window_icon())
        self.setProperty("flowWindow", True)
        self.setMinimumSize(440, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        title = QLabel("Dictionary")
        title.setProperty("role", "title")
        root.addWidget(title)

        self._form = DictionaryWidget(store, self)
        root.addWidget(self._form, 1)
        # Backward-compatible attribute aliases (see DictionaryWidget).
        self._list = self._form._list
        self._edit = self._form._edit
        self._add_btn = self._form._add_btn
        self._remove_btn = self._form._remove_btn
        self._status = self._form._status
        self._error = self._form._error
        self._empty = self._form._empty

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self._save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if self._save_btn is not None:
            self._save_btn.setProperty("primary", True)
        root.addWidget(buttons)

    def _refresh_list(self) -> None:
        self._form._refresh_list()

    def _add(self) -> None:
        self._form._add()

    def _remove(self) -> None:
        self._form._remove()

    def _save(self) -> None:
        if self._form.save_with_feedback(self._on_save):
            self.accept()
