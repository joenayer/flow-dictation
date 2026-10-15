"""Table-driven tests for flow.cleanup.clean (pure, headless)."""

from __future__ import annotations

import pytest

from flow.cleanup import clean
from flow.config import Settings


def S(**kwargs) -> Settings:
    return Settings(**kwargs)


CLEAN_CASES = [
    ("strip / punctuate", "  hello world  ", S(), "Hello world."),
    ("empty", "   ", S(), ""),
    ("fillers dropped", "um hello uh world", S(), "Hello world."),
    ("fillers case", "UM hello Umm HMM world", S(), "Hello world."),
    ("fillers with comma", "Um, hello", S(), "Hello."),
    ("filler not inside human", "human um summer", S(), "Human summer."),
    ("filler not inside the", "the other", S(), "The other."),
    (
        "fillers disabled",
        "um hello",
        S(cleanup_fillers=False, cleanup_punctuate=False),
        "um hello",
    ),
    ("adjacent dupes", "the the cat", S(), "The cat."),
    ("triple dupes", "yes yes yes", S(), "Yes."),
    ("dupes keep first case", "The the cat", S(cleanup_punctuate=False), "The cat"),
    (
        "space before period",
        "hello .",
        S(cleanup_punctuate=False),
        "hello.",
    ),
    (
        "space before comma",
        "hello , world",
        S(cleanup_punctuate=False),
        "hello, world",
    ),
    (
        "space before excl",
        "wow !",
        S(cleanup_punctuate=False),
        "wow!",
    ),
    (
        "punctuate off",
        "hello world",
        S(cleanup_punctuate=False),
        "hello world",
    ),
    ("already has bang", "hello world!", S(), "Hello world!"),
    ("already has question", "are you there?", S(), "Are you there?"),
    ("sentence starts", "hello. goodbye", S(), "Hello. Goodbye."),
    (
        "press enter on",
        "send this press enter",
        S(press_enter_phrase=True),
        "Send this.\n",
    ),
    (
        "press enter case",
        "send this PRESS ENTER",
        S(press_enter_phrase=True),
        "Send this.\n",
    ),
    (
        "press enter without punctuate",
        "send this press enter",
        S(press_enter_phrase=True, cleanup_punctuate=False),
        "send this\n",
    ),
    (
        "press enter disabled keeps phrase",
        "send this press enter",
        S(press_enter_phrase=False),
        "Send this press enter.",
    ),
    (
        "press enter only",
        "press enter",
        S(press_enter_phrase=True, cleanup_punctuate=False),
        "\n",
    ),
    ("fillers only", "um uh er ah", S(), ""),
    (
        "punct colon space",
        "note : hi",
        S(cleanup_punctuate=False),
        "note: hi",
    ),
    (
        "punct semicolon space",
        "wait ; go",
        S(cleanup_punctuate=False),
        "wait; go",
    ),
]


@pytest.mark.parametrize(
    "label,text,settings,expected",
    CLEAN_CASES,
    ids=[c[0] for c in CLEAN_CASES],
)
def test_clean(label: str, text: str, settings: Settings, expected: str) -> None:
    del label
    assert clean(text, settings) == expected
