"""Offscreen tests for UI edges: Esc delivery, empty states, capture, deletes."""

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

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from flow.config import Settings  # noqa: E402
from flow.dictionary import DictionaryStore  # noqa: E402
from flow.events import SessionState  # noqa: E402
from flow.ui.dictionary import DictionaryDialog  # noqa: E402
from flow.ui.history_window import HistoryWindow  # noqa: E402
from flow.ui.main_window import FlowMainWindow  # noqa: E402
from flow.ui.pill import QtPill  # noqa: E402
from flow.ui.scratchpad import ScratchpadWindow  # noqa: E402
from flow.ui.settings import SettingsDialog  # noqa: E402


class FakeHistory:
    def __init__(self, entries=None):
        self.entries = list(entries or [])

    def all(self):
        return list(self.entries)

    def search(self, query):
        needle = query.casefold()
        return [
            e for e in self.entries if needle in str(e.get("text") or "").casefold()
        ]


class FakeNotes:
    def __init__(self):
        self.notes: list[dict] = []
        self._n = 0

    def create(self, title):
        self._n += 1
        note_id = str(self._n)
        self.notes.append(
            {"id": note_id, "ts": float(self._n), "title": title, "body": ""}
        )
        return note_id

    def get(self, id):
        for note in self.notes:
            if note["id"] == id:
                return dict(note)
        return None

    def list_all(self):
        return [dict(n) for n in sorted(self.notes, key=lambda n: n["ts"], reverse=True)]

    def update(self, id, title, body):
        for note in self.notes:
            if note["id"] == id:
                note["title"] = title
                note["body"] = body
                return True
        return False

    def delete(self, id):
        for i, note in enumerate(self.notes):
            if note["id"] == id:
                del self.notes[i]
                return True
        return False


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["flow-linux-ui-extras"])
    return app


# -- Esc delivery (real key events, not direct method calls) ----------------


def test_history_escape_delivered_from_search(qapp) -> None:
    window = HistoryWindow(FakeHistory([]), copy_fn=lambda text: None)
    try:
        window.show()
        window._search.setFocus()
        QTest.keyClick(window._search, Qt.Key.Key_Escape)
        assert not window.isVisible()
    finally:
        window.close()


def test_notes_escape_delivered_from_body(qapp) -> None:
    window = ScratchpadWindow(FakeNotes(), on_dictate=lambda: None)
    try:
        window.show()
        window._body.setFocus()
        QTest.keyClick(window._body, Qt.Key.Key_Escape)
        assert not window.isVisible()
    finally:
        window.close()


def test_settings_dialog_escape_rejects(qapp) -> None:
    dlg = SettingsDialog(Settings())
    try:
        dlg.show()
        QTest.keyClick(dlg, Qt.Key.Key_Escape)
        assert dlg.result() == QDialog.DialogCode.Rejected
        assert not dlg.isVisible()
    finally:
        dlg.close()


def test_dictionary_dialog_escape_rejects(qapp, tmp_path) -> None:
    store = DictionaryStore(str(tmp_path / "hotwords.txt"))
    dlg = DictionaryDialog(store)
    try:
        dlg.show()
        QTest.keyClick(dlg, Qt.Key.Key_Escape)
        assert dlg.result() == QDialog.DialogCode.Rejected
        assert not dlg.isVisible()
    finally:
        dlg.close()


def test_embedded_page_escape_keeps_main_open(qapp, tmp_path) -> None:
    history = FakeHistory([{"id": "1", "ts": 1.0, "text": "hello"}])
    notes = FakeNotes()
    notes.create("One")
    dictionary = DictionaryStore(str(tmp_path / "hotwords.txt"))
    window = FlowMainWindow(
        history_store=history,
        note_store=notes,
        dict_store=dictionary,
        on_dictate=lambda: None,
    )
    try:
        window.show_page("history")
        QTest.keyClick(window._history_win._search, Qt.Key.Key_Escape)
        assert window.isVisible()
        window.show_page("notes")
        QTest.keyClick(window._notes_win._body, Qt.Key.Key_Escape)
        assert window.isVisible()
    finally:
        window.close()


# -- history copy confirmation + empty states --------------------------------


def test_history_double_click_copies_and_confirms(qapp) -> None:
    copied: list[str] = []
    store = FakeHistory([{"id": "1", "ts": 1.0, "text": "spoken words"}])
    window = HistoryWindow(store, copy_fn=copied.append)
    try:
        item = window._list.item(0)
        window._list.itemDoubleClicked.emit(item)
        assert copied == ["spoken words"]
        assert window._status.text() == "Copied to clipboard"
    finally:
        window.close()


