"""Settings schema (unit 1 contract — do not change field names/types)."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import tempfile

log = logging.getLogger("flow.config")


@dataclasses.dataclass
class Settings:
    ptt_shortcut: str = "Alt+W"
    handsfree_shortcut: str = "Alt+E"
    command_shortcut: str = "Alt+G"
    paste_last_shortcut: str = "Alt+B"
    copy_last_shortcut: str = "Alt+C"
    cancel_key: str = "Escape"
    engine: str = "parakeet"  # or "moonshine"
    stt_threads: int = 8
    sample_rate: int = 16000  # models require 16 kHz mono
    models_dir: str = "models"
    hotwords_file: str = ""
    cleanup_fillers: bool = True
    cleanup_punctuate: bool = True
    press_enter_phrase: bool = False


def default_settings_path() -> str:
    return os.path.expanduser("~/.config/flow-linux/settings.json")


_SHORTCUT_FIELDS = (
    "ptt_shortcut",
    "handsfree_shortcut",
    "command_shortcut",
    "paste_last_shortcut",
    "copy_last_shortcut",
    "cancel_key",
)
_PATH_FIELDS = ("models_dir", "hotwords_file")
_BOOL_FIELDS = ("cleanup_fillers", "cleanup_punctuate", "press_enter_phrase")
_ENGINES = ("parakeet", "moonshine")


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


def _validation_error(data: dict) -> str | None:
    """Return why loaded settings are unusable, or None when valid.

    Dataclass construction does not enforce annotations, so a
    structurally valid file with wrong field types (``{"engine": []}``)
    would otherwise explode later in engine setup.
    """
    for field in _SHORTCUT_FIELDS:
        value = data.get(field)
        if value is not None and (
            not isinstance(value, str) or not value.strip()
        ):
            return f"{field} must be a non-empty string"
    for field in _PATH_FIELDS:
        value = data.get(field)
        # Empty hotwords_file means "none"; models_dir is required.
        if value is not None and not isinstance(value, str):
            return f"{field} must be a string"
        if field == "models_dir" and isinstance(value, str) and not value.strip():
            return "models_dir must be a non-empty string"
    engine = data.get("engine")
    if engine is not None and engine not in _ENGINES:
        return f"engine must be one of {_ENGINES}"
    threads = data.get("stt_threads")
    if threads is not None and (
        not isinstance(threads, int)
        or isinstance(threads, bool)
        or threads <= 0
    ):
        return "stt_threads must be a positive integer"
    rate = data.get("sample_rate")
    if rate is not None and (
        not isinstance(rate, int) or isinstance(rate, bool) or rate != 16000
    ):
        return "sample_rate must be 16000 (models require 16 kHz mono)"
    for field in _BOOL_FIELDS:
        value = data.get(field)
        if value is not None and not isinstance(value, bool):
            return f"{field} must be true or false"
    return None


def load_settings(path: str | None = None) -> Settings:
    # First-run defaults live in 2-key Alt space on every platform: Alt
    # chords never hit OS-reserved behavior, and the backends swallow them
    # before apps see menu accelerators. Saved user bindings are untouched.
    path = path or default_settings_path()
    if not os.path.exists(path):
        return Settings()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        known = {f.name for f in dataclasses.fields(Settings)}
        filtered = {k: v for k, v in data.items() if k in known}
        problem = _validation_error(filtered)
        if problem is not None:
            raise ValueError(problem)
        return Settings(**filtered)
    except (OSError, ValueError, AttributeError, TypeError) as exc:
        # Corrupt settings must never prevent startup: preserve the file
        # aside (never silently delete user data) and run on defaults.
        log.warning("settings file %r unreadable (%s); using defaults", path, exc)
        _quarantine(path)
        return Settings()


def save_settings(settings: Settings, path: str | None = None) -> None:
    path = path or default_settings_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    # Staged write: serialize and fsync a same-directory temp file, then
    # atomically replace. An interrupted save keeps the previous file.
    payload = json.dumps(dataclasses.asdict(settings), indent=2)
    fd, tmp = tempfile.mkstemp(
        prefix=".settings-", suffix=".tmp", dir=parent or "."
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
