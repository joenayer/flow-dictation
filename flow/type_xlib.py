"""X11 typer backend using python-xlib XTEST (no external binary)."""

from __future__ import annotations

import os
import re

from flow.typer_base import TYPER_BACKENDS, TyperBackend

try:
    from Xlib import XK, X
    from Xlib import display as xdisplay
except ImportError:  # pragma: no cover
    XK = None  # type: ignore[assignment]
    X = None  # type: ignore[assignment]
    xdisplay = None  # type: ignore[assignment]


def _allowed_char(ch: str) -> bool:
    if ch == "\n":
        return True
    return 32 <= ord(ch) <= 126


def _allowed_text(text: str) -> bool:
    return all(_allowed_char(ch) for ch in text)


def _open_display():
    if xdisplay is None or X is None:
        return None
    if not os.environ.get("DISPLAY"):
        return None
    try:
        disp = xdisplay.Display()
    except Exception:
        return None
    try:
        if not disp.has_extension("XTEST"):
            disp.close()
            return None
    except Exception:
        try:
            disp.close()
        except Exception:
            pass
        return None
    return disp


_MOD_TOKENS: dict[str, int] = {}
if XK is not None:
    _MOD_TOKENS = {
        "ctrl": XK.XK_Control_L,
        "control": XK.XK_Control_L,
        "shift": XK.XK_Shift_L,
        "alt": XK.XK_Alt_L,
        "super": XK.XK_Super_L,
    }

_KEY_ALIASES: dict[str, str] = {
    "backspace": "BackSpace",
    "bksp": "BackSpace",
    "enter": "Return",
    "return": "Return",
    "esc": "Escape",
    "escape": "Escape",
    "space": "space",
    "tab": "Tab",
    "del": "Delete",
    "delete": "Delete",
}


def _keysym_for(ch: str) -> int | None:
    if XK is None:
        return None
    if ch == "\n":
        return XK.XK_Return
    if 32 <= ord(ch) <= 126:
        return ord(ch)
    return None


def _keysym_for_token(token: str) -> int:
    """Map a non-modifier keyspec token to an X keysym. Raises ValueError."""
    if XK is None:
        raise ValueError("Xlib XK unavailable")
    alias = _KEY_ALIASES.get(token.lower())
    if alias:
        name = alias
    elif len(token) == 1 and token.isalpha():
        name = token.lower()
    elif re.fullmatch(r"[fF]\d{1,2}", token):
        name = "F" + token[1:]
    else:
        name = token
    keysym = XK.string_to_keysym(name)
    if not keysym:
        keysym = XK.string_to_keysym(name[:1].upper() + name[1:]) if name else 0
    if not keysym:
        raise ValueError(f"unknown key {token!r}")
    return keysym


def parse_keyspec(keyspec: str) -> tuple[tuple[int, ...], int]:
    """Parse Xlib-style ``Ctrl+BackSpace`` into ``(modifier_keysyms, keysym)``.

    Tokens are joined by ``+``. Allowed modifiers: Ctrl/Control, Shift, Alt,
    Super. Exactly one non-modifier key is required. Raises ``ValueError``
    for empty specs, empty tokens, modifier-only chords, extra keys, and
    unknown keys.
    """
    if XK is None:
        raise ValueError("Xlib XK unavailable")
    if keyspec is None or not str(keyspec).strip():
        raise ValueError("empty keyspec")
    tokens = [part.strip() for part in str(keyspec).split("+")]
    if any(token == "" for token in tokens):
        raise ValueError(f"invalid keyspec {keyspec!r}: empty token")

    mods: list[int] = []
    seen_mods: set[int] = set()
    key_keysym: int | None = None
    for token in tokens:
        mod = _MOD_TOKENS.get(token.lower())
        if mod is not None:
            if mod in seen_mods:
                raise ValueError(
                    f"invalid keyspec {keyspec!r}: duplicate modifier {token!r}"
                )
            seen_mods.add(mod)
            mods.append(mod)
            continue
        if key_keysym is not None:
            raise ValueError(f"invalid keyspec {keyspec!r}: extra key {token!r}")
        key_keysym = _keysym_for_token(token)
    if key_keysym is None:
        raise ValueError(f"invalid keyspec {keyspec!r}: modifier-only")
    return tuple(mods), key_keysym


