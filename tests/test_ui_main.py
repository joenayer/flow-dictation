"""Offscreen tests for the integrated main window and UI upgrades."""

from __future__ import annotations

import importlib.util
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 not installed",
)
pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from flow.config import Settings  # noqa: E402
from flow.dictionary import DictionaryStore  # noqa: E402
from flow.events import SessionState  # noqa: E402
from flow.ui.dictionary import DictionaryDialog  # noqa: E402
from flow.ui.history_window import HistoryWindow  # noqa: E402
from flow.ui.main_window import PAGES, FlowMainWindow  # noqa: E402
from flow.ui.pill import MESSAGE_DISMISS_MS, QtPill  # noqa: E402
from flow.ui.scratchpad import ScratchpadWindow  # noqa: E402
from flow.ui.settings import (  # noqa: E402
    SettingsDialog,
    combo_spec_from_qt,
)


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
        app = QApplication(["flow-linux-ui-main"])
    return app


@pytest.fixture()
def stores(tmp_path):
    history = FakeHistory(
        [
            {"id": "1", "ts": 1_700_000_000.0, "text": "alpha utterance"},
            {"id": "2", "ts": 1_700_000_060.0, "text": "bravo note"},
        ]
    )
    notes = FakeNotes()
    notes.create("First")
    dictionary = DictionaryStore(str(tmp_path / "hotwords.txt"))
    return history, notes, dictionary


def _main(qapp, stores, **kwargs):
    history, notes, dictionary = stores
    kwargs.setdefault("history_store", history)
    kwargs.setdefault("note_store", notes)
    kwargs.setdefault("dict_store", dictionary)
    kwargs.setdefault("on_dictate", lambda: None)
    return FlowMainWindow(**kwargs)


# -- main window navigation -------------------------------------------


def test_main_window_has_all_pages(qapp, stores) -> None:
    window = _main(qapp, stores)
    try:
        assert window._nav.count() == len(PAGES) == 5
        assert window._stack.count() == 5
        for key, _label in PAGES:
            window.show_page(key)
            assert window._stack.currentIndex() == window._index[key]
            assert window.isVisible()
    finally:
        window.close()


def test_show_page_unknown_key_falls_back_to_dictate(qapp, stores) -> None:
    window = _main(qapp, stores)
    try:
        window.show_page("nope")
        assert window._stack.currentIndex() == window._index["dictate"]
    finally:
        window.close()


def test_taskbar_icons_present(qapp, stores) -> None:
    history, notes, dictionary = stores
    window = _main(qapp, stores)
    try:
        assert not window.windowIcon().isNull()
        assert not window._history_win.windowIcon().isNull()
        assert not window._notes_win.windowIcon().isNull()
        assert not SettingsDialog(Settings()).windowIcon().isNull()
        assert not DictionaryDialog(dictionary).windowIcon().isNull()
        assert not HistoryWindow(history, lambda text: None).windowIcon().isNull()
    finally:
        window.close()


# -- dictate page ------------------------------------------------------


def test_dictate_state_level_and_transcript(qapp, stores) -> None:
    window = _main(qapp, stores)
    try:
        window.set_state(SessionState.RECORDING)
        assert window._dictate._status.text() == "Listening…"
        assert window._side_state.text() == "Listening…"
        window.set_level(3000.0)
        window._dictate._tick()
        window.set_state(SessionState.PROCESSING)
        assert window._dictate._status.text() == "Writing…"
        window.on_transcript("hello world")
        assert window._dictate._last.toPlainText() == "hello world"
        assert window._dictate.reviewed_text() == "hello world"
        window.set_state(SessionState.IDLE)
        assert window._dictate._status.text() == "Ready"
    finally:
        window.close()


def test_on_transcript_refreshes_history_page(qapp, stores) -> None:
    history, _notes, _dictionary = stores
    window = _main(qapp, stores)
    try:
        assert window._history_win._list.count() == 2
        history.entries.insert(
            0, {"id": "3", "ts": 1_700_000_120.0, "text": "fresh words"}
        )
        window.on_transcript("fresh words")
        assert window._history_win._list.count() == 3
    finally:
        window.close()


def test_dictate_shortcut_hint_tracks_settings(qapp, stores) -> None:
    window = _main(qapp, stores)
    try:
        assert "Alt+W" in window._dictate._hint.text()
        window.refresh_settings(Settings(ptt_shortcut="Ctrl+Super+d"))
        assert "Ctrl+Super+d" in window._dictate._hint.text()
    finally:
        window.close()


