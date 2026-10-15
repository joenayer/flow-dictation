"""Offscreen QApplication smoke tests for ScratchpadWindow."""

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

from flow.ui.scratchpad import ScratchpadWindow  # noqa: E402


class FakeStore:
    """Minimal in-memory stand-in for NoteStore."""

    def __init__(self) -> None:
        self.notes: list[dict] = []
        self._n = 0

    def create(self, title: str) -> str:
        self._n += 1
        note_id = str(self._n)
        self.notes.append({"id": note_id, "ts": float(self._n), "title": title, "body": ""})
        return note_id

    def get(self, id: str) -> dict | None:
        for note in self.notes:
            if note["id"] == id:
                return dict(note)
        return None

    def list_all(self) -> list[dict]:
        return [dict(n) for n in sorted(self.notes, key=lambda n: n["ts"], reverse=True)]

    def update(self, id: str, title: str, body: str) -> bool:
        for note in self.notes:
            if note["id"] == id:
                note["title"] = title
                note["body"] = body
                return True
        return False

    def delete(self, id: str) -> bool:
        for index, note in enumerate(self.notes):
            if note["id"] == id:
                del self.notes[index]
                return True
        return False


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["flow-linux-scratchpad"])
    return app


def test_dictate_appends_at_cursor(qapp: QApplication) -> None:
    window = ScratchpadWindow(FakeStore(), on_dictate=lambda: "hello")
    assert window._body.toPlainText() == ""
    window._dictate_btn.click()
    assert window._body.toPlainText() == "hello"


def test_dictate_none_is_noop(qapp: QApplication) -> None:
    window = ScratchpadWindow(FakeStore(), on_dictate=lambda: None)
    window._body.setPlainText("keep")
    window._dictate_btn.click()
    assert window._body.toPlainText() == "keep"


def test_failed_undo_keeps_body_for_retry(qapp, tmp_path) -> None:
    from flow.notes import NoteStore

    store_dir = tmp_path / "notes"
    store_dir.mkdir()
    store = NoteStore(str(store_dir / "notes.json"))
    note_id = store.create("Title")
    store.update(note_id, "Title", "irrecoverable body")

    window = ScratchpadWindow(store, on_dictate=lambda: None)
    window._list.setCurrentRow(0)
    assert window._body.toPlainText() == "irrecoverable body"
    window._delete_btn.click()
    assert window._trash == {"title": "Title", "body": "irrecoverable body"}

    os.chmod(store_dir, 0o500)
    try:
        window._undo_btn.click()  # restore fails: write error shown
    finally:
        os.chmod(store_dir, 0o700)
    assert "Could not restore note" in window._status.text()
    assert window._trash == {"title": "Title", "body": "irrecoverable body"}
    assert window._undo_btn.isEnabled()

    window._undo_btn.click()  # retry after permissions heal
    assert window._trash is None
    assert store.list_all()[0]["body"] == "irrecoverable body"


def test_dictate_at_end_after_emoji(qapp, tmp_path) -> None:
    from flow.notes import NoteStore

    store = NoteStore(str(tmp_path / "notes.json"))
    note_id = store.create("Emoji")
    store.update(note_id, "Emoji", "😀😀 end")

    window = ScratchpadWindow(store, on_dictate=lambda: "spoken")
    window._list.setCurrentRow(0)
    cursor = window._body.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    window._body.setTextCursor(cursor)
    window._dictate_btn.click()
    assert window._body.toPlainText() == "😀😀 end spoken"
