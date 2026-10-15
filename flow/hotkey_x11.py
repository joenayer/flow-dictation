"""X11 global hotkey backend (python-xlib).

``parse_shortcut`` is pure and does not open a Display, so it is safe to
call without ``$DISPLAY``. Grabbing and the event loop run in ``start``.
"""

from __future__ import annotations

import logging
import re
import select
import threading
import time
from collections.abc import Callable

from Xlib import X, XK, display as xdisplay

from .config import Settings
from .hotkey_base import HOTKEY_BACKENDS, Action, HotkeyBackend

log = logging.getLogger(__name__)

PTT_DOUBLE_TAP_S = 0.350

# CapsLock (Lock) + NumLock (Mod2) so grabs still fire with lock keys on.
_LOCK_EXTRAS = (
    0,
    X.LockMask,
    X.Mod2Mask,
    X.LockMask | X.Mod2Mask,
)

_MODIFIER_MASK = (
    X.ShiftMask | X.ControlMask | X.Mod1Mask | X.Mod3Mask | X.Mod4Mask
)

_MOD_NAMES: dict[str, int] = {
    "ctrl": X.ControlMask,
    "control": X.ControlMask,
    "ctl": X.ControlMask,
    "shift": X.ShiftMask,
    "alt": X.Mod1Mask,
    "option": X.Mod1Mask,
    "mod1": X.Mod1Mask,
    "super": X.Mod4Mask,
    "win": X.Mod4Mask,
    "windows": X.Mod4Mask,
    "cmd": X.Mod4Mask,
    "mod4": X.Mod4Mask,
    "meta": X.Mod4Mask,
}

_KEY_ALIASES: dict[str, str] = {
    "esc": "Escape",
    "escape": "Escape",
    "enter": "Return",
    "return": "Return",
    "space": "space",
    "tab": "Tab",
    "backspace": "BackSpace",
    "bksp": "BackSpace",
    "del": "Delete",
    "delete": "Delete",
    "plus": "plus",
    "minus": "minus",
}

_MOUSE_TOKEN = re.compile(
    r"^(button\d+|btn\d+|mouse\d+|pointer_button\d+)$",
    re.IGNORECASE,
)

_KIND_PTT = "ptt"
_KIND_HANDSFREE = "handsfree"
_KIND_COMMAND = "command"
_KIND_PASTE = "paste"
_KIND_COPY = "copy"
_KIND_CANCEL = "cancel"


def lock_mask_variants(modmask: int) -> tuple[int, ...]:
    """Return grab modifier masks covering CapsLock/NumLock on and off."""
    return tuple(modmask | extra for extra in _LOCK_EXTRAS)


def active_window_id() -> int | None:
    """Best-effort active window id, or None when unknown.

    Opens a throwaway Display, reads ``_NET_ACTIVE_WINDOW``, closes it.
    Never raises: focus tracking is advisory only (insert review guard).
    """
    try:
        dpy = xdisplay.Display()
    except Exception:
        return None
    try:
        root = dpy.screen().root
        prop = root.get_full_property(
            dpy.intern_atom("_NET_ACTIVE_WINDOW"), X.AnyPropertyType
        )
        if prop is None or not getattr(prop, "value", None):
            return None
        return int(prop.value[0])
    except Exception:
        return None
    finally:
        try:
            dpy.close()
        except Exception:
            pass


def resolve_ptt_down(
    last_down: float | None,
    now: float,
    window: float = PTT_DOUBLE_TAP_S,
) -> tuple[Action, float | None]:
    """Map a PTT key-down to an Action.

    Two downs within ``window`` seconds yield HANDSFREE_TOGGLE instead of
    a second PTT_DOWN. Returns ``(action, last_down_to_remember)``.
    """
    if last_down is not None and (now - last_down) <= window:
        return Action.HANDSFREE_TOGGLE, None
    return Action.PTT_DOWN, now


def _split_tokens(spec: str) -> list[str]:
    text = spec.strip()
    if not text:
        raise ValueError("empty shortcut")
    if "," in text:
        raise ValueError(
            f"invalid shortcut {spec!r}: parse_shortcut takes a single binding"
        )
    tokens = [part.strip() for part in text.split("+")]
    if any(token == "" for token in tokens):
        raise ValueError(f"invalid shortcut {spec!r}: empty token")
    return tokens


def _token_to_keysym(token: str) -> int:
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