def _keycode_for(disp, keysym: int) -> tuple[int, int] | None:
    """Return ``(keycode, group_index)`` preferring unshifted index 0/1."""
    try:
        pairs = list(disp.keysym_to_keycodes(keysym))
    except Exception:
        pairs = []
    for kc, idx in pairs:
        if kc and idx in (0, 1):
            return kc, idx
    try:
        kc = disp.keysym_to_keycode(keysym)
    except Exception:
        kc = 0
    if not kc:
        return None
    return kc, 0


def _events_for_char(disp, ch: str) -> list[tuple[int, int]] | None:
    if X is None or XK is None:
        return None
    keysym = _keysym_for(ch)
    if keysym is None:
        return None
    try:
        pairs = list(disp.keysym_to_keycodes(keysym))
    except Exception:
        return None
    keycode = None
    index = None
    for kc, idx in pairs:
        if idx in (0, 1):
            keycode, index = kc, idx
            break
    if not keycode:
        return None
    events: list[tuple[int, int]] = []
    shift_code = 0
    if index == 1:
        try:
            shift_code = disp.keysym_to_keycode(XK.XK_Shift_L)
        except Exception:
            shift_code = 0
        if not shift_code:
            return None
        events.append((X.KeyPress, shift_code))
    events.append((X.KeyPress, keycode))
    events.append((X.KeyRelease, keycode))
    if index == 1:
        events.append((X.KeyRelease, shift_code))
    return events


def _events_for_keyspec(disp, keyspec: str) -> list[tuple[int, int]] | None:
    if X is None or XK is None:
        return None
    try:
        mod_keysyms, key_keysym = parse_keyspec(keyspec)
    except ValueError:
        return None
    mod_codes: list[int] = []
    for mks in mod_keysyms:
        found = _keycode_for(disp, mks)
        if found is None:
            return None
        mod_codes.append(found[0])
    key_found = _keycode_for(disp, key_keysym)
    if key_found is None:
        return None
    keycode, index = key_found
    extra_shift = 0
    shift_held = XK.XK_Shift_L in mod_keysyms
    if index == 1 and not shift_held:
        try:
            extra_shift = disp.keysym_to_keycode(XK.XK_Shift_L)
        except Exception:
            extra_shift = 0
        if not extra_shift:
            return None
    events: list[tuple[int, int]] = []
    if extra_shift:
        events.append((X.KeyPress, extra_shift))
    for code in mod_codes:
        events.append((X.KeyPress, code))
    events.append((X.KeyPress, keycode))
    events.append((X.KeyRelease, keycode))
    for code in reversed(mod_codes):
        events.append((X.KeyRelease, code))
    if extra_shift:
        events.append((X.KeyRelease, extra_shift))
    return events


class XlibTyper(TyperBackend):
    """Type ascii printable + newline via XTEST fake key events."""

    name = "xlib"

    @classmethod
    def available(cls) -> bool:
        disp = _open_display()
        if disp is None:
            return False
        try:
            disp.close()
        except Exception:
            pass
        return True

    def type_text(self, text: str) -> bool:
        if not _allowed_text(text):
            return False
        disp = _open_display()
        if disp is None:
            return False
        try:
            queued: list[tuple[int, int]] = []
            for ch in text:
                evs = _events_for_char(disp, ch)
                if evs is None:
                    return False
                queued.extend(evs)
            for event_type, detail in queued:
                disp.xtest_fake_input(event_type, detail)
            disp.sync()
            return True
        except Exception:
            return False
        finally:
            try:
                disp.close()
            except Exception:
                pass

    def press_keys(self, keyspec: str) -> bool:
        try:
            parse_keyspec(keyspec)
        except ValueError:
            return False
        disp = _open_display()
        if disp is None:
            return False
        try:
            events = _events_for_keyspec(disp, keyspec)
            if events is None:
                return False
            for event_type, detail in events:
                disp.xtest_fake_input(event_type, detail)
            disp.sync()
            return True
        except Exception:
            return False
        finally:
            try:
                disp.close()
            except Exception:
                pass


TYPER_BACKENDS["xlib"] = XlibTyper