def test_history_status_clears_on_timer(qapp) -> None:
    store = FakeHistory([{"id": "1", "ts": 1.0, "text": "hello"}])
    window = HistoryWindow(store, copy_fn=lambda text: None)
    try:
        assert window._status_timer.isSingleShot()
        window._list.setCurrentRow(0)
        window._copy_btn.click()
        assert window._status_timer.isActive()
        window._status_timer.timeout.emit()
        assert window._status.text() == ""
    finally:
        window.close()


def test_history_no_match_empty_text(qapp) -> None:
    store = FakeHistory([{"id": "1", "ts": 1.0, "text": "alpha"}])
    window = HistoryWindow(store, copy_fn=lambda text: None)
    try:
        window._search.setText("zzz-no-such-words")
        assert window._list.count() == 0
        assert window._empty.text().startswith("No matches for")
        assert "zzz-no-such-words" in window._empty.text()
        window._search.setText("")
        assert window._list.count() == 1
        assert window._empty.text().startswith("Nothing here yet")
    finally:
        window.close()


# -- dictionary empty state --------------------------------------------------


def test_dictionary_empty_state_toggles(qapp, tmp_path) -> None:
    store = DictionaryStore(str(tmp_path / "hotwords.txt"))
    dlg = DictionaryDialog(store)
    try:
        dlg.show()
        assert dlg._empty.isVisible()
        dlg._edit.setText("custom phrase")
        dlg._add_btn.click()
        assert dlg._empty.isHidden()
        dlg._list.setCurrentRow(0)
        dlg._remove_btn.click()
        assert dlg._empty.isVisible()
    finally:
        dlg.close()


# -- notes delete + dictate-after-switch -------------------------------------


def test_notes_delete_updates_list(qapp) -> None:
    store = FakeNotes()
    store.create("One")
    store.create("Two")
    window = ScratchpadWindow(store, on_dictate=lambda: None)
    try:
        assert window._list.count() == 2
        window._list.setCurrentRow(0)
        doomed = window._current_id()
        window._delete_btn.click()
        assert store.get(doomed) is None
        assert window._list.count() == 1
        window._delete_btn.click()
        assert window._list.count() == 0
        assert window._title.text() == ""
        assert window._body.toPlainText() == ""
    finally:
        window.close()


def test_notes_dictated_text_autosaved_on_switch(qapp) -> None:
    store = FakeNotes()
    store.create("One")
    store.create("Two")
    window = ScratchpadWindow(store, on_dictate=lambda: "spoken")
    try:
        window._list.setCurrentRow(1)
        second_id = window._current_id()
        window._dictate_btn.click()
        assert "spoken" in window._body.toPlainText()
        window._list.setCurrentRow(0)
        assert "spoken" in store.get(second_id)["body"]
    finally:
        window.close()


def test_notes_dictate_inserts_with_word_spacing(qapp) -> None:
    store = FakeNotes()
    store.create("One")
    window = ScratchpadWindow(store, on_dictate=lambda: "spoken")
    try:
        window._body.setPlainText("hello world")
        cursor = window._body.textCursor()
        cursor.setPosition(5)  # between "hello" and " world"
        window._body.setTextCursor(cursor)
        window._dictate_btn.click()
        assert window._body.toPlainText() == "hello spoken world"
    finally:
        window.close()


def test_notes_dictate_at_empty_body_has_no_padding(qapp) -> None:
    store = FakeNotes()
    store.create("One")
    window = ScratchpadWindow(store, on_dictate=lambda: "spoken")
    try:
        assert window._body.toPlainText() == ""
        window._dictate_btn.click()
        assert window._body.toPlainText() == "spoken"
    finally:
        window.close()


def test_notes_undo_delete_keeps_other_draft(qapp) -> None:
    store = FakeNotes()
    store.create("A")
    store.create("B")
    window = ScratchpadWindow(store, on_dictate=lambda: None)
    try:
        window._list.setCurrentRow(1)  # A (newest-first: B, A)
        assert window._current_id() == "1"
        window._delete_btn.click()
        # B is now selected; edit it, then undo before autosave fires.
        window._body.setPlainText("original B UNSAVED")
        window._undo_btn.click()
        assert window._list.count() == 2
        assert store.get("2")["body"] == "original B UNSAVED"
    finally:
        window.close()