# -- settings page: live save ------------------------------------------


def test_settings_page_save_calls_hook(qapp, stores) -> None:
    saved: list[Settings] = []
    window = _main(qapp, stores, on_save_settings=saved.append)
    try:
        window.show_page("settings")
        window._settings_form._editors["ptt_shortcut"].setText("Alt+Q")
        window._settings_save_btn.click()
        assert len(saved) == 1
        assert saved[0].ptt_shortcut == "Alt+Q"
        assert "immediately" in window._settings_status.text()
    finally:
        window.close()


def test_settings_page_save_blocked_when_invalid(qapp, stores) -> None:
    saved: list[Settings] = []
    window = _main(qapp, stores, on_save_settings=saved.append)
    try:
        window._settings_form._editors["ptt_shortcut"].setText("d")
        assert not window._settings_save_btn.isEnabled()
        window._settings_save_btn.click()
        assert saved == []
    finally:
        window.close()


def test_settings_page_save_failure_surfaced(qapp, stores) -> None:
    def boom(values: Settings) -> None:
        raise RuntimeError("engine blew up")

    window = _main(qapp, stores, on_save_settings=boom)
    try:
        window._settings_save_btn.click()
        assert "engine blew up" in window._settings_status.text()
    finally:
        window.close()


def test_settings_page_conflicting_shortcut_blocks_save(qapp, stores) -> None:
    saved: list[Settings] = []
    window = _main(qapp, stores, on_save_settings=saved.append)
    try:
        form = window._settings_form
        form._editors["handsfree_shortcut"].setText(
            form._editors["ptt_shortcut"].text()
        )
        assert not form.is_valid()
        assert "conflict" in form._error.text().lower()
        assert not window._settings_save_btn.isEnabled()
        window._settings_save_btn.click()
        assert saved == []
    finally:
        window.close()


def test_settings_page_mirrors_error_to_status_line(qapp, stores) -> None:
    window = _main(qapp, stores)
    try:
        form = window._settings_form
        form._editors["ptt_shortcut"].setText("d")
        assert "Push-to-talk" in window._settings_status.text()
        assert window._settings_status.property("role") == "error"
        form._editors["ptt_shortcut"].setText("Alt+W")
        assert window._settings_status.text() == ""
        assert window._settings_status.property("role") == "confirm"
    finally:
        window.close()


def test_settings_page_recent_dictation_prefilled(qapp, stores) -> None:
    window = _main(
        qapp, stores, on_refresh_history=lambda: ["first", "second"]
    )
    try:
        items = [
            window._settings_form._history_list.item(i).text()
            for i in range(window._settings_form._history_list.count())
        ]
        assert items == ["first", "second"]
    finally:
        window.close()


def test_settings_page_stale_saved_becomes_unsaved(qapp, stores) -> None:
    window = _main(qapp, stores, on_save_settings=lambda values: None)
    try:
        window._settings_save_btn.click()
        assert "applied immediately" in window._settings_status.text()
        window._settings_form._editors["ptt_shortcut"].setText("Alt+Q")
        assert window._settings_status.text() == "Unsaved changes"
        window._settings_save_btn.click()
        assert "applied immediately" in window._settings_status.text()
        window._settings_form._engine.setCurrentText("moonshine")
        assert window._settings_status.text() == "Unsaved changes"
    finally:
        window.close()


def test_dictionary_flush_marks_saved_not_applied(qapp, stores) -> None:
    window = _main(qapp, stores)
    try:
        window.show_page("dictionary")
        form = window._dict_form
        form._edit.setText("wug applied")
        form._add_btn.click()
        assert form.is_dirty()
        window.flush_drafts()
        assert not form.is_dirty()
        assert not form.is_applied()
        assert "press Save to apply" in form._status.text()
        assert form.save_with_feedback(None) is True
        assert form.is_applied()
        assert form._status.text() == "Dictionary saved — engine reloaded"
    finally:
        window.close()


