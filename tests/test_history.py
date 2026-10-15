"""TranscriptStore: append, last, cap, migration, search (tmp_path only)."""

from __future__ import annotations

import json
import time

from flow.history import DEFAULT_HISTORY_PATH, MAX_ENTRIES, TranscriptStore


def test_default_path_is_xdg_data_home() -> None:
    assert DEFAULT_HISTORY_PATH.endswith("/flow-linux/history.jsonl")
    assert MAX_ENTRIES == 500


def test_empty_store_last_is_none(tmp_path) -> None:
    store = TranscriptStore(str(tmp_path / "history.jsonl"))
    assert store.last() is None


def test_append_and_last(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    store = TranscriptStore(str(path))
    n = store.append("hello")
    assert n == 1
    assert store.last() == "hello"
    n = store.append("world")
    assert n == 2
    assert store.last() == "world"


def test_reload_from_jsonl(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    TranscriptStore(str(path)).append("persisted")
    reloaded = TranscriptStore(str(path))
    assert reloaded.last() == "persisted"
    assert reloaded.append("next") == 2
    assert reloaded.last() == "next"


def test_cap_keeps_newest_500(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    store = TranscriptStore(str(path))
    for i in range(MAX_ENTRIES + 5):
        n = store.append(str(i))
    assert n == MAX_ENTRIES
    assert store.last() == str(MAX_ENTRIES + 4)

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == MAX_ENTRIES
    assert lines[0]["text"] == "5"
    assert lines[-1]["text"] == str(MAX_ENTRIES + 4)

    reloaded = TranscriptStore(str(path))
    assert reloaded.last() == str(MAX_ENTRIES + 4)
    assert reloaded.append("tail") == MAX_ENTRIES
    assert reloaded.last() == "tail"


def test_append_sets_id_and_ts(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    store = TranscriptStore(str(path))
    before = time.time()
    assert store.append("hello") == 1
    after = time.time()
    entries = store.all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["text"] == "hello"
    assert isinstance(entry["id"], str) and entry["id"]
    assert isinstance(entry["ts"], float)
    assert before <= entry["ts"] <= after + 0.5
    assert store.last() == "hello"

    line = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert line["id"] == entry["id"]
    assert line["text"] == "hello"
    assert isinstance(line["ts"], float)


def test_all_is_newest_first(tmp_path) -> None:
    store = TranscriptStore(str(tmp_path / "history.jsonl"))
    store.append("older")
    store.append("newer")
    assert [e["text"] for e in store.all()] == ["newer", "older"]
    assert store.last() == "newer"


def test_migrate_legacy_lines(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(
        json.dumps("bare string")
        + "\n"
        + json.dumps({"text": "legacy dict"})
        + "\n"
        + json.dumps({"id": "keep-me", "ts": None, "text": "already new"})
        + "\n",
        encoding="utf-8",
    )
    store = TranscriptStore(str(path))
    entries = store.all()
    assert [e["text"] for e in entries] == ["already new", "legacy dict", "bare string"]
    assert store.last() == "already new"
    by_text = {e["text"]: e for e in entries}
    assert by_text["bare string"]["ts"] is None
    assert by_text["legacy dict"]["ts"] is None
    assert by_text["already new"]["ts"] is None
    assert by_text["already new"]["id"] == "keep-me"
    assert by_text["bare string"]["id"]
    assert by_text["legacy dict"]["id"]

    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 3
    assert [row["text"] for row in lines] == ["bare string", "legacy dict", "already new"]
    for row in lines:
        assert "id" in row and row["id"]
        assert "ts" in row
        assert row["ts"] is None
    assert lines[2]["id"] == "keep-me"


def test_search_case_insensitive_substring(tmp_path) -> None:
    store = TranscriptStore(str(tmp_path / "history.jsonl"))
    store.append("Hello World")
    store.append("goodbye")
    store.append("HELLO there")
    hits = store.search("hello")
    assert [h["text"] for h in hits] == ["HELLO there", "Hello World"]
    assert store.search("GOOD")[0]["text"] == "goodbye"
    assert store.search("nope") == []
    assert [h["text"] for h in store.search("")] == [h["text"] for h in store.all()]


def test_garbage_bytes_start_empty(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_bytes(b"\x00\x01\x02\xff\xfe garbage")
    store = TranscriptStore(str(path))
    assert store.all() == []
    assert store.last() is None


def test_bad_lines_skipped_good_lines_kept(tmp_path) -> None:
    path = tmp_path / "history.jsonl"
    path.write_text(
        '{"text": "kept one"}\nnot json at all\n{"text": "kept two"}\n',
        encoding="utf-8",
    )
    store = TranscriptStore(str(path))
    assert [e["text"] for e in store.all()] == ["kept two", "kept one"]


def test_append_repairs_unterminated_complete_tail(tmp_path) -> None:
    from flow.history import TranscriptStore as TS

    path = tmp_path / "history.jsonl"
    old = {"id": "x", "ts": 1.0, "text": "old one"}
    path.write_text(json.dumps(old), encoding="utf-8")  # no trailing \n
    store = TS(str(path))
    store.append("newly dictated")
    reopened = TS(str(path))
    assert [e["text"] for e in reopened.all()] == [
        "newly dictated",
        "old one",
    ]


def test_append_quarantines_partial_tail(tmp_path) -> None:
    from flow.history import TranscriptStore as TS

    path = tmp_path / "history.jsonl"
    old = {"id": "x", "ts": 1.0, "text": "old"}
    path.write_text(
        json.dumps(old) + "\n" + '{"id": "y", "te', encoding="utf-8"
    )
    store = TS(str(path))
    store.append("fresh")
    reopened = TS(str(path))
    assert [e["text"] for e in reopened.all()] == ["fresh", "old"]
    assert (tmp_path / "history.jsonl.corrupt").is_file()


def test_legacy_history_loads_without_write_permission(tmp_path) -> None:
    import os

    from flow.history import TranscriptStore as TS

    rodir = tmp_path / "ro"
    rodir.mkdir()
    path = rodir / "history.jsonl"
    path.write_text('"legacy text"\n', encoding="utf-8")
    os.chmod(rodir, 0o500)
    try:
        store = TS(str(path))
    finally:
        os.chmod(rodir, 0o700)
    assert store.last() == "legacy text"
    assert store.migration_pending is True
    assert store.save_error
