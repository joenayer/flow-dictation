"""NoteStore: CRUD, search, and persist round trip (tmp_path only)."""

from __future__ import annotations

import json
import os
import time

import pytest

from flow.notes import DEFAULT_NOTES_PATH, NoteStore


def test_default_path_is_xdg_data_home() -> None:
    assert DEFAULT_NOTES_PATH.endswith("/flow-linux/notes.json")
    assert os.path.expanduser("~/.local/share/flow-linux/notes.json") == DEFAULT_NOTES_PATH


def test_create_get_and_shape(tmp_path) -> None:
    store = NoteStore(str(tmp_path / "notes.json"))
    before = time.time()
    note_id = store.create("First")
    after = time.time()
    note = store.get(note_id)
    assert note is not None
    assert note["id"] == note_id
    assert note["title"] == "First"
    assert note["body"] == ""
    assert isinstance(note["ts"], float)
    assert before <= note["ts"] <= after + 0.5
    assert store.get("missing") is None


def test_list_all_newest_first(tmp_path) -> None:
    store = NoteStore(str(tmp_path / "notes.json"))
    first = store.create("older")
    time.sleep(0.02)
    second = store.create("newer")
    listed = store.list_all()
    assert [n["id"] for n in listed] == [second, first]
    assert listed[0]["title"] == "newer"


def test_update_and_delete(tmp_path) -> None:
    store = NoteStore(str(tmp_path / "notes.json"))
    note_id = store.create("Draft")
    assert store.update(note_id, "Saved", "hello body") is True
    note = store.get(note_id)
    assert note is not None
    assert note["title"] == "Saved"
    assert note["body"] == "hello body"
    assert store.update("missing", "x", "y") is False
    assert store.delete(note_id) is True
    assert store.get(note_id) is None
    assert store.list_all() == []
    assert store.delete("missing") is False


def test_search_case_insensitive(tmp_path) -> None:
    store = NoteStore(str(tmp_path / "notes.json"))
    a = store.create("Grocery List")
    store.update(a, "Grocery List", "milk and eggs")
    time.sleep(0.02)
    b = store.create("Work")
    store.update(b, "Work", "Write the GROCERY report")
    c = store.create("Unrelated")
    store.update(c, "Unrelated", "nothing here")

    hits = store.search("grocery")
    assert [n["id"] for n in hits] == [b, a]
    assert store.search("EGGS")[0]["id"] == a
    assert store.search("nope") == []


def test_persist_round_trip(tmp_path) -> None:
    path = tmp_path / "notes.json"
    store = NoteStore(str(path))
    note_id = store.create("Keep")
    assert store.update(note_id, "Keep", "persisted body") is True
    extra = store.create("Drop me")
    assert store.delete(extra) is True

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert len(raw) == 1
    assert not os.path.exists(str(path) + ".tmp")

    reloaded = NoteStore(str(path))
    note = reloaded.get(note_id)
    assert note is not None
    assert note["title"] == "Keep"
    assert note["body"] == "persisted body"
    listed = reloaded.list_all()
    assert len(listed) == 1
    assert listed[0]["id"] == note_id
    assert reloaded.update(note_id, "Keep", "round trip") is True
    assert NoteStore(str(path)).get(note_id)["body"] == "round trip"


def test_garbage_bytes_start_empty(tmp_path) -> None:
    path = tmp_path / "notes.json"
    path.write_bytes(b"\x00\x01\x02\xff\xfe garbage")
    store = NoteStore(str(path))
    assert store.list_all() == []


def test_truncated_json_starts_empty(tmp_path) -> None:
    path = tmp_path / "notes.json"
    path.write_text('[{"id": "1", "tit', encoding="utf-8")
    store = NoteStore(str(path))
    assert store.list_all() == []


def test_truncated_file_salvages_complete_notes(tmp_path) -> None:
    path = tmp_path / "notes.json"
    path.write_text(
        '[{"id": "a1", "ts": 1, "title": "T", "body": "precious"},'
        ' {"id": "b2", "tit',
        encoding="utf-8",
    )
    store = NoteStore(str(path))
    assert [n["body"] for n in store.list_all()] == ["precious"]
    assert store.load_error
    backup = tmp_path / "notes.json.corrupt"
    assert backup.is_file()  # original preserved for recovery


def test_save_after_corruption_keeps_backup(tmp_path) -> None:
    path = tmp_path / "notes.json"
    original = (
        '[{"id": "a1", "ts": 1, "title": "T", "body": "precious"},'
        ' {"id": "b2"'
    )
    path.write_text(original, encoding="utf-8")
    store = NoteStore(str(path))
    store.create("New")
    assert (tmp_path / "notes.json.corrupt").read_text(
        encoding="utf-8"
    ) == original
    bodies = sorted(n["body"] for n in NoteStore(str(path)).list_all())
    assert bodies == ["", "precious"]


def test_wrong_shape_quarantined_not_silently_dropped(tmp_path) -> None:
    path = tmp_path / "notes.json"
    path.write_text('{"id": "x"}', encoding="utf-8")
    store = NoteStore(str(path))
    assert store.list_all() == []
    assert store.load_error
    assert (tmp_path / "notes.json.corrupt").is_file()


def test_failed_mutations_roll_back_memory(tmp_path, monkeypatch) -> None:
    from flow.notes import NoteStore as NS

    path = tmp_path / "notes.json"
    store = NS(str(path))
    note_id = store.create("First")

    def _boom() -> None:
        raise OSError("injected ENOSPC")

    monkeypatch.setattr(store, "_save", _boom)
    with pytest.raises(OSError):
        store.create("Lost")
    with pytest.raises(OSError):
        store.update(note_id, "Changed", "changed body")
    with pytest.raises(OSError):
        store.delete(note_id)
    assert [n["id"] for n in store.list_all()] == [note_id]
    assert store.get(note_id)["body"] == ""


def test_create_full_writes_body_atomically(tmp_path) -> None:
    from flow.notes import NoteStore as NS

    path = tmp_path / "notes.json"
    store = NS(str(path))
    note_id = store.create_full("Title", "restored body")
    assert NS(str(path)).get(note_id)["body"] == "restored body"