def test_notes_new_adopts_first_draft(qapp) -> None:
    store = FakeNotes()
    window = ScratchpadWindow(store, on_dictate=lambda: None)
    try:
        assert window._list.count() == 0
        window._body.setPlainText("first draft")
        window._new_btn.click()
        bodies = sorted(n["body"] for n in store.notes)
        assert bodies == ["", "first draft"]
    finally:
        window.close()


def test_notes_dictate_lands_in_origin_note(qapp) -> None:
    store = FakeNotes()
    store.create("A")
    store.create("B")
    window = ScratchpadWindow(store, on_dictate=lambda: "spoken")
    try:
        window._list.setCurrentRow(1)  # A
        origin = window._current_id()

        def hook() -> str:
            window._list.setCurrentRow(0)  # user switches to B mid-speech
            return "spoken"

        window._on_dictate = hook
        window._dictate_btn.click()
        assert window._current_id() == origin  # returned to A
        assert "spoken" in store.get(origin)["body"] or "spoken" in (
            window._body.toPlainText()
        )
        other = "2" if origin == "1" else "1"
        assert "spoken" not in (store.get(other)["body"] or "")
    finally:
        window.close()


def test_notes_dictate_failure_shows_status(qapp) -> None:
    store = FakeNotes()
    store.create("A")
    window = ScratchpadWindow(
        store,
        on_dictate=lambda: None,
        on_dictate_error=lambda: "Could not open microphone: boom",
    )
    try:
        window._dictate_btn.click()
        assert "Could not open microphone" in window._status.text()
        assert window._status.property("role") == "error"
    finally:
        window.close()


def test_notes_unwritable_disk_reports_without_raising(
    qapp, tmp_path
) -> None:
    import os

    from flow.notes import NoteStore

    store = NoteStore(str(tmp_path / "notes.json"))
    store.create("A")
    window = ScratchpadWindow(store, on_dictate=lambda: None)
    try:
        os.chmod(tmp_path, 0o500)
        try:
            window._body.setPlainText("doomed draft")
            window.flush()  # quit path: must never raise
            window._save_btn.click()
            window._new_btn.click()
            window._delete_btn.click()
        finally:
            os.chmod(tmp_path, 0o700)
        assert "Could not" in window._status.text()
        assert window._status.property("role") == "error"
    finally:
        window.close()


def test_notes_dictate_cancel_shows_cancelled(qapp) -> None:
    store = FakeNotes()
    store.create("A")
    window = ScratchpadWindow(store, on_dictate=lambda: None)
    try:
        window._dictate_btn.click()
        assert window._status.text() == "Dictation cancelled"
    finally:
        window.close()


def test_notes_service_dictate_binds_origin_and_stays_alive(
    qapp, tmp_path, monkeypatch
) -> None:
    """Mid-recording note switch + slow transcription stay correct."""
    import time
    from types import SimpleNamespace

    import numpy as np
    from PySide6.QtCore import QTimer

    from flow.dictionary import DictionaryStore
    from flow.flowd import FlowService
    from flow.history import TranscriptStore
    from flow.notes import NoteStore

    svc = FlowService(
        Settings(), history_path=str(tmp_path / "history.jsonl")
    )

    class SlowCapture:
        def start(self, cb) -> None:
            pass

        def stop(self):
            return np.ones(8000, dtype=np.float32)

    class QuickVAD:
        def reset(self) -> None:
            self.start = time.monotonic()

        def feed(self, chunk) -> None:
            pass

        def should_auto_stop(self) -> bool:
            return time.monotonic() - self.start > 0.18

    observed: dict = {}

    class SlowEngine:
        def transcribe(self, samples):
            observed["state"] = str(svc.state)
            before = len(ticks)
            time.sleep(0.35)
            observed["ticks"] = len(ticks) - before
            return SimpleNamespace(text="spoken for A")

    svc._vad = QuickVAD()
    svc._engine = SlowEngine()
    notes = NoteStore(str(tmp_path / "notes.json"))
    window = FlowMainWindow(
        history_store=TranscriptStore(str(tmp_path / "history.jsonl")),
        note_store=notes,
        dict_store=DictionaryStore(str(tmp_path / "hotwords.txt")),
        on_dictate=svc.scratchpad_dictate,
        on_dictate_error=lambda: svc.last_dictate_error,
    )
    try:
        svc.bus.on("state", window.set_state)
        a_id = notes.create("A")
        b_id = notes.create("B")
        notes.update(b_id, "B", "existing B")
        page = window._notes_win
        page._refresh_list(select_id=a_id)
        window.show_page("notes")
        ticks: list = []
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: ticks.append(time.monotonic()))
        heartbeat.start()

        def switch_note() -> None:
            for row in range(page._list.count()):
                item = page._list.item(row)
                if item.data(Qt.ItemDataRole.UserRole) == b_id:
                    rect = page._list.visualItemRect(item)
                    QTest.mouseClick(
                        page._list.viewport(),
                        Qt.MouseButton.LeftButton,
                        pos=rect.center(),
                    )

        try:
            QTimer.singleShot(60, switch_note)
            monkeypatch.setattr(
                "flow.flowd.default_capture", SlowCapture
            )
            page._dictate_btn.click()
        finally:
            heartbeat.stop()
        page.flush()
        # Speech landed in the originating note, not the switched-to one.
        assert "spoken for a" in notes.get(a_id)["body"].lower()
        assert notes.get(b_id)["body"] == "existing B"
        # Transcription ran off the GUI thread with correct busy state.
        assert observed["ticks"] > 0
        assert observed["state"] == "SessionState.PROCESSING"
        assert svc.last_dictate_error is None
    finally:
        window.close()