def test_dictionary_reload_keeps_ui_alive(qapp, stores) -> None:
    import time

    from PySide6.QtCore import QTimer

    window = _main(qapp, stores)
    try:
        window.show_page("dictionary")
        form = window._dict_form
        ticks = {"n": 0}
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: ticks.__setitem__("n", ticks["n"] + 1))
        heartbeat.start()

        def slow_reload(store) -> None:
            time.sleep(0.25)

        try:
            assert form.save_with_feedback(slow_reload) is True
        finally:
            heartbeat.stop()
        assert ticks["n"] > 0
    finally:
        window.close()


def test_dictate_buttons_follow_state_and_drive_hooks(qapp, stores) -> None:
    calls: list[str] = []
    copied: list[str] = []
    window = _main(
        qapp,
        stores,
        on_dictate_start=lambda: calls.append("start"),
        on_dictate_stop=lambda: calls.append("stop"),
        on_dictate_cancel=lambda: calls.append("cancel"),
        on_insert_text=calls.append,
        copy_fn=copied.append,
    )
    try:
        page = window._dictate
        assert page._start_btn.isEnabled()
        assert not page._stop_btn.isEnabled()
        assert not page._cancel_btn.isEnabled()
        page._start_btn.click()
        assert calls == ["start"]
        window.set_state(SessionState.RECORDING)
        assert not page._start_btn.isEnabled()
        assert page._stop_btn.isEnabled()
        assert page._cancel_btn.isEnabled()
        window.on_transcript("hello editable")
        assert page.reviewed_text() == "hello editable"
        page._last.setPlainText("hello edited")
        page._copy_btn.click()
        assert copied == ["hello edited"]
        assert "Copied" in page._insert_status.text()
        page._insert_btn.click()
        assert calls[-1] == "hello edited"
        window.on_insert(("typed", "XlibTyper"))
        assert "Xlib" in page._insert_status.text()
        window.on_insert(("held", "Focus changed — review, then Insert"))
        assert "Focus changed" in page._insert_status.text()
        window.set_state(SessionState.IDLE)
        assert page._start_btn.isEnabled()
    finally:
        window.close()


def test_notes_flush_saves_draft_on_page_switch(qapp, stores) -> None:
    _history, notes, _dictionary = stores
    window = _main(qapp, stores)
    try:
        window.show_page("notes")
        note_id = window._notes_win._current_id()
        window._notes_win._body.setPlainText("unsaved draft")
        window.show_page("history")  # nav-away flushes
        assert notes.get(note_id) is not None
        assert notes.get(note_id)["body"] == "unsaved draft"
    finally:
        window.close()


def test_notes_undo_delete_restores_note(qapp, stores) -> None:
    _history, notes, _dictionary = stores
    window = _main(qapp, stores)
    try:
        window.show_page("notes")
        assert not window._notes_win._undo_btn.isEnabled()
        window._notes_win._body.setPlainText("doomed body")
        window._notes_win._delete_btn.click()
        assert window._notes_win._list.count() == 0
        assert window._notes_win._undo_btn.isEnabled()
        window._notes_win._undo_btn.click()
        assert window._notes_win._list.count() == 1
        assert "doomed body" in window._notes_win._body.toPlainText()
        assert not window._notes_win._undo_btn.isEnabled()
    finally:
        window.close()


def test_dictionary_dirty_marker_and_flush(qapp, stores, tmp_path) -> None:
    window = _main(qapp, stores)
    try:
        window.show_page("dictionary")
        form = window._dict_form
        assert not form.is_dirty()
        form._edit.setText("wug testword")
        form._add_btn.click()
        assert form.is_dirty()
        assert "Unsaved" in form._status.text()
        window.flush_drafts()  # quit path persists without engine reload
        assert not form.is_dirty()
        assert "wug testword" in (tmp_path / "hotwords.txt").read_text()
    finally:
        window.close()


# -- shortcut capture --------------------------------------------------


def test_combo_spec_from_qt() -> None:
    alt = Qt.KeyboardModifier.AltModifier.value
    ctrl = Qt.KeyboardModifier.ControlModifier.value
    meta = Qt.KeyboardModifier.MetaModifier.value
    shift = Qt.KeyboardModifier.ShiftModifier.value
    assert combo_spec_from_qt(alt, Qt.Key.Key_W.value) == "Alt+W"
    assert combo_spec_from_qt(ctrl | meta, Qt.Key.Key_D.value) == "Ctrl+Super+D"
    assert combo_spec_from_qt(shift, Qt.Key.Key_F5.value) == "Shift+F5"
    assert combo_spec_from_qt(0, Qt.Key.Key_Escape.value) is None
    assert combo_spec_from_qt(0, Qt.Key.Key_unknown.value) is None


