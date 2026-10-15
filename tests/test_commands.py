"""Table-driven tests for flow.commands.handle_command (pure, headless)."""

from __future__ import annotations

import datetime

import pytest

from flow.commands import CommandResult, handle_command
from flow.config import Settings

S = Settings()

COMMAND_CASES = [
    ("no prefix", "please type this", False, ""),
    ("prefix in the middle", "please hey flow new line", False, ""),
    ("not flower", "hey flower new line", False, ""),
    ("prefix only", "hey flow", False, ""),
    ("unknown", "hey flow dance", False, ""),
    ("new line", "hey flow new line", True, "\n"),
    ("new line case", "HEY FLOW NEW LINE", True, "\n"),
    ("new line padded", "  hey flow new line  ", True, "\n"),
    ("new paragraph", "hey flow new paragraph", True, "\n\n"),
    ("press enter", "hey flow press enter", True, "\n"),
    ("type words", "hey flow type Hello World", True, "Hello World"),
    ("type preserves case", "hey flow type McDonald", True, "McDonald"),
    ("type after TYPE", "hey flow TYPE Hello", True, "Hello"),
    ("type without words", "hey flow type", False, ""),
    ("unrelated transcript", "hello world", False, ""),
]


@pytest.mark.parametrize(
    "label,transcript,handled,message",
    COMMAND_CASES,
    ids=[c[0] for c in COMMAND_CASES],
)
def test_handle_command(
    label: str, transcript: str, handled: bool, message: str
) -> None:
    del label
    result = handle_command(transcript, S)
    assert result == CommandResult(handled=handled, message=message)


def test_date_is_iso_today() -> None:
    result = handle_command("hey flow date", S)
    assert result.handled is True
    assert result.message == datetime.date.today().isoformat()
    datetime.date.fromisoformat(result.message)


def test_time_is_hh_mm_24h() -> None:
    result = handle_command("hey flow time", S)
    assert result.handled is True
    parsed = datetime.datetime.strptime(result.message, "%H:%M")
    now = datetime.datetime.now()
    assert abs((now.hour * 60 + now.minute) - (parsed.hour * 60 + parsed.minute)) <= 1


NEW_VERB_CASES = [
    (
        "delete last word",
        "hey flow delete last word",
        True,
        "",
        "Ctrl+BackSpace",
    ),
    (
        "delete last word case",
        "HEY FLOW DELETE LAST WORD",
        True,
        "",
        "Ctrl+BackSpace",
    ),
    ("undo", "hey flow undo", True, "", "Ctrl+Z"),
    ("undo case", "hey flow UNDO", True, "", "Ctrl+Z"),
    ("select all", "hey flow select all", True, "", "Ctrl+A"),
    ("select all case", "hey flow Select All", True, "", "Ctrl+A"),
    ("spell", "hey flow spell hello", True, "h e l l o", ""),
    ("spell case", "hey flow spell McD", True, "M c D", ""),
    ("spell two words", "hey flow spell hi yo", True, "h i   y o", ""),
    ("spell after SPELL", "hey flow SPELL Ab", True, "A b", ""),
    ("shout", "hey flow shout hello world", True, "HELLO WORLD", ""),
    ("shout case", "hey flow shout McDonald", True, "MCDONALD", ""),
    ("small", "hey flow small Hello", True, "hello", ""),
    ("small already lower", "hey flow small already", True, "already", ""),
    ("spell without words", "hey flow spell", False, "", ""),
    ("shout without words", "hey flow shout", False, "", ""),
    ("small without words", "hey flow small", False, "", ""),
]


@pytest.mark.parametrize(
    "label,transcript,handled,message,keys",
    NEW_VERB_CASES,
    ids=[c[0] for c in NEW_VERB_CASES],
)
def test_new_verbs(
    label: str, transcript: str, handled: bool, message: str, keys: str
) -> None:
    del label
    result = handle_command(transcript, S)
    assert result == CommandResult(handled=handled, message=message, keys=keys)
