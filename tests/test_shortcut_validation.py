"""Headless validate_shortcut tests (no display required)."""

from __future__ import annotations

import pytest

from flow.ui.settings import canonical_binding, find_conflicts, validate_shortcut


OK_CASES = [
    "Ctrl+Super+d",
    "Ctrl+Super+h",
    "Escape",
    "F5",
    "Ctrl+Super+c",
    "Ctrl+Super+v",
    "Shift+Alt+z",
    "Ctrl+Super+d,Ctrl+Super+e,Ctrl+Super+f,Ctrl+Super+g",
]


FAIL_CASES = [
    ("d", "letter"),
    ("a", "letter"),
    ("Ctrl+c", "reserved"),
    ("Ctrl+C", "reserved"),
    ("Ctrl+v", "reserved"),
    ("Ctrl+x", "reserved"),
    ("Ctrl+z", "reserved"),
    ("Ctrl+a", "reserved"),
    ("Ctrl+Shift+v", "reserved"),
    ("Ctrl+Alt+Shift+d", "3 keys"),
    ("Ctrl+Super+d,Ctrl+Super+e,Ctrl+Super+f,Ctrl+Super+g,Ctrl+Super+h", "4 bindings"),
    ("Button1", "mouse"),
    ("", "empty"),
    ("Ctrl+Super", "non-modifier"),
]


@pytest.mark.parametrize("spec", OK_CASES)
def test_validate_shortcut_accepts(spec: str) -> None:
    ok, reason = validate_shortcut(spec)
    assert ok is True, reason
    assert reason == ""


@pytest.mark.parametrize("spec, kind", FAIL_CASES)
def test_validate_shortcut_rejects(spec: str, kind: str) -> None:
    ok, reason = validate_shortcut(spec)
    assert ok is False
    assert reason
    lowered = reason.lower()
    if kind == "letter":
        assert "letter" in lowered
    elif kind == "reserved":
        assert "reserved" in lowered
    elif kind == "3 keys":
        assert "3" in lowered and "key" in lowered
    elif kind == "4 bindings":
        assert "4" in lowered and "binding" in lowered
    elif kind == "mouse":
        assert "mouse" in lowered
    elif kind == "empty":
        assert "empty" in lowered
    elif kind == "non-modifier":
        assert "non-modifier" in lowered or "modifier" in lowered


def test_validate_shortcut_returns_tuple() -> None:
    ok, reason = validate_shortcut("Escape")
    assert (ok, reason) == (True, "")
    ok, reason = validate_shortcut("d")
    assert ok is False
    assert isinstance(reason, str) and reason


def test_canonical_binding_normalizes_aliases_and_order() -> None:
    assert canonical_binding("Shift+Ctrl+W") == canonical_binding("Control+Shift+w")
    assert canonical_binding("Win+Space") == canonical_binding("Super+space")
    assert canonical_binding("Alt+W") != canonical_binding("Alt+E")


def test_find_conflicts_flags_duplicates_across_actions() -> None:
    values = {
        "ptt_shortcut": "Alt+W",
        "handsfree_shortcut": "Ctrl+Shift+W",
        "command_shortcut": "Alt+W",
        "paste_last_shortcut": "Alt+B",
        "copy_last_shortcut": "Alt+C",
        "cancel_key": "Escape",
    }
    conflicts = find_conflicts(values)
    assert "command_shortcut" in conflicts
    assert "Push-to-talk" in conflicts["command_shortcut"]
    assert "ptt_shortcut" not in conflicts  # first occurrence wins


def test_find_conflicts_clean_for_defaults() -> None:
    values = {
        "ptt_shortcut": "Alt+W",
        "handsfree_shortcut": "Alt+E",
        "command_shortcut": "Meta+G",
        "paste_last_shortcut": "Meta+B",
        "copy_last_shortcut": "Meta+Space",
        "cancel_key": "Escape",
    }
    assert find_conflicts(values) == {}


def test_find_conflicts_ignores_invalid_bindings() -> None:
    values = {
        "ptt_shortcut": "d",  # invalid: reported by validate_shortcut
        "handsfree_shortcut": "d",
        "command_shortcut": "Meta+G",
        "paste_last_shortcut": "Meta+B",
        "copy_last_shortcut": "Meta+Space",
        "cancel_key": "Escape",
    }
    assert find_conflicts(values) == {}


def _values(**overrides) -> dict:
    values = {
        "ptt_shortcut": "Alt+W",
        "handsfree_shortcut": "Alt+E",
        "command_shortcut": "Meta+G",
        "paste_last_shortcut": "Meta+B",
        "copy_last_shortcut": "Meta+Space",
        "cancel_key": "Escape",
    }
    values.update(overrides)
    return values


def test_find_conflicts_flags_alias_spellings() -> None:
    conflicts = find_conflicts(
        _values(ptt_shortcut="Alt+Enter", handsfree_shortcut="Alt+Return")
    )
    assert "handsfree_shortcut" in conflicts
    conflicts = find_conflicts(
        _values(ptt_shortcut="Alt+Backspace", handsfree_shortcut="Alt+Bksp")
    )
    assert "handsfree_shortcut" in conflicts


def test_find_conflicts_flags_bare_cancel_shadow() -> None:
    conflicts = find_conflicts(
        _values(ptt_shortcut="Alt+Esc", cancel_key="Escape")
    )
    assert "ptt_shortcut" in conflicts
    assert "Cancel" in conflicts["ptt_shortcut"]


def test_find_conflicts_clean_for_modified_cancel() -> None:
    assert (
        find_conflicts(_values(ptt_shortcut="Alt+Q", cancel_key="Ctrl+Q"))
        == {}
    )


def test_find_conflicts_flags_exact_modified_cancel_clash() -> None:
    conflicts = find_conflicts(
        _values(ptt_shortcut="Ctrl+Q", cancel_key="Ctrl+Q")
    )
    assert "cancel_key" in conflicts
