"""Autorepeat suppression: a held grabbed key must yield one DOWN/UP pair."""

import os
import time
from types import SimpleNamespace

from Xlib import X

from flow.hotkey_base import Action
from flow.hotkey_x11 import X11Backend

KEYCODE = 40
MODS = X.ControlMask | X.Mod4Mask
TABLE = [(KEYCODE, MODS, "ptt", False)]


def _evt(etype, keycode=KEYCODE):
    return SimpleNamespace(type=etype, detail=keycode, state=MODS)


class _FakeDpy:
    """Minimal display stub for _swallow_strobe (pipe fd never readable)."""

    def __init__(self, queued):
        self._queued = list(queued)
        self._rfd, self._wfd = os.pipe()

    def pending_events(self):
        return len(self._queued)

    def next_event(self):
        return self._queued.pop(0)

    def fileno(self):
        return self._rfd

    def close(self):
        os.close(self._rfd)
        os.close(self._wfd)


def test_strobe_pair_swallowed():
    backend = X11Backend()
    dpy = _FakeDpy([_evt(X.KeyPress)])
    try:
        assert backend._swallow_strobe(dpy, _evt(X.KeyRelease), []) is True
    finally:
        dpy.close()


def test_genuine_release_passes_through():
    backend = X11Backend()
    dpy = _FakeDpy([])
    try:
        t0 = time.monotonic()
        assert backend._swallow_strobe(dpy, _evt(X.KeyRelease), []) is False
        assert 0.02 <= time.monotonic() - t0 < 0.5
    finally:
        dpy.close()


def test_repeat_press_within_window_ignored():
    backend = X11Backend()
    seen: list[Action] = []
    backend._dispatch = seen.append
    backend._handle_event(_evt(X.KeyPress), TABLE)
    backend._handle_event(_evt(X.KeyRelease), TABLE)
    backend._handle_event(_evt(X.KeyPress), TABLE)  # ~0ms later: strobe
    assert seen == [Action.PTT_DOWN, Action.PTT_UP]


def test_fast_double_tap_still_registers():
    backend = X11Backend()
    seen: list[Action] = []
    backend._dispatch = seen.append
    backend._handle_event(_evt(X.KeyPress), TABLE)
    backend._handle_event(_evt(X.KeyRelease), TABLE)
    time.sleep(0.12)  # human second tap, well outside the 30ms window
    backend._handle_event(_evt(X.KeyPress), TABLE)
    assert Action.HANDSFREE_TOGGLE in seen


def test_cancel_matching_requires_configured_modifiers():
    """Bare cancel fires with any mods; modified cancel needs exact mods."""
    from flow.hotkey_x11 import X11Backend

    backend = X11Backend()
    bare = [(KEYCODE, 0, "cancel", True)]
    assert backend._match_kind(KEYCODE, MODS, bare) == "cancel"
    modified = [(KEYCODE, MODS, "cancel", False)]
    assert backend._match_kind(KEYCODE, MODS, modified) == "cancel"
    assert backend._match_kind(KEYCODE, 0, modified) is None


def test_cancel_compile_marks_only_bare_any_mod():
    from flow.config import Settings
    from flow.hotkey_x11 import X11Backend

    backend = X11Backend()
    rows = backend._compile_bindings(Settings(cancel_key="Escape"))
    cancel_rows = [r for r in rows if r[2] == "cancel"]
    assert cancel_rows and all(r[3] is True for r in cancel_rows)
    rows = backend._compile_bindings(Settings(cancel_key="Ctrl+Q"))
    cancel_rows = [r for r in rows if r[2] == "cancel"]
    assert cancel_rows and all(r[3] is False for r in cancel_rows)