def parse_shortcut(spec: str) -> tuple[int, int]:
    """Parse ``Ctrl+Super+d`` / ``Escape`` / ``F5`` into ``(modmask, keysym)``.

    Raises ``ValueError`` with a clear message for mouse buttons, bare
    letters, empty input, unknown keys, and modifier-only combos.
    """
    if spec is None or not str(spec).strip():
        raise ValueError("empty shortcut")
    tokens = _split_tokens(str(spec))
    for token in tokens:
        if _MOUSE_TOKEN.match(token):
            raise ValueError(f"mouse buttons are not allowed: {token!r}")

    modmask = 0
    key_token: str | None = None
    for token in tokens:
        mask = _MOD_NAMES.get(token.lower())
        if mask is not None:
            if modmask & mask:
                raise ValueError(
                    f"invalid shortcut {spec!r}: duplicate modifier {token!r}"
                )
            modmask |= mask
            continue
        if key_token is not None:
            raise ValueError(
                f"invalid shortcut {spec!r}: extra key {token!r}"
            )
        key_token = token

    if key_token is None:
        raise ValueError(
            f"invalid shortcut {spec!r}: no non-modifier key"
        )

    keysym = _token_to_keysym(key_token)
    if modmask == 0 and len(key_token) == 1 and key_token.isalpha():
        raise ValueError(
            f"single plain letters are not allowed: {key_token!r}"
        )
    return modmask, keysym


def parse_bindings(spec: str) -> list[tuple[int, int]]:
    """Parse a comma-separated list of bindings into ``(modmask, keysym)``."""
    if spec is None or not str(spec).strip():
        raise ValueError("empty shortcut")
    out: list[tuple[int, int]] = []
    for part in str(spec).split(","):
        binding = part.strip()
        if not binding:
            raise ValueError("empty binding")
        out.append(parse_shortcut(binding))
    return out


