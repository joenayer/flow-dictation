"""Custom vocabulary persisted as a sherpa-onnx hotwords file.

File format (UTF-8), verified against:

- installed sherpa-onnx 1.13.8 ``OfflineRecognizer.from_transducer``
  (``hotwords_file: str = ''``, ``hotwords_score: float = 1.5``) and its
  docstring: one words/phrase per line; BPE/cjkchar pieces space-separated
- https://k2-fsa.github.io/sherpa/onnx/hotwords/index.html

Rules:

- one phrase per line; empty lines ignored
- tokens on a line are space-separated
- optional boosting score as the **last** field only: ``HELLO WORLD :2.0``
- ``from_transducer`` requires ``decoding_method='modified_beam_search'``
  when ``hotwords_file`` is non-empty (ValueError otherwise)
- ``from_moonshine`` (1.13.8) has no ``hotwords_file`` / ``hotwords_score``;
  sherpa docs: hotwords are transducer-only
"""

from __future__ import annotations

import inspect
import logging
import os
import re
from collections.abc import Callable
from typing import Any

log = logging.getLogger("flow.dictionary")

HOTWORDS_FILENAME = "hotwords.txt"
DEFAULT_HOTWORDS_SCORE = 1.5
MAX_WORDS = 5

# One token: letters, with optional internal apostrophes / hyphens.
_TOKEN_RE = re.compile(r"[A-Za-z]+(?:['\-][A-Za-z]+)*")
_SCORE_RE = re.compile(r":[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")


def hotwords_path(models_dir: str) -> str:
    return os.path.join(models_dir, HOTWORDS_FILENAME)


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


def normalize_phrase(word: str) -> str | None:
    """Return a stripped phrase if it is valid custom vocab, else None.

    Valid: 1–5 whitespace-separated tokens; letters, apostrophes, hyphens,
    and spaces only.
    """
    if word is None:
        return None
    phrase = " ".join(str(word).split())
    if not phrase:
        return None
    tokens = phrase.split(" ")
    if not (1 <= len(tokens) <= MAX_WORDS):
        return None
    if not all(_TOKEN_RE.fullmatch(tok) for tok in tokens):
        return None
    return phrase


def parse_hotwords_file(path: str) -> list[str]:
    """Read a sherpa hotwords file. Raises RuntimeError if malformed."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as exc:
        raise RuntimeError(f"cannot read hotwords file {path!r}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"hotwords file is malformed (not UTF-8): {path}: {exc}"
        ) from exc
    phrases: list[str] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            phrase = _parse_hotwords_line(stripped)
        except ValueError as exc:
            raise RuntimeError(
                f"hotwords file is malformed: {path}:{lineno}: {exc}"
            ) from exc
        if phrase:
            phrases.append(phrase)
    return phrases


def _parse_hotwords_line(line: str) -> str:
    parts = line.split()
    score_at = [i for i, part in enumerate(parts) if part.startswith(":")]
    if score_at:
        if score_at != [len(parts) - 1]:
            raise ValueError(
                "boosting score must be the last field "
                f"(e.g. 'HELLO WORLD :2.0'), got {line!r}"
            )
        if not _SCORE_RE.fullmatch(parts[-1]):
            raise ValueError(f"invalid boosting score {parts[-1]!r}")
        parts = parts[:-1]
    if not parts:
        return ""
    return " ".join(parts)


def recognizer_hotwords_kwargs(
    models_dir: str,
    factory: Callable[..., Any],
) -> dict[str, Any]:
    """Kwargs to pass a ``{models_dir}/hotwords.txt`` into a sherpa factory.

    Empty if the file is missing or the factory has no ``hotwords_file``
    parameter. Sets ``decoding_method='modified_beam_search'`` when that
    parameter exists (required by from_transducer).
    """
    path = hotwords_path(models_dir)
    if not os.path.isfile(path):
        return {}
    parse_hotwords_file(path)
    params = inspect.signature(factory).parameters
    if "hotwords_file" not in params:
        return {}
    kwargs: dict[str, Any] = {"hotwords_file": path}
    if "hotwords_score" in params:
        kwargs["hotwords_score"] = DEFAULT_HOTWORDS_SCORE
    if "decoding_method" in params:
        kwargs["decoding_method"] = "modified_beam_search"
    return kwargs


class DictionaryStore:
    """In-memory custom vocabulary backed by a sherpa hotwords file.

    A malformed file is quarantined aside (``<path>.corrupt*``), valid
    lines are salvaged, and ``load_error`` describes what happened.
    """

    def __init__(self, path: str) -> None:
        self.path = path
        self._words: list[str] = []
        self.load_error: str | None = None
        self._load()

    def words(self) -> list[str]:
        return list(self._words)

    def add(self, word: str) -> bool:
        phrase = normalize_phrase(word)
        if phrase is None or phrase in self._words:
            return False
        self._words.append(phrase)
        return True

    def remove(self, word: str) -> bool:
        phrase = " ".join(str(word).split())
        if phrase not in self._words:
            return False
        self._words.remove(phrase)
        return True

    def save(self) -> None:
        parent = os.path.dirname(self.path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        body = "".join(f"{w}\n" for w in self._words)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(body)
        os.replace(tmp, self.path)

    def _load(self) -> None:
        self._words = []
        self.load_error = None
        if not os.path.isfile(self.path):
            return
        seen: set[str] = set()
        try:
            phrases = parse_hotwords_file(self.path)
        except RuntimeError as exc:
            # Quarantine the original so the next save cannot destroy
            # it, then keep every independently valid line.
            salvaged = self._salvage_lines()
            backup = _quarantine(self.path)
            for phrase in salvaged:
                normalized = normalize_phrase(phrase)
                if normalized is None or normalized in seen:
                    continue
                seen.add(normalized)
                self._words.append(normalized)
            where = f" (kept as {backup})" if backup else ""
            kept = f"kept {len(self._words)} valid lines; " if self._words else ""
            self.load_error = (
                f"hotwords file was malformed; {kept}original kept{where}"
            )
            log.warning("hotwords file %r malformed (%s)%s", self.path, exc, where)
            return
        for phrase in phrases:
            normalized = normalize_phrase(phrase)
            if normalized is None or normalized in seen:
                continue
            seen.add(normalized)
            self._words.append(normalized)

    def _salvage_lines(self) -> list[str]:
        """Best-effort valid phrases from a malformed hotwords file."""
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                raw = fh.read()
        except (OSError, ValueError):
            return []
        phrases: list[str] = []
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                phrase = _parse_hotwords_line(stripped)
            except ValueError:
                continue
            if phrase:
                phrases.append(phrase)
        return phrases