def test_capture_records_alt_w(qapp, stores) -> None:
    window = _main(qapp, stores)
    try:
        window.show_page("settings")
        form = window._settings_form
        btn = form._capture_btns["ptt_shortcut"]
        btn.click()
        assert btn.text() == "Press keys…"
        QTest.keyClick(btn, Qt.Key.Key_W, Qt.KeyboardModifier.AltModifier)
        assert form._editors["ptt_shortcut"].text() == "Alt+W"
        assert btn.text() == "Record"
        assert form.is_valid()
    finally:
        window.close()


def test_capture_escape_cancels(qapp, stores) -> None:
    window = _main(qapp, stores)
    try:
        form = window._settings_form
        editor = form._editors["handsfree_shortcut"]
        before = editor.text()
        btn = form._capture_btns["handsfree_shortcut"]
        btn.click()
        QTest.keyClick(btn, Qt.Key.Key_Escape)
        assert editor.text() == before
        assert btn.text() == "Record"
    finally:
        window.close()


def test_capture_invalid_combo_rejected(qapp, stores) -> None:
    window = _main(qapp, stores)
    try:
        form = window._settings_form
        editor = form._editors["copy_last_shortcut"]
        before = editor.text()
        btn = form._capture_btns["copy_last_shortcut"]
        btn.click()
        QTest.keyClick(btn, Qt.Key.Key_D)  # bare letter: invalid
        assert editor.text() == before
        assert "letter" in form._error.text().lower()
        assert btn.text() == "Record"
    finally:
        window.close()


def test_capture_reserved_combo_rejected(qapp, stores) -> None:
    window = _main(qapp, stores)
    try:
        form = window._settings_form
        editor = form._editors["paste_last_shortcut"]
        before = editor.text()
        btn = form._capture_btns["paste_last_shortcut"]
        btn.click()
        QTest.keyClick(
            btn, Qt.Key.Key_C, Qt.KeyboardModifier.ControlModifier
        )
        assert editor.text() == before
        assert "reserved" in form._error.text().lower()
    finally:
        window.close()


def test_settings_dialog_capture_buttons_present(qapp) -> None:
    dlg = SettingsDialog(Settings())
    try:
        assert set(dlg._capture_btns) == {
            "ptt_shortcut",
            "handsfree_shortcut",
            "command_shortcut",
            "paste_last_shortcut",
            "copy_last_shortcut",
            "cancel_key",
        }
    finally:
        dlg.close()


# -- history upgrades --------------------------------------------------


def test_history_copy_confirmation(qapp) -> None:
    copied: list[str] = []
    store = FakeHistory([{"id": "1", "ts": 1.0, "text": "hello"}])
    window = HistoryWindow(store, copy_fn=copied.append)
    try:
        assert window._status.text() == ""
        window._list.setCurrentRow(0)
        window._copy_btn.click()
        assert copied == ["hello"]
        assert window._status.text() == "Copied to clipboard"
    finally:
        window.close()


def test_history_empty_state(qapp) -> None:
    window = HistoryWindow(FakeHistory([]), copy_fn=lambda text: None)
    try:
        window.show()
        assert window._list.count() == 0
        assert window._empty.isVisible()
    finally:
        window.close()


def test_history_empty_state_hidden_with_rows(qapp) -> None:
    store = FakeHistory([{"id": "1", "ts": 1.0, "text": "hello"}])
    window = HistoryWindow(store, copy_fn=lambda text: None)
    try:
        assert window._empty.isHidden()
    finally:
        window.close()


def test_history_escape_closes_top_level(qapp) -> None:
    window = HistoryWindow(FakeHistory([]), copy_fn=lambda text: None)
    try:
        window.show()
        assert window.isVisible()
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
        )
        window.keyPressEvent(event)
        assert not window.isVisible()
    finally:
        window.close()


# -- notes upgrades ----------------------------------------------------


def test_notes_autosave_on_switch(qapp) -> None:
    store = FakeNotes()
    store.create("One")
    store.create("Two")
    window = ScratchpadWindow(store, on_dictate=lambda: None)
    try:
        window._list.setCurrentRow(0)
        first_id = window._current_id()
        window._body.setPlainText("unsaved edits")
        window._list.setCurrentRow(1)
        assert store.get(first_id)["body"] == "unsaved edits"
    finally:
        window.close()