class X11Backend(HotkeyBackend):
    """Grab shortcuts on the X11 root window and dispatch ``Action`` values."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._dispatch: Callable[[Action], None] | None = None
        self._last_ptt_down: float | None = None
        self._suppress_ptt_up = False
        self._held_keycodes: set[int] = set()
        # Autorepeat suppression: X sends release+press pairs ~0ms apart
        # while a grabbed key is held; a real re-press is never that fast.
        self._last_release: dict[int, float] = {}
        self._repeat_window_s = 0.030
        # Cancel grab is armed only while recording/processing so a bare
        # Escape keeps working in other apps while flowd is idle.
        self._cancel_want = False

    def set_cancel_armed(self, armed: bool) -> None:
        """Request the cancel-key grab on/off (applied on the hotkey thread)."""
        self._cancel_want = bool(armed)

    def start(
        self, settings: Settings, dispatch: Callable[[Action], None]
    ) -> None:
        if self._thread is not None and self._thread.is_alive():
            raise RuntimeError("X11Backend is already running")
        self._dispatch = dispatch
        self._stop.clear()
        self._ready.clear()
        self._error = None
        self._last_ptt_down = None
        self._suppress_ptt_up = False
        self._held_keycodes.clear()
        self._thread = threading.Thread(
            target=self._run,
            args=(settings,),
            name="flow-hotkey-x11",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(timeout=5.0):
            self._stop.set()
            raise RuntimeError("X11 hotkey thread failed to start")
        if self._error is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
            raise RuntimeError(f"X11 hotkey backend failed: {self._error}") from self._error

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=2.0)
        self._thread = None
        self._dispatch = None

    def _emit(self, action: Action) -> None:
        cb = self._dispatch
        if cb is None:
            return
        try:
            cb(action)
        except Exception:
            log.exception("hotkey dispatch failed for %s", action)

    def _run(self, settings: Settings) -> None:
        dpy = None
        root = None
        grabs: list[tuple[int, int]] = []
        bindings: list[tuple[int, int, str, bool]] = []
        try:
            dpy = xdisplay.Display()
            dpy.set_error_handler(lambda *args, **kwargs: None)
            root = dpy.screen().root
            bindings = self._compile_bindings(settings)
            grabs = self._grab_all(dpy, root, bindings)
            dpy.flush()
            self._ready.set()
            self._loop(dpy, root, bindings, grabs)
        except Exception as exc:
            self._error = exc
            self._ready.set()
            log.exception("X11 hotkey thread aborted")
        finally:
            if dpy is not None and root is not None:
                for keycode, modifiers in grabs:
                    try:
                        root.ungrab_key(keycode, modifiers)
                    except Exception:
                        pass
                try:
                    dpy.flush()
                    dpy.close()
                except Exception:
                    pass

    def _compile_bindings(
        self, settings: Settings
    ) -> list[tuple[int, int, str, bool]]:
        """Return (modmask, keysym, kind, any_modifier) rows.

        Any-modifier matching applies only to a bare cancel binding;
        an explicitly modified cancel chord requires its modifiers.
        """
        rows: list[tuple[int, int, str, bool]] = []
        mapping = (
            (settings.ptt_shortcut, _KIND_PTT, False),
            (settings.handsfree_shortcut, _KIND_HANDSFREE, False),
            (settings.command_shortcut, _KIND_COMMAND, False),
            (settings.paste_last_shortcut, _KIND_PASTE, False),
            (settings.copy_last_shortcut, _KIND_COPY, False),
            (settings.cancel_key, _KIND_CANCEL, True),
        )
        for spec, kind, cancel in mapping:
            for modmask, keysym in parse_bindings(spec):
                any_mod = cancel and modmask == 0
                rows.append((modmask, keysym, kind, any_mod))
        return rows

    def _grab_all(
        self,
        dpy: xdisplay.Display,
        root: object,
        bindings: list[tuple[int, int, str, bool]],
    ) -> list[tuple[int, int]]:
        grabbed: list[tuple[int, int]] = []
        seen: set[tuple[int, int]] = set()
        for modmask, keysym, _kind, any_mod in bindings:
            keycodes = _keycodes_for_keysym(dpy, keysym)
            if not keycodes:
                raise RuntimeError(
                    f"no keycode for keysym {keysym} (check the keyboard map)"
                )
            if any_mod:
                continue  # cancel rows arm on demand in _loop
            if any_mod:
                variants = (X.AnyModifier,)
            else:
                variants = lock_mask_variants(modmask)
            for keycode in keycodes:
                for modifiers in variants:
                    pair = (keycode, modifiers)
                    if pair in seen:
                        continue
                    seen.add(pair)
                    root.grab_key(  # type: ignore[attr-defined]
                        keycode,
                        modifiers,
                        True,
                        X.GrabModeAsync,
                        X.GrabModeAsync,
                    )
                    grabbed.append(pair)
        return grabbed

    def _loop(
        self,
        dpy: xdisplay.Display,
        root: object,
        bindings: list[tuple[int, int, str, bool]],
        grabs: list[tuple[int, int]],
    ) -> None:
        compiled = self._compile_match_table(dpy, bindings)
        cancel_rows = [
            (modmask, keysym)
            for modmask, keysym, _kind, any_mod in bindings
            if any_mod
        ]
        cancel_pairs: list[tuple[int, int]] = []
        fd = dpy.fileno()
        pushback: list = []
        while not self._stop.is_set():
            self._sync_cancel_grab(dpy, root, cancel_rows, grabs, cancel_pairs)
            if not pushback:
                try:
                    ready, _, _ = select.select([fd], [], [], 0.05)
                except (OSError, ValueError):
                    break
                if not ready:
                    continue
            while pushback or dpy.pending_events():
                if pushback:
                    event = pushback.pop(0)
                else:
                    event = dpy.next_event()
                if getattr(event, "type", None) == X.KeyRelease and self._swallow_strobe(
                    dpy, event, pushback
                ):
                    continue
                self._handle_event(event, compiled)

    def _sync_cancel_grab(
        self,
        dpy: xdisplay.Display,
        root: object,
        cancel_rows: list[tuple[int, int]],
        grabs: list[tuple[int, int]],
        cancel_pairs: list[tuple[int, int]],
    ) -> None:
        """Grab/ungrab the cancel key to match ``_cancel_want``.

        Runs on the hotkey thread only. Armed pairs join ``grabs`` so
        ``stop()`` still releases them.
        """
        want = self._cancel_want
        if want == bool(cancel_pairs):
            return
        if want:
            for _modmask, keysym in cancel_rows:
                for keycode in _keycodes_for_keysym(dpy, keysym):
                    pair = (keycode, X.AnyModifier)
                    if pair in grabs or pair in cancel_pairs:
                        continue
                    try:
                        root.grab_key(  # type: ignore[attr-defined]
                            keycode,
                            X.AnyModifier,
                            True,
                            X.GrabModeAsync,
                            X.GrabModeAsync,
                        )
                    except Exception:
                        continue
                    cancel_pairs.append(pair)
                    grabs.append(pair)
            try:
                dpy.flush()
            except Exception:
                pass
        else:
            for pair in cancel_pairs:
                try:
                    root.ungrab_key(*pair)  # type: ignore[attr-defined]
                except Exception:
                    pass
                if pair in grabs:
                    grabs.remove(pair)
            cancel_pairs.clear()
            try:
                dpy.flush()
            except Exception:
                pass

    def _swallow_strobe(self, dpy, release_event, pushback: list) -> bool:
        """Swallow an autorepeat release+press pair (held grabbed key).

        Returns True when a KeyPress for the same keycode arrives within
        30ms (strobe: drop both). Otherwise the release is genuine: any
        other queued events are stashed to ``pushback`` and False is
        returned so the caller dispatches the release normally.
        """
        keycode = int(release_event.detail)
        deadline = time.monotonic() + 0.030
        while True:
            while dpy.pending_events():
                nxt = dpy.next_event()
                if getattr(nxt, "type", None) == X.KeyPress and int(
                    nxt.detail
                ) == keycode:
                    return True
                pushback.append(nxt)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            try:
                ready, _, _ = select.select([dpy.fileno()], [], [], remaining)
            except (OSError, ValueError):
                return False
            if not ready:
                return False

    def _compile_match_table(
        self,
        dpy: xdisplay.Display,
        bindings: list[tuple[int, int, str, bool]],
    ) -> list[tuple[int, int, str, bool]]:
        table: list[tuple[int, int, str, bool]] = []
        for modmask, keysym, kind, any_mod in bindings:
            for keycode in _keycodes_for_keysym(dpy, keysym):
                table.append((keycode, modmask, kind, any_mod))
        return table

    def _handle_event(
        self,
        event: object,
        table: list[tuple[int, int, str, bool]],
    ) -> None:
        etype = getattr(event, "type", None)
        if etype not in (X.KeyPress, X.KeyRelease):
            return
        keycode = int(event.detail)
        state = int(getattr(event, "state", 0))
        mods = state & _MODIFIER_MASK
        is_press = etype == X.KeyPress

        if is_press:
            if keycode in self._held_keycodes:
                return
            # Swallow autorepeat: its press lands ~0ms after its release.
            if time.monotonic() - self._last_release.get(keycode, 0.0) < self._repeat_window_s:
                return
            self._held_keycodes.add(keycode)
        else:
            self._held_keycodes.discard(keycode)
            self._last_release[keycode] = time.monotonic()

        kind = self._match_kind(keycode, mods, table)
        if kind is None:
            return
        self._dispatch_kind(kind, is_press)

    def _match_kind(
        self,
        keycode: int,
        mods: int,
        table: list[tuple[int, int, str, bool]],
    ) -> str | None:
        # Cancel (any-mod) wins so Escape still fires with modifiers held.
        for grabbed_code, modmask, kind, any_mod in table:
            if kind != _KIND_CANCEL or grabbed_code != keycode:
                continue
            if any_mod or mods == modmask:
                return kind
        for grabbed_code, modmask, kind, any_mod in table:
            if grabbed_code != keycode:
                continue
            if any_mod or mods == modmask:
                return kind
        return None

    def _dispatch_kind(self, kind: str, is_press: bool) -> None:
        if kind == _KIND_CANCEL:
            if is_press:
                self._emit(Action.CANCEL)
            return
        if kind == _KIND_PTT:
            now = time.monotonic()
            if is_press:
                action, self._last_ptt_down = resolve_ptt_down(
                    self._last_ptt_down, now
                )
                self._suppress_ptt_up = action is Action.HANDSFREE_TOGGLE
                self._emit(action)
            else:
                if self._suppress_ptt_up:
                    self._suppress_ptt_up = False
                    return
                self._emit(Action.PTT_UP)
            return
        if kind == _KIND_HANDSFREE:
            if is_press:
                self._emit(Action.HANDSFREE_TOGGLE)
            return
        if kind == _KIND_COMMAND:
            self._emit(Action.COMMAND_DOWN if is_press else Action.COMMAND_UP)
            return
        if kind == _KIND_PASTE:
            if is_press:
                self._emit(Action.PASTE_LAST)
            return
        if kind == _KIND_COPY:
            if is_press:
                self._emit(Action.COPY_LAST)


def _keycodes_for_keysym(dpy: xdisplay.Display, keysym: int) -> list[int]:
    raw = dpy.keysym_to_keycodes(keysym)
    codes: list[int] = []
    seen: set[int] = set()
    for item in raw or ():
        keycode = item[0] if isinstance(item, tuple) else int(item)
        if keycode and keycode not in seen:
            seen.add(keycode)
            codes.append(keycode)
    if not codes:
        primary = dpy.keysym_to_keycode(keysym)
        if primary:
            codes.append(primary)
    return codes


HOTKEY_BACKENDS["x11"] = X11Backend
