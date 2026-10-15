"""Live typer checks. Strictly skipped without a display and/or tools.

These tests must not inject keystrokes into the focused window.
"""

from __future__ import annotations

import os
import shutil

import pytest

from flow.type_clipboard import ClipboardTyper
from flow.type_wtype import WtypeTyper
from flow.type_xdotool import XdotoolTyper
from flow.type_xlib import XlibTyper


def _xlib_display_ok() -> bool:
    if not os.environ.get("DISPLAY"):
        return False
    try:
        from Xlib import display

        disp = display.Display()
        ok = disp.has_extension("XTEST")
        disp.close()
        return bool(ok)
    except Exception:
        return False


needs_display = pytest.mark.skipif(
    not os.environ.get("DISPLAY"), reason="needs display"
)
needs_xlib = pytest.mark.skipif(not _xlib_display_ok(), reason="needs display")
needs_xdotool = pytest.mark.skipif(
    shutil.which("xdotool") is None or not os.environ.get("DISPLAY"),
    reason="needs display and xdotool",
)
needs_wtype = pytest.mark.skipif(
    shutil.which("wtype") is None, reason="needs wtype"
)
needs_clipboard = pytest.mark.skipif(
    shutil.which("xclip") is None and shutil.which("xsel") is None,
    reason="needs xclip or xsel",
)


@needs_xdotool
def test_xdotool_live_available_and_rejects_non_ascii() -> None:
    assert XdotoolTyper.available() is True
    assert XdotoolTyper().type_text("naïve") is False


@needs_xlib
def test_xlib_live_available_and_rejects_non_ascii() -> None:
    assert XlibTyper.available() is True
    assert XlibTyper().type_text("é") is False
    assert XlibTyper().type_text("hello\t") is False


@needs_wtype
def test_wtype_live_available() -> None:
    assert WtypeTyper.available() is True


@needs_clipboard
def test_clipboard_live_copy_roundtrip() -> None:
    text = "flow-linux-clipboard-test-7f3a"
    assert ClipboardTyper.available() is True
    assert ClipboardTyper().type_text(text) is True

    import subprocess

    xclip = shutil.which("xclip")
    if xclip is not None:
        out = subprocess.run(
            [xclip, "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert out.returncode == 0
        assert out.stdout == text
        return
    xsel = shutil.which("xsel")
    assert xsel is not None
    out = subprocess.run(
        [xsel, "--clipboard", "--output"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0
    assert out.stdout == text


@needs_display
def test_live_skip_gate_sees_display() -> None:
    """Sanity: skipif above is display-gated; this file is not headless-only."""
    assert os.environ.get("DISPLAY")
