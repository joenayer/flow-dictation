"""JSON note store for the dictated-notes scratchpad."""

from __future__ import annotations

import json
import logging
import os
import time
import uuid
from typing import Any

log = logging.getLogger("flow.notes")

DEFAULT_NOTES_PATH = os.path.expanduser("~/.local/share/flow-linux/notes.json")


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


def _as_entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or "id" not in raw:
        return None
    try:
        ts = float(raw.get("ts") or 0.0)
    except (TypeError, ValueError):
        ts = 0.0
    return {
        "id": str(raw["id"]),
        "ts": ts,
        "title": str(raw.get("title") or ""),
        "body": str(raw.get("body") or ""),
    }


def _salvage_entries(text: str) -> list[dict[str, Any]]:
    """Recover complete leading entries from a truncated JSON array."""
    stripped = text.strip()
    if not stripped.startswith("["):
        return []
    decoder = json.JSONDecoder()
    entries: list[dict[str, Any]] = []
    idx, end = 1, len(stripped)
    while idx < end:
        while idx < end and stripped[idx] in " \t\r\n,":
            idx += 1
        if idx >= end or stripped[idx] == "]":
            break
        try:
            obj, idx = decoder.raw_decode(stripped, idx)
        except json.JSONDecodeError:
            break
        entry = _as_entry(obj)
        if entry is not None:
            entries.append(entry)
    return entries


class NoteStore:
    """Persists notes as a JSON list. Writes are atomic (tmp + os.replace).

    A damaged file is quarantined aside (``<path>.corrupt*``) instead of
    being silently replaced, complete leading entries are salvaged, and
    ``load_error`` describes what happened for the UI.
    """

    def __init__(self, path: str | None = None) -> None:
        self.path = path or DEFAULT_NOTES_PATH
        self._notes: list[dict[str, Any]] = []
        self.load_error: str | None = None
        self._load()

    def _load(self) -> None:
        self._notes = []
        self.load_error = None
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw_text = fh.read()
        except (OSError, ValueError) as exc:
            # ValueError covers UnicodeDecodeError: garbage bytes start
            # empty instead of crashing startup. Quarantine first so the
            # next save cannot destroy the original.
            backup = _quarantine(self.path)
            where = f" (kept as {backup})" if backup else ""
            self.load_error = f"notes file was damaged; started empty{where}"
            log.warning("notes file %r unreadable (%s)%s", self.path, exc, where)
            return
        try:
            data = json.loads(raw_text)
        except ValueError as exc:
            salvaged = _salvage_entries(raw_text)
            backup = _quarantine(self.path)
            self._notes = salvaged
            where = f" (kept as {backup})" if backup else ""
            kept = f"recovered {len(salvaged)} note(s); " if salvaged else ""
            self.load_error = (
                f"notes file was truncated; {kept}original kept{where}"
            )
            log.warning("notes file %r truncated (%s)%s", self.path, exc, where)
            return
        if not isinstance(data, list):
            backup = _quarantine(self.path)
            where = f" (kept as {backup})" if backup else ""
            self.load_error = (
                f"notes file had the wrong shape; started empty{where}"
            )
            log.warning("notes file %r is not a JSON list%s", self.path, where)
            return
        for item in data:
            entry = _as_entry(item)
            if entry is not None:
                self._notes.append(entry)

    def _save(self) -> None:
        _ensure_parent(self.path)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._notes, fh, indent=2)
        os.replace(tmp, self.path)

    def _copy(self, note: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": note["id"],
            "ts": note["ts"],
            "title": note["title"],
            "body": note["body"],
        }

    def _newest_first(self, notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        indexed = list(enumerate(notes))
        indexed.sort(key=lambda pair: (pair[1]["ts"], pair[0]), reverse=True)
        return [self._copy(pair[1]) for pair in indexed]

    def _find(self, note_id: str) -> dict[str, Any] | None:
        for note in self._notes:
            if note["id"] == note_id:
                return note
        return None

    def create(self, title: str) -> str:
        return self.create_full(title, "")

    def create_full(self, title: str, body: str) -> str:
        """Create a note with its body in one atomic save (for Undo)."""
        note_id = uuid.uuid4().hex
        note = {
            "id": note_id,
            "ts": time.time(),
            "title": title,
            "body": body,
        }
        self._notes.append(note)
        try:
            self._save()
        except OSError:
            # Roll back the in-memory note: a failed write must not
            # leave a phantom entry that the next save would persist.
            self._notes = [n for n in self._notes if n["id"] != note_id]
            raise
        return note_id

    def get(self, id: str) -> dict[str, Any] | None:
        note = self._find(id)
        if note is None:
            return None
        return self._copy(note)

    def list_all(self) -> list[dict[str, Any]]:
        return self._newest_first(self._notes)

    def update(self, id: str, title: str, body: str) -> bool:
        note = self._find(id)
        if note is None:
            return False
        old_title, old_body = note["title"], note["body"]
        note["title"] = title
        note["body"] = body
        try:
            self._save()
        except OSError:
            note["title"] = old_title
            note["body"] = old_body
            raise
        return True

    def delete(self, id: str) -> bool:
        for index, note in enumerate(self._notes):
            if note["id"] == id:
                removed = self._notes.pop(index)
                try:
                    self._save()
                except OSError:
                    self._notes.insert(index, removed)
                    raise
                return True
        return False

    def search(self, q: str) -> list[dict[str, Any]]:
        needle = q.casefold()
        hits = [
            note
            for note in self._notes
            if needle in note["title"].casefold() or needle in note["body"].casefold()
        ]
        return self._newest_first(hits)
