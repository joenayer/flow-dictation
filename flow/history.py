"""JSONL transcript history for paste-last / copy-last / session search."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

log = logging.getLogger("flow.history")

MAX_ENTRIES = 500
DEFAULT_HISTORY_PATH = os.path.expanduser("~/.local/share/flow-linux/history.jsonl")


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _quarantine(path: str) -> str | None:
    """Move a damaged file aside; never overwrite an earlier backup."""
    candidate = path + ".corrupt"
    if os.path.exists(candidate):
        index = 1
        while os.path.exists(f"{candidate}-{index}"):
            index += 1
        candidate = f"{candidate}-{index}"
    try:
        os.replace(path, candidate)
    except OSError:
        return None
    return candidate


def _copy_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {"id": entry["id"], "ts": entry["ts"], "text": entry["text"]}


def _dump_entry(entry: dict[str, Any]) -> str:
    return json.dumps(
        {"id": entry["id"], "ts": entry["ts"], "text": entry["text"]},
        ensure_ascii=False,
    )


def _coerce_entry(obj: object) -> tuple[dict[str, Any] | None, bool]:
    """Parse a JSONL value into {id, ts, text}. True if the line was legacy."""
    if isinstance(obj, str):
        return {"id": uuid.uuid4().hex, "ts": None, "text": obj}, True
    if not isinstance(obj, dict) or "text" not in obj:
        return None, False
    migrated = False
    raw_id = obj.get("id")
    if raw_id is None or raw_id == "":
        entry_id = uuid.uuid4().hex
        migrated = True
    else:
        entry_id = str(raw_id)
    if "ts" not in obj:
        ts: float | None = None
        migrated = True
    elif obj["ts"] is None:
        ts = None
    else:
        try:
            ts = float(obj["ts"])
        except (TypeError, ValueError):
            ts = None
            migrated = True
    return {"id": entry_id, "ts": ts, "text": str(obj["text"])}, migrated


class TranscriptStore:
    """Append-only JSONL store capped at MAX_ENTRIES newest entries.

    Reading never requires a writable directory: when migration or
    compaction cannot be saved, entries stay in memory and the rewrite
    is retried on the next append (``migration_pending`` / ``save_error``
    report the condition). Appending repairs an unterminated tail first
    so one missing newline can never eat old and new transcripts.
    """

    def __init__(self, path: str | None = None) -> None:
        self.path = path or DEFAULT_HISTORY_PATH
        self._entries: list[dict[str, Any]] = []
        self.migration_pending = False
        self.save_error: str | None = None
        self._load()

    def _load(self) -> None:
        self._entries = []
        self.migration_pending = False
        self.save_error = None
        if not os.path.exists(self.path):
            return
        migrated = False
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    entry, was_migrated = _coerce_entry(obj)
                    if entry is None:
                        continue
                    if was_migrated:
                        migrated = True
                    self._entries.append(entry)
        except (OSError, ValueError):
            # ValueError covers UnicodeDecodeError: garbage bytes start
            # empty instead of crashing startup. The tail repair in
            # append() quarantines the file on the next write.
            self._entries = []
            return
        truncated = False
        if len(self._entries) > MAX_ENTRIES:
            self._entries = self._entries[-MAX_ENTRIES:]
            truncated = True
        if migrated or truncated:
            try:
                self._rewrite()
            except OSError as exc:
                # Read-only directory: keep the parsed entries and
                # retry the conversion on the next append.
                self.migration_pending = True
                self.save_error = f"could not migrate history file: {exc}"
                log.warning(
                    "history migration deferred for %r (%s)",
                    self.path,
                    exc,
                )

    def _rewrite(self) -> None:
        _ensure_parent(self.path)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            for entry in self._entries:
                fh.write(_dump_entry(entry) + "\n")
        os.replace(tmp, self.path)

    def _tail_state(self) -> str:
        """Classify the file tail: ``"ok"``, ``"separator"``, or ``"broken"``.

        ``"separator"`` means the last record is complete but unterminated
        (an appended newline fixes it); ``"broken"`` means the tail is a
        partial record that must be quarantined before appending.
        """
        try:
            with open(self.path, "rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                if size == 0:
                    return "ok"
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) == b"\n":
                    return "ok"
                back = min(size, 1 << 20)
                fh.seek(-back, os.SEEK_END)
                last_line = fh.read(back).split(b"\n")[-1]
        except FileNotFoundError:
            return "ok"
        except OSError:
            return "ok"  # let the append itself report the error
        try:
            json.loads(last_line.decode("utf-8"))
        except ValueError:  # JSON error or non-UTF-8 tail bytes
            return "broken"
        return "separator"

    def append(self, text: str) -> int:
        entry = {"id": uuid.uuid4().hex, "ts": time.time(), "text": text}
        self._entries.append(entry)
        if len(self._entries) > MAX_ENTRIES:
            self._entries = self._entries[-MAX_ENTRIES:]
            self._rewrite()
            self.migration_pending = False
            self.save_error = None
            return len(self._entries)
        if self.migration_pending:
            try:
                self._rewrite()
            except OSError:
                pass
            else:
                self.migration_pending = False
                self.save_error = None
                return len(self._entries)
        tail = self._tail_state()
        if tail == "broken":
            backup = _quarantine(self.path)
            self._rewrite()
            where = f" (kept as {backup})" if backup else ""
            log.warning("history tail was partial; quarantined%s", where)
            return len(self._entries)
        _ensure_parent(self.path)
        with open(self.path, "a", encoding="utf-8") as fh:
            if tail == "separator":
                fh.write("\n")
            fh.write(_dump_entry(entry) + "\n")
        return len(self._entries)

    def last(self) -> str | None:
        if not self._entries:
            return None
        return self._entries[-1]["text"]

    def all(self) -> list[dict[str, Any]]:
        return [_copy_entry(entry) for entry in reversed(self._entries)]

    def search(self, query: str) -> list[dict[str, Any]]:
        needle = query.casefold()
        hits = [entry for entry in self._entries if needle in entry["text"].casefold()]
        return [_copy_entry(entry) for entry in reversed(hits)]
