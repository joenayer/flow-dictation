#!/usr/bin/env python3
"""Create a small, read-only Wispr Flow Windows dictionary handoff for Flow Dictation."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

FORMAT = "flow-dictation-wispr-dictionary"
VERSION = 1
MAX_ENTRIES = 5_000
MAX_TRANSFER_BYTES = 2_000_000
PERSONAL_LIBRARY_ID = "00000000-0000-0000-0000-000000000000"
OUTPUT_BASENAME = "Wispr-Flow-Dictionary.json"


class ExportError(Exception):
    pass


def read_personal_dictionary(database_path: Path) -> list[dict[str, str | None]]:
    """Read only the active personal dictionary columns needed for import."""
    if not database_path.is_file():
        raise ExportError("Wispr Flow's local dictionary database was not found.")

    uri = database_path.resolve().as_uri() + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            connection.execute("PRAGMA query_only=ON")
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(Dictionary)")
            }
            required = {"phrase", "replacement", "teamDictionaryId", "isDeleted", "isSnippet"}
            if not required.issubset(columns):
                raise ExportError("This Wispr Flow database has an unsupported dictionary layout.")

            cursor = connection.execute(
                "SELECT phrase, replacement FROM Dictionary "
                "WHERE isDeleted = 0 AND isSnippet = 0 AND teamDictionaryId = ? "
                "ORDER BY phrase COLLATE NOCASE",
                (PERSONAL_LIBRARY_ID,),
            )
            entries: list[dict[str, str | None]] = []
            for phrase, replacement in cursor:
                if not isinstance(phrase, str) or not phrase.strip():
                    raise ExportError("Wispr Flow contains an empty dictionary word; no file was created.")
                if replacement is not None and not isinstance(replacement, str):
                    raise ExportError("Wispr Flow contains an unsupported dictionary correction; no file was created.")
                entries.append({
                    "phrase": phrase,
                    "replacement": replacement if isinstance(replacement, str) and replacement.strip() else None,
                })
                if len(entries) > MAX_ENTRIES:
                    raise ExportError("This dictionary has more than 5,000 entries. No file was created.")
            return entries
        finally:
            connection.close()
    except ExportError:
        raise
    except sqlite3.Error as error:
        raise ExportError("Wispr Flow's dictionary could not be read. Close Wispr Flow and try again.") from error


def _create_unique_file(folder: Path) -> tuple[int, Path]:
    for number in range(1, 10_000):
        suffix = "" if number == 1 else f" ({number})"
        path = folder / f"{Path(OUTPUT_BASENAME).stem}{suffix}{Path(OUTPUT_BASENAME).suffix}"
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            return descriptor, path
        except FileExistsError:
            continue
    raise ExportError("Could not choose a new filename in Downloads.")


def create_transfer_file(database_path: Path, output_folder: Path) -> tuple[Path, int]:
    entries = read_personal_dictionary(database_path)
    if not entries:
        raise ExportError("No active personal dictionary words were found. No transfer file was created.")
    payload: dict[str, Any] = {"format": FORMAT, "version": VERSION, "entries": entries}
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_TRANSFER_BYTES:
        raise ExportError("The dictionary transfer file would be too large for Flow Dictation. No file was created.")

    output_folder.mkdir(parents=True, exist_ok=True)
    descriptor, output_path = _create_unique_file(output_folder)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        try:
            output_path.unlink()
        except OSError:
            pass
        raise
    return output_path, len(entries)


def main() -> int:
    if os.name != "nt":
        print("Run this helper on the Windows computer where Wispr Flow is installed.")
        return 1

    appdata = os.environ.get("APPDATA")
    userprofile = os.environ.get("USERPROFILE")
    if not appdata or not userprofile:
        print("Windows could not find the Wispr Flow or Downloads folder.")
        return 1

    database = Path(appdata) / "Wispr Flow" / "flow.sqlite"
    downloads = Path(userprofile) / "Downloads"
    try:
        output, count = create_transfer_file(database, downloads)
    except ExportError as error:
        print(str(error))
        return 1
    except OSError:
        print("The transfer file could not be saved in Downloads.")
        return 1

    print(f"Created a transfer file with {count} dictionary entries:")
    print(output)
    print("Move this file to your Android phone, then choose it in Flow Dictation.")
    print("The file contains your private dictionary words. Keep it somewhere safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
