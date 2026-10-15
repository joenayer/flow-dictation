"""Rule-based English transcript cleanup (pure function, no I/O).

Pipeline: strip and collapse whitespace; drop standalone fillers; collapse
adjacent duplicate words; remove spaces before ``. , ! ? ; :``; optionally
punctuate (capitalize sentence starts, ensure a ``.`` / ``!`` / ``?`` end
mark); optionally strip a trailing spoken ``press enter`` and append ``\\n``.

Examples::

    >>> from flow.config import Settings
    >>> clean("  hello world  ", Settings())
    'Hello world.'
    >>> clean("um hello uh world", Settings())
    'Hello world.'
    >>> clean("the the cat", Settings())
    'The cat.'
    >>> clean("hello .", Settings(cleanup_punctuate=False))
    'hello.'
    >>> clean("send this press enter", Settings(press_enter_phrase=True))
    'Send this.\\n'
    >>> clean("human um summer", Settings())
    'Human summer.'
"""

from __future__ import annotations

import re

from flow.config import Settings

_FILLERS = frozenset({"um", "uh", "er", "ah", "umm", "hmm"})
_FILLER_PUNCT = ".,!?;:\"'()[]{}"
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([.,!?;:])")
_PRESS_ENTER_RE = re.compile(r"(?i)(?:^|\s)press\s+enter\s*$")
_END_MARKS = ".!?"


def clean(text: str, settings: Settings) -> str:
    """Return a polished transcript. Pure: no I/O, no mutation of *settings*."""
    text = " ".join(text.split())
    if not text:
        return ""

    if settings.cleanup_fillers:
        text = _drop_fillers(text)
    text = _collapse_duplicate_words(text)
    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = text.strip()

    add_newline = False
    if settings.press_enter_phrase:
        text, add_newline = _strip_press_enter(text)

    if settings.cleanup_punctuate:
        text = _punctuate(text)

    if add_newline:
        text = text + "\n"
    return text


def _word_core(token: str) -> str:
    return token.strip(_FILLER_PUNCT).lower()


def _drop_fillers(text: str) -> str:
    kept = [tok for tok in text.split() if _word_core(tok) not in _FILLERS]
    return " ".join(kept)


def _collapse_duplicate_words(text: str) -> str:
    words = text.split()
    if not words:
        return ""
    out = [words[0]]
    for word in words[1:]:
        if word.lower() != out[-1].lower():
            out.append(word)
    return " ".join(out)


def _strip_press_enter(text: str) -> tuple[str, bool]:
    m = _PRESS_ENTER_RE.search(text)
    if not m:
        return text, False
    return text[: m.start()].strip(), True


def _punctuate(text: str) -> str:
    if not text:
        return text
    chars = list(text)
    cap_next = True
    for i, ch in enumerate(chars):
        if cap_next and ch.isalpha():
            chars[i] = ch.upper()
            cap_next = False
        elif ch in _END_MARKS:
            cap_next = True
    text = "".join(chars)
    if text[-1] not in _END_MARKS:
        text += "."
    return text