def test_notes_new_note_keeps_current_edits(qapp) -> None:
    store = FakeNotes()
    store.create("One")
    window = ScratchpadWindow(store, on_dictate=lambda: None)
    try:
        window._list.setCurrentRow(0)
        current_id = window._current_id()
        window._body.setPlainText("keep me")
        window._new_btn.click()
        assert store.get(current_id)["body"] == "keep me"
    finally:
        window.close()


def test_notes_empty_state_and_escape(qapp) -> None:
    window = ScratchpadWindow(FakeNotes(), on_dictate=lambda: None)
    try:
        window.show()
        assert window._empty.isVisible()
        event = QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
        )
        window.keyPressEvent(event)
        assert not window.isVisible()
    finally:
        window.close()


# -- dictionary upgrades ------------------------------------------------


def test_dictionary_parakeet_hint(qapp, tmp_path) -> None:
    from flow.ui.dictionary import HINT_TEXT

    store = DictionaryStore(str(tmp_path / "hotwords.txt"))
    dlg = DictionaryDialog(store)
    try:
        assert "Parakeet" in HINT_TEXT
        assert "Moonshine" in HINT_TEXT
    finally:
        dlg.close()


def test_dictionary_save_progress_and_reload(qapp, tmp_path) -> None:
    store = DictionaryStore(str(tmp_path / "hotwords.txt"))
    store.add("hello")
    reloaded: list[DictionaryStore] = []
    dlg = DictionaryDialog(store, on_save=reloaded.append)
    try:
        dlg._save_btn.click()
        assert reloaded == [store]
        assert "reloaded" in dlg._status.text()
        assert dlg.result() == QDialog.DialogCode.Accepted
    finally:
        dlg.close()


def test_dictionary_reload_failure_keeps_dialog_open(qapp, tmp_path) -> None:
    store = DictionaryStore(str(tmp_path / "hotwords.txt"))
    store.add("hello")

    def boom(st: DictionaryStore) -> None:
        raise RuntimeError("no engine")

    dlg = DictionaryDialog(store, on_save=boom)
    try:
        dlg._save_btn.click()
        assert "no engine" in dlg._error.text()
        assert dlg.result() == QDialog.DialogCode.Rejected
    finally:
        dlg.close()


def test_dictionary_page_save_in_main_window(qapp, stores) -> None:
    reloaded: list[DictionaryStore] = []
    window = _main(qapp, stores, on_save_dictionary=reloaded.append)
    try:
        window.show_page("dictionary")
        window._dict_form._edit.setText("custom word")
        window._dict_form._add_btn.click()
        window._dict_save_btn.click()
        assert len(reloaded) == 1
        assert "reloaded" in window._dict_form._status.text()
    finally:
        window.close()


# -- pill upgrades -------------------------------------------------------


def test_pill_message_auto_dismiss_interval(qapp) -> None:
    assert MESSAGE_DISMISS_MS == 4000
    pill = QtPill()
    try:
        assert pill._dismiss.interval() == 4000
        assert pill._dismiss.isSingleShot()
    finally:
        pill.close()


def test_pill_message_dismisses_when_idle(qapp) -> None:
    pill = QtPill()
    try:
        pill.set_state(SessionState.IDLE)
        pill.show_message("boom")
        assert pill.isVisible()
        assert pill._dismiss.isActive()
        pill._dismiss_message()
        assert pill.isHidden()
    finally:
        pill.close()


def test_pill_message_restores_recording_label(qapp) -> None:
    pill = QtPill()
    try:
        pill.set_state(SessionState.RECORDING)
        pill.show_message("boom")
        assert pill._label.text() == "boom"
        pill._dismiss_message()
        assert pill.isVisible()
        assert pill._label.text().startswith("Listening…")
    finally:
        pill.close()


def test_pill_recording_elapsed_timer(qapp) -> None:
    pill = QtPill()
    try:
        pill.set_state(SessionState.RECORDING)
        pill._rec_start = time.monotonic() - 65.0
        pill._tick()
        assert pill._label.text() == "Listening… 1:05"
        pill.set_state(SessionState.IDLE)
        assert pill.isHidden()
    finally:
        pill.close()