# -- shortcut capture edges --------------------------------------------------


def test_capture_second_click_cancels(qapp) -> None:
    dlg = SettingsDialog(Settings())
    try:
        form = dlg._form
        btn = form._capture_btns["ptt_shortcut"]
        btn.click()
        assert form._capturing == "ptt_shortcut"
        assert btn.text() == "Press keys…"
        btn.click()
        assert form._capturing is None
        assert btn.text() == "Record"
    finally:
        dlg.close()


def test_capture_modifier_press_keeps_waiting(qapp) -> None:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    dlg = SettingsDialog(Settings())
    try:
        form = dlg._form
        btn = form._capture_btns["ptt_shortcut"]
        form._start_capture("ptt_shortcut")
        event = QKeyEvent(
            QEvent.Type.KeyPress,
            Qt.Key.Key_Alt,
            Qt.KeyboardModifier.AltModifier,
        )
        assert form.eventFilter(btn, event) is True
        assert form._capturing == "ptt_shortcut"
        form._cancel_capture()
    finally:
        dlg.close()


def test_capture_ctrl_super_d_end_to_end(qapp) -> None:
    dlg = SettingsDialog(Settings())
    try:
        dlg.show()
        form = dlg._form
        btn = form._capture_btns["command_shortcut"]
        btn.click()
        QTest.keyClick(
            btn,
            Qt.Key.Key_D,
            Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.MetaModifier,
        )
        assert form._editors["command_shortcut"].text() == "Ctrl+Super+D"
        assert form.is_valid()
        assert btn.text() == "Record"
    finally:
        dlg.close()


# -- pill transient cancellation ---------------------------------------------


def test_pill_state_change_cancels_transient(qapp) -> None:
    pill = QtPill()
    try:
        pill.set_state(SessionState.RECORDING)
        pill.show_message("switching engine")
        assert pill._transient
        assert pill._dismiss.isActive()
        pill.set_state(SessionState.PROCESSING)
        assert not pill._transient
        assert not pill._dismiss.isActive()
        assert pill._label.text() == "Writing…"
        pill._dismiss_message()  # no-op once the transient is gone
        assert pill.isVisible()
    finally:
        pill.close()


# -- main window navigation sync ---------------------------------------------


def _main_window(tmp_path, **kwargs):
    history = FakeHistory([{"id": "1", "ts": 1.0, "text": "hello"}])
    notes = FakeNotes()
    notes.create("One")
    dictionary = DictionaryStore(str(tmp_path / "hotwords.txt"))
    kwargs.setdefault("history_store", history)
    kwargs.setdefault("note_store", notes)
    kwargs.setdefault("dict_store", dictionary)
    kwargs.setdefault("on_dictate", lambda: None)
    return FlowMainWindow(**kwargs)


def test_nav_click_switches_stack(qapp, tmp_path) -> None:
    window = _main_window(tmp_path)
    try:
        window._nav.setCurrentRow(3)
        assert window._stack.currentIndex() == window._index["dictionary"]
        window.show_page("notes")
        assert window._nav.currentRow() == 2
        assert window._stack.currentIndex() == window._index["notes"]
    finally:
        window.close()


