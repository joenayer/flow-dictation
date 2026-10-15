"""Registry and availability selection; no real display or binaries required."""

from __future__ import annotations

import pytest

from flow.typer_base import TYPER_BACKENDS
from flow.type_clipboard import COPIED_MESSAGE, ClipboardTyper
from flow.type_select import (
    PREFERRED_ORDER,
    available_backend_names,
    select_typer,
    select_typer_name,
)
from flow.type_wtype import WtypeTyper
from flow.type_xdotool import XdotoolTyper
from flow.type_xlib import XlibTyper


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
            97: [(38, 0)],  # a
            65: [(38, 1)],  # A
            33: [(10, 1)],  # !
            32: [(65, 0)],  # space
            65293: [(36, 0)],  # Return
        }
        return table.get(keysym, [])

    def keysym_to_keycode(self, keysym: int) -> int:
        if keysym == 0xFFE1:  # XK_Shift_L
            return 50
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


@pytest.fixture
def no_display(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr("Xlib.display.Display", BoomDisplay)


def test_registry_has_all_backends() -> None:
    for name in ("xdotool", "xlib", "wtype", "clipboard"):
        assert name in TYPER_BACKENDS
    assert TYPER_BACKENDS["xdotool"] is XdotoolTyper
    assert TYPER_BACKENDS["xlib"] is XlibTyper
    assert TYPER_BACKENDS["wtype"] is WtypeTyper
    assert TYPER_BACKENDS["clipboard"] is ClipboardTyper
    assert PREFERRED_ORDER == ("xdotool", "xlib", "wtype", "clipboard")


def test_select_prefers_xdotool(monkeypatch, no_display) -> None:
    monkeypatch.setattr("shutil.which", _which_only("xdotool", "wtype", "xclip"))
    assert select_typer_name() == "xdotool"
    inst = select_typer()
    assert isinstance(inst, XdotoolTyper)


def test_select_xlib_when_no_binaries(monkeypatch) -> None:
    monkeypatch.setattr("shutil.which", _which_only())
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("Xlib.display.Display", FakeDisplay)
    assert select_typer_name() == "xlib"
    assert isinstance(select_typer(), XlibTyper)


def test_select_wtype(monkeypatch, no_display) -> None:
    monkeypatch.setattr("shutil.which", _which_only("wtype", "xclip"))
    assert select_typer_name() == "wtype"
    assert isinstance(select_typer(), WtypeTyper)


def test_select_clipboard_xclip(monkeypatch, no_display) -> None:
    monkeypatch.setattr("shutil.which", _which_only("xclip"))
    assert select_typer_name() == "clipboard"
    assert isinstance(select_typer(), ClipboardTyper)


def test_select_clipboard_xsel(monkeypatch, no_display) -> None:
    monkeypatch.setattr("shutil.which", _which_only("xsel"))
    assert available_backend_names() == ["clipboard"]
    assert select_typer_name() == "clipboard"


def test_select_none(monkeypatch, no_display) -> None:
    monkeypatch.setattr("shutil.which", _which_only())
    assert available_backend_names() == []
    assert select_typer_name() is None
    assert select_typer() is None


def test_xdotool_missing_or_non_ascii(monkeypatch, no_display) -> None:
    monkeypatch.setattr("shutil.which", _which_only())
    assert XdotoolTyper.available() is False
    assert XdotoolTyper().type_text("hello") is False

    monkeypatch.setattr("shutil.which", _which_only("xdotool"))
    assert XdotoolTyper.available() is True
    assert XdotoolTyper().type_text("naïve") is False
    assert XdotoolTyper().type_text("café") is False


def test_xdotool_invokes_documented_argv(monkeypatch, no_display) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return _Ok()

    monkeypatch.setattr("shutil.which", _which_only("xdotool"))
    monkeypatch.setattr("subprocess.run", fake_run)
    assert XdotoolTyper().type_text("hello") is True
    assert calls[0][1:] == ["type", "--clearmodifiers", "--delay", "0", "--", "hello"]


def test_wtype_missing_and_stdin(monkeypatch, no_display) -> None:
    monkeypatch.setattr("shutil.which", _which_only())
    assert WtypeTyper.available() is False
    assert WtypeTyper().type_text("hello") is False

    seen: dict = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = list(cmd)
        seen["input"] = kwargs.get("input")
        return _Ok()

    monkeypatch.setattr("shutil.which", _which_only("wtype"))
    monkeypatch.setattr("subprocess.run", fake_run)
    assert WtypeTyper.available() is True
    assert WtypeTyper().type_text("typed via stdin") is True
    assert seen["cmd"] == ["/usr/bin/wtype"]
    assert seen["input"] == "typed via stdin"


def test_clipboard_true_only_if_copy_happened(monkeypatch, no_display) -> None:
    monkeypatch.setattr("shutil.which", _which_only())
    assert ClipboardTyper.available() is False
    assert ClipboardTyper().type_text("no tools") is False

    monkeypatch.setattr("shutil.which", _which_only("xclip"))
    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Fail())
    assert ClipboardTyper.available() is True
    assert ClipboardTyper().type_text("fail copy") is False

    monkeypatch.setattr("subprocess.run", lambda *a, **k: _Ok())
    assert ClipboardTyper().type_text("ok copy") is True
    assert COPIED_MESSAGE == "copied, paste manually"
    assert ClipboardTyper.message == "copied, paste manually"


def test_xlib_false_without_display(monkeypatch) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr("Xlib.display.Display", BoomDisplay)
    assert XlibTyper.available() is False
    assert XlibTyper().type_text("hello") is False
    assert XlibTyper().type_text("naïve") is False
    assert XlibTyper().type_text("tab\t") is False


def test_xlib_types_ascii_printable_and_newline(monkeypatch) -> None:
    rec = FakeDisplay()
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("Xlib.display.Display", lambda *a, **k: rec)
    typer = XlibTyper()
    assert typer.available() is True
    assert typer.type_text("A!\n") is True
    # Shift+A, Shift+1, Return — KeyPress=2, KeyRelease=3
    assert rec.events == [
        (2, 50),
        (2, 38),
        (3, 38),
        (3, 50),
        (2, 50),
        (2, 10),
        (3, 10),
        (3, 50),
        (2, 36),
        (3, 36),
    ]


def test_xlib_rejects_non_ascii_even_with_display(monkeypatch) -> None:
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr("Xlib.display.Display", FakeDisplay)
    assert XlibTyper().type_text("é") is False
    assert XlibTyper().type_text("hello\tworld") is False
