"""Headless keyspec parse + press_keys tests. Live XTEST is opt-in only."""

from __future__ import annotations

import os

import pytest
from Xlib import XK

from flow.type_clipboard import ClipboardTyper
from flow.type_wtype import WtypeTyper
from flow.type_xdotool import XdotoolTyper
from flow.type_xlib import XlibTyper, parse_keyspec
from flow.typer_base import TyperBackend


PARSE_CASES = [
    ("Ctrl+BackSpace", (XK.XK_Control_L,), XK.XK_BackSpace),
    ("Ctrl+Z", (XK.XK_Control_L,), XK.XK_z),
    ("Ctrl+A", (XK.XK_Control_L,), XK.XK_a),
    ("ctrl+z", (XK.XK_Control_L,), XK.XK_z),
    ("Control+BackSpace", (XK.XK_Control_L,), XK.XK_BackSpace),
    ("Ctrl+Shift+Z", (XK.XK_Control_L, XK.XK_Shift_L), XK.XK_z),
    ("Shift+Alt+z", (XK.XK_Shift_L, XK.XK_Alt_L), XK.XK_z),
    ("Alt+Tab", (XK.XK_Alt_L,), XK.XK_Tab),
    ("Super+a", (XK.XK_Super_L,), XK.XK_a),
    ("BackSpace", (), XK.XK_BackSpace),
]


INVALID_SPECS = [
    "",
    "   ",
    "Ctrl+",
    "+A",
    "Ctrl++A",
    "Ctrl",
    "Ctrl+Shift",
    "Ctrl+A+B",
    "NotAKey",
    "Ctrl+NotAKey",
    "Ctrl+Ctrl+A",
]


class _Ok:
    returncode = 0


class _Fail:
    returncode = 1


class FakeDisplay:
    """Minimal Display that looks like a working XTEST server."""

    def __init__(self, *args, **kwargs) -> None:
        self.events: list[tuple[int, int]] = []

    def has_extension(self, name: str) -> bool:
        return name == "XTEST"

    def keysym_to_keycodes(self, keysym: int):
        table = {
            XK.XK_Control_L: [(37, 0)],
            XK.XK_Shift_L: [(50, 0)],
            XK.XK_Alt_L: [(64, 0)],
            XK.XK_Super_L: [(133, 0)],
            XK.XK_BackSpace: [(22, 0)],
            XK.XK_z: [(52, 0)],
            XK.XK_a: [(38, 0)],
            XK.XK_Tab: [(23, 0)],
        }
        return table.get(keysym, [])

    def keysym_to_keycode(self, keysym: int) -> int:
        pairs = list(self.keysym_to_keycodes(keysym))
        return pairs[0][0] if pairs else 0

    def xtest_fake_input(self, event_type, detail=0, **kwargs) -> None:
        self.events.append((event_type, detail))

    def sync(self) -> None:
        pass

    def close(self) -> None:
        pass


class BoomDisplay:
    def __init__(self, *args, **kwargs) -> None:
        raise RuntimeError("no display")


def _which_only(*present: str):
    present_set = set(present)

    def which(cmd: str):
        return f"/usr/bin/{cmd}" if cmd in present_set else None

    return which


@pytest.mark.parametrize("spec, mods, keysym", PARSE_CASES)
def test_parse_keyspec_table(spec: str, mods: tuple[int, ...], keysym: int) -> None:
    assert parse_keyspec(spec) == (mods, keysym)


@pytest.mark.parametrize("spec", INVALID_SPECS)
def test_parse_keyspec_invalid(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_keyspec(spec)


def test_default_press_keys_is_false() -> None:
    class Dummy(TyperBackend):
        def type_text(self, text: str) -> bool:
            return False

    assert Dummy().press_keys("Ctrl+Z") is False
    assert ClipboardTyper().press_keys("Ctrl+Z") is False
    assert WtypeTyper().press_keys("Ctrl+A") is False


def test_xdotool_press_keys_missing(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", _which_only())
    assert XdotoolTyper().press_keys("Ctrl+Z") is False


def test_xdotool_press_keys_empty(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", _which_only("xdotool"))
    assert XdotoolTyper().press_keys("") is False
    assert XdotoolTyper().press_keys("   ") is False


def test_xdotool_press_keys_invokes_key(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _Ok()

    monkeypatch.setattr("shutil.which", _which_only("xdotool"))
    monkeypatch.setattr("subprocess.run", fake_run)
    assert XdotoolTyper().press_keys("Ctrl+BackSpace") is True
    assert calls[0][1:] == ["key", "Ctrl+BackSpace"]


def test_xdotool_press_keys_nonzero(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", _which_only("xdotool"))
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Fail())
    assert XdotoolTyper().press_keys("Ctrl+Z") is False


def test_xlib_press_keys_false_without_display(monkeypatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr("Xlib.display.Display", BoomDisplay)
    assert XlibTyper().press_keys("Ctrl+Z") is False
    assert XlibTyper().press_keys("not a key") is False


def test_xlib_press_keys_emits_modifier_then_key(monkeypatch) -> None:
    rec = FakeDisplay()
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("Xlib.display.Display", lambda *a, **k: rec)
    typer = XlibTyper()
    assert typer.press_keys("Ctrl+Z") is True
    # Control_L then z; KeyPress=2, KeyRelease=3. No extra Shift for Ctrl+Z.
    assert rec.events == [
        (2, 37),
        (2, 52),
        (3, 52),
        (3, 37),
    ]


def test_xlib_press_keys_ctrl_backspace_and_a(monkeypatch) -> None:
    rec = FakeDisplay()
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("Xlib.display.Display", lambda *a, **k: rec)
    typer = XlibTyper()
    assert typer.press_keys("Ctrl+BackSpace") is True
    assert rec.events == [
        (2, 37),
        (2, 22),
        (3, 22),
        (3, 37),
    ]
    rec.events.clear()
    assert typer.press_keys("Ctrl+A") is True
    assert rec.events == [
        (2, 37),
        (2, 38),
        (3, 38),
        (3, 37),
    ]


def test_xlib_press_keys_invalid_spec_false(monkeypatch) -> None:
    rec = FakeDisplay()
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("Xlib.display.Display", lambda *a, **k: rec)
    assert XlibTyper().press_keys("Ctrl+Shift") is False
    assert rec.events == []


@pytest.mark.skipif(
    os.environ.get("FLOW_LIVE_KEYS") != "1",
    reason="live XTEST forbidden unless FLOW_LIVE_KEYS=1",
)
def test_live_xtest_press_keys() -> None:
    """Opt-in only: injects a real XTEST chord when FLOW_LIVE_KEYS=1."""
    assert XlibTyper().press_keys("Ctrl+A") is True
