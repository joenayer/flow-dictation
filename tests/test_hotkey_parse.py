"""Headless parse/reject table for X11 shortcuts."""

from __future__ import annotations

import pytest
from Xlib import X, XK

from flow.hotkey_base import HOTKEY_BACKENDS, Action
from flow.hotkey_x11 import (
    PTT_DOUBLE_TAP_S,
    X11Backend,
    lock_mask_variants,
    parse_shortcut,
    resolve_ptt_down,
)
from flow.hotkey_wayland import WaylandBackend


PARSE_CASES = [
    ("Ctrl+Super+d", X.ControlMask | X.Mod4Mask, XK.XK_d),
    ("Ctrl+Super+h", X.ControlMask | X.Mod4Mask, XK.XK_h),
    ("Ctrl+Super+g", X.ControlMask | X.Mod4Mask, XK.XK_g),
    ("Ctrl+Super+v", X.ControlMask | X.Mod4Mask, XK.XK_v),
    ("Ctrl+Super+c", X.ControlMask | X.Mod4Mask, XK.XK_c),
    ("Control+Win+d", X.ControlMask | X.Mod4Mask, XK.XK_d),
    ("Escape", 0, XK.XK_Escape),
    ("Esc", 0, XK.XK_Escape),
    ("F5", 0, XK.XK_F5),
    ("f12", 0, XK.XK_F12),
    ("Shift+Alt+z", X.ShiftMask | X.Mod1Mask, XK.XK_z),
    ("Ctrl+Escape", X.ControlMask, XK.XK_Escape),
    ("Super+F5", X.Mod4Mask, XK.XK_F5),
]


REJECT_CASES = [
    ("d", "letter"),
    ("D", "letter"),
    ("a", "letter"),
    ("Button1", "mouse"),
    ("button2", "mouse"),
    ("Ctrl+Button1", "mouse"),
    ("Mouse1", "mouse"),
    ("Btn3", "mouse"),
    ("", "empty"),
    ("   ", "empty"),
    ("Ctrl+Super", "non-modifier"),
    ("NotAKey", "unknown"),
    ("Ctrl++d", "empty"),
]


@pytest.mark.parametrize("spec, modmask, keysym", PARSE_CASES)
def test_parse_shortcut_table(
    spec: str, modmask: int, keysym: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISPLAY", raising=False)
    assert parse_shortcut(spec) == (modmask, keysym)


@pytest.mark.parametrize("spec, kind", REJECT_CASES)
def test_parse_shortcut_rejects(spec: str, kind: str) -> None:
    with pytest.raises(ValueError) as info:
        parse_shortcut(spec)
    message = str(info.value).lower()
    if kind == "letter":
        assert "letter" in message
    elif kind == "mouse":
        assert "mouse" in message
    elif kind == "empty":
        assert "empty" in message
    elif kind == "non-modifier":
        assert "non-modifier" in message or "modifier" in message
    elif kind == "unknown":
        assert "unknown" in message


def test_lock_mask_variants_include_caps_and_numlock() -> None:
    variants = lock_mask_variants(X.ControlMask | X.Mod4Mask)
    assert len(variants) == 4
    assert X.ControlMask | X.Mod4Mask in variants
    assert X.ControlMask | X.Mod4Mask | X.LockMask in variants
    assert X.ControlMask | X.Mod4Mask | X.Mod2Mask in variants
    assert X.ControlMask | X.Mod4Mask | X.LockMask | X.Mod2Mask in variants


def test_double_tap_emits_toggle_instead_of_second_down() -> None:
    action, last = resolve_ptt_down(None, 1.0)
    assert action is Action.PTT_DOWN
    action, last = resolve_ptt_down(last, 1.0 + PTT_DOUBLE_TAP_S / 2)
    assert action is Action.HANDSFREE_TOGGLE
    assert last is None
    action, last = resolve_ptt_down(last, 2.0)
    assert action is Action.PTT_DOWN
    action, _ = resolve_ptt_down(last, 2.0 + PTT_DOUBLE_TAP_S + 0.01)
    assert action is Action.PTT_DOWN


def test_backends_register() -> None:
    assert HOTKEY_BACKENDS["x11"] is X11Backend
    assert HOTKEY_BACKENDS["wayland"] is WaylandBackend


def test_wayland_start_points_at_portal_gap() -> None:
    from flow.config import Settings

    with pytest.raises(RuntimeError, match="xdg-desktop-portal GlobalShortcuts") as info:
        WaylandBackend().start(Settings(), lambda action: None)
    assert "v1" in str(info.value).lower() or "not implemented" in str(info.value).lower()