def test_show_page_reshows_hidden_window(qapp, tmp_path) -> None:
    window = _main_window(tmp_path)
    try:
        window.show_page("dictate")
        assert window.isVisible()
        window.close()
        assert not window.isVisible()
        window.show_page("settings")
        assert window.isVisible()
        assert window._stack.currentIndex() == window._index["settings"]
    finally:
        window.close()


def test_refresh_settings_syncs_form_and_hints(qapp, tmp_path) -> None:
    window = _main_window(tmp_path)
    try:
        window.refresh_settings(
            Settings(ptt_shortcut="Alt+Q", engine="moonshine")
        )
        form = window._settings_form
        assert form._editors["ptt_shortcut"].text() == "Alt+Q"
        assert form._engine.currentText() == "moonshine"
        assert "Alt+Q" in window._dictate._hint.text()
    finally:
        window.close()


def test_side_state_tracks_processing(qapp, tmp_path) -> None:
    window = _main_window(tmp_path)
    try:
        window.set_state(SessionState.PROCESSING)
        assert window._side_state.text() == "Writing…"
        window.set_state(SessionState.IDLE)
        assert window._side_state.text() == "Ready"
    finally:
        window.close()


# -- layout regression: no squeezed controls, no overlapping rows ------------


def _process_events(qapp, rounds: int = 5) -> None:
    for _ in range(rounds):
        qapp.processEvents()
    QTest.qWait(50)
    qapp.processEvents()


def test_settings_controls_keep_full_height(qapp, tmp_path) -> None:
    """Editors + Record buttons never squeeze below sizeHint (smeared text)."""
    window = _main_window(tmp_path)
    try:
        window.resize(1060, 660)
        window.show_page("settings")
        _process_events(qapp)
        form = window._settings_form
        for field, editor in form._editors.items():
            assert editor.height() >= editor.sizeHint().height(), field
            button = form._capture_btns[field]
            assert button.height() >= button.sizeHint().height(), field
    finally:
        window.close()


def test_settings_controls_keep_full_height_at_min_size(qapp, tmp_path) -> None:
    window = _main_window(tmp_path)
    try:
        window.resize(window.minimumSize())
        window.show_page("settings")
        _process_events(qapp)
        form = window._settings_form
        for field, editor in form._editors.items():
            assert editor.height() >= editor.sizeHint().height(), field
            button = form._capture_btns[field]
            assert button.height() >= button.sizeHint().height(), field
    finally:
        window.close()


def _assert_rows_not_overlapping(window, page_key: str) -> None:
    if page_key == "notes":
        lst = window._notes_win._list
    else:
        lst = window._history_win._list
    assert lst.count() >= 2
    previous_bottom = None
    for row in range(lst.count()):
        rect = lst.visualRect(lst.indexFromItem(lst.item(row)))
        assert rect.height() >= lst.sizeHintForRow(row), (page_key, row)
        if previous_bottom is not None:
            assert rect.top() >= previous_bottom, (page_key, row)
        previous_bottom = rect.bottom()


def test_notes_rows_do_not_overlap_after_show(qapp, tmp_path) -> None:
    window = _main_window(tmp_path)
    try:
        window._notes_win._store.create("Two")
        window._notes_win._refresh_list()
        window.resize(1060, 660)
        window.show_page("notes")
        _process_events(qapp)
        _assert_rows_not_overlapping(window, "notes")
    finally:
        window.close()


def test_history_rows_do_not_overlap_after_show(qapp, tmp_path) -> None:
    history = FakeHistory(
        [
            {"id": "1", "ts": 1.0, "text": "alpha"},
            {"id": "2", "ts": 2.0, "text": "bravo"},
        ]
    )
    notes = FakeNotes()
    notes.create("One")
    dictionary = DictionaryStore(str(tmp_path / "hotwords.txt"))
    window = FlowMainWindow(
        history_store=history,
        note_store=notes,
        dict_store=dictionary,
        on_dictate=lambda: None,
    )
    try:
        window.resize(1060, 660)
        window.show_page("history")
        _process_events(qapp)
        _assert_rows_not_overlapping(window, "history")
    finally:
        window.close()


# -- package exports ---------------------------------------------------------


def test_ui_package_exports() -> None:
    import flow.ui as ui

    for name in (
        "FlowMainWindow",
        "DictatePage",
        "HistoryWindow",
        "ScratchpadWindow",
        "SettingsDialog",
        "SettingsWidget",
        "DictionaryDialog",
        "DictionaryWidget",
        "PillController",
        "QtPill",
        "TrayIcon",
        "validate_shortcut",
    ):
        assert name in ui.__all__
        assert getattr(ui, name) is not None
