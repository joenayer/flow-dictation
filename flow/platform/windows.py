"""Windows 10/11 platform backends for flow (English-only, offline).

Mirrors the Linux ``X11Backend`` / typer shapes behind the frozen seams in
:mod:`flow.hotkey_base` and :mod:`flow.typer_base` so the integrator can pick
them by platform with no shared-file redesign:

- :class:`WindowsBackend` — global hotkeys incl. hold-to-talk (PTT down/up),
  double-tap hands-free toggle, command chords, paste/copy-last, cancel.
- :class:`WinSendInputTyper` — ``SendInput``-based typer (Unicode text plus
  ``press_keys`` chords) mirroring :class:`flow.type_xlib.XlibTyper`.
- Startup-folder autostart (``autostart_is_enabled`` /
  ``autostart_set_enabled``) mirroring :mod:`flow.autostart` semantics
  (never raise on missing pieces).
- ``%APPDATA%`` / ``%LOCALAPPDATA%`` directories for settings, data, cache.

Hotkey-listener choice: **pynput** over the ``keyboard`` package.

- ``pynput`` ships a maintained ``keyboard.Listener`` thread with distinct
  ``on_press`` / ``on_release`` callbacks, which maps 1:1 onto hold-to-talk.
  On Windows it uses a low-level hook (``SetWindowsHookEx``) via ctypes and
  needs no administrator rights for ordinary apps and no compiled wheels.
- The ``keyboard`` package needs elevated privileges for reliable global
  interception on Windows, its last release is stale relative to ``pynput``,
  and it pulls in remap/block machinery this app never uses.
- Either way the dependency stays minimal and lazy: nothing here imports
  ``pynput`` (or any Windows-only API such as ``ctypes.windll`` / ``msvcrt``)
  at module import time, so this module imports cleanly on Linux and every
  pure helper is unit-testable anywhere. The live listener and ``SendInput``
  paths are injected seams (``listener_factory``, ``sender``) so tests run
  with fakes; tests that need real Windows APIs skip off-Windows.

UNVERIFIED-ON-WINDOWS: this module was written and tested on Linux. The
pynput listener wiring, real SendInput injection, Startup-folder behaviour,
and installer scripts have not yet run on Windows 10/11.
"""

from __future__ import annotations

import ctypes
import logging
import os
import re
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

from ..config import Settings
from ..hotkey_base import HOTKEY_BACKENDS, Action, HotkeyBackend
from ..typer_base import TYPER_BACKENDS, TyperBackend

log = logging.getLogger(__name__)

PTT_DOUBLE_TAP_S = 0.350

APP_NAME = "flow-linux"
STARTUP_LAUNCHER_NAME = "flow-linux.bat"

_KIND_PTT = "ptt"
_KIND_HANDSFREE = "handsfree"
_KIND_COMMAND = "command"
_KIND_PASTE = "paste"
_KIND_COPY = "copy"
_KIND_CANCEL = "cancel"

_MOD_NAMES: dict[str, str] = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "ctl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "option": "alt",
    "super": "win",
    "win": "win",
    "windows": "win",
    "cmd": "win",
    "meta": "win",
    "mod4": "win",
    "mod1": "alt",
}

_KEY_ALIASES: dict[str, str] = {
    "esc": "escape",
    "escape": "escape",
    "enter": "enter",
    "return": "enter",
    "space": "space",
    "tab": "tab",
    "backspace": "backspace",
    "bksp": "backspace",
    "del": "delete",
    "delete": "delete",
    "plus": "plus",
    "minus": "minus",
    "ins": "insert",
    "insert": "insert",
    "pgup": "page_up",
    "pageup": "page_up",
    "page_up": "page_up",
    "pgdn": "page_down",
    "pagedown": "page_down",
    "page_down": "page_down",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "home": "home",
    "end": "end",
    "capslock": "caps_lock",
    "caps_lock": "caps_lock",
}

_MOUSE_TOKEN = re.compile(
    r"^(button\d+|btn\d+|mouse\d+|pointer_button\d+)$",
    re.IGNORECASE,
)

_FKEY_RE = re.compile(r"[fF](\d{1,2})\Z")

_PUNCT_KEYS = frozenset(
    "`-=[]\\;',./"
    "~!@#$%^&*()_+{}|:\"<>?"
)


def is_windows() -> bool:
    """Return True when running on Windows (``sys.platform == 'win32'``)."""
    return sys.platform == "win32"


def _canonical_key(token: str) -> str:
    """Map a non-modifier token to its canonical lowercase key name."""
    alias = _KEY_ALIASES.get(token.lower())
    if alias is not None:
        return alias
    match = _FKEY_RE.fullmatch(token)
    if match:
        number = int(match.group(1))
        if 1 <= number <= 24:
            return f"f{number}"
        raise ValueError(f"unknown key {token!r}")
    if len(token) == 1 and (token.isalnum() or token in _PUNCT_KEYS):
        return token.lower()
    raise ValueError(f"unknown key {token!r}")


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


def parse_shortcut(spec: str) -> tuple[frozenset[str], str]:
    """Parse ``Ctrl+Win+d`` / ``Escape`` / ``F5`` into ``(modifiers, key)``.

    ``modifiers`` is a frozenset of ``ctrl`` / ``shift`` / ``alt`` / ``win``
    and ``key`` is a canonical lowercase key name. Mirrors the X11
    ``parse_shortcut`` rejection rules: mouse buttons, bare letters, empty
    input, unknown keys, duplicate modifiers, extra keys, and
    modifier-only combos all raise ``ValueError``.
    """
    if spec is None or not str(spec).strip():
        raise ValueError("empty shortcut")
    tokens = _split_tokens(str(spec))
    for token in tokens:
        if _MOUSE_TOKEN.match(token):
            raise ValueError(f"mouse buttons are not allowed: {token!r}")

    modifiers: set[str] = set()
    key_token: str | None = None
    for token in tokens:
        mod = _MOD_NAMES.get(token.lower())
        if mod is not None:
            if mod in modifiers:
                raise ValueError(
                    f"invalid shortcut {spec!r}: duplicate modifier {token!r}"
                )
            modifiers.add(mod)
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
    key = _canonical_key(key_token)
    if not modifiers and len(key_token) == 1 and key_token.isalpha():
        raise ValueError(
            f"single plain letters are not allowed: {key_token!r}"
        )
    return frozenset(modifiers), key


def parse_bindings(spec: str) -> list[tuple[frozenset[str], str]]:
    """Parse a comma-separated list of bindings into ``(modifiers, key)``."""
    if spec is None or not str(spec).strip():
        raise ValueError("empty shortcut")
    out: list[tuple[frozenset[str], str]] = []
    for part in str(spec).split(","):
        binding = part.strip()
        if not binding:
            raise ValueError("empty binding")
        out.append(parse_shortcut(binding))
    return out


def resolve_ptt_down(
    last_down: float | None,
    now: float,
    window: float = PTT_DOUBLE_TAP_S,
) -> tuple[Action, float | None]:
    """Map a PTT key-down to an Action (same contract as the X11 helper).

    Two downs within ``window`` seconds yield HANDSFREE_TOGGLE instead of
    a second PTT_DOWN. Returns ``(action, last_down_to_remember)``.
    """
    if last_down is not None and (now - last_down) <= window:
        return Action.HANDSFREE_TOGGLE, None
    return Action.PTT_DOWN, now


# pynput.keyboard.Key names for modifier keys -> canonical modifier.
_PYNPUT_MODS: dict[str, str] = {
    "ctrl": "ctrl",
    "ctrl_l": "ctrl",
    "ctrl_r": "ctrl",
    "shift": "shift",
    "shift_l": "shift",
    "shift_r": "shift",
    "alt": "alt",
    "alt_l": "alt",
    "alt_r": "alt",
    "alt_gr": "alt",
    "cmd": "win",
    "cmd_l": "win",
    "cmd_r": "win",
}

# pynput.keyboard.Key names for non-modifier keys -> canonical key name.
_PYNPUT_KEYS: dict[str, str] = {
    "esc": "escape",
    "enter": "enter",
    "space": "space",
    "tab": "tab",
    "backspace": "backspace",
    "delete": "delete",
    "insert": "insert",
    "home": "home",
    "end": "end",
    "page_up": "page_up",
    "page_down": "page_down",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "caps_lock": "caps_lock",
    "num_lock": "num_lock",
    "print_screen": "print_screen",
    "scroll_lock": "scroll_lock",
    "pause": "pause",
    "menu": "menu",
}

# Windows virtual-key codes seen on KeyCode(vk=...) without a char.
_VK_TO_KEY: dict[int, str] = {
    0x08: "backspace",
    0x09: "tab",
    0x0D: "enter",
    0x1B: "escape",
    0x20: "space",
    0x21: "page_up",
    0x22: "page_down",
    0x23: "end",
    0x24: "home",
    0x25: "left",
    0x26: "up",
    0x27: "right",
    0x28: "down",
    0x2D: "insert",
    0x2E: "delete",
}


def normalize_listener_key(key: Any) -> tuple[str, str | None]:
    """Map a listener key event to ``(kind, name)``.

    ``kind`` is ``"mod"`` (name is a canonical modifier), ``"key"`` (name
    is a canonical key name matching :func:`parse_shortcut`), or
    ``"unknown"`` (name is None). Accepts pynput ``Key`` / ``KeyCode``
    objects by duck typing (never imports pynput) and plain strings,
    which pass through :func:`_canonical_key` so tests can drive the
    backend without any listener library.
    """
    if isinstance(key, str):
        text = key.strip()
        if not text:
            return "unknown", None
        mod = _MOD_NAMES.get(text.lower())
        if mod is not None and len(text) > 1:
            return "mod", mod
        try:
            return "key", _canonical_key(text)
        except ValueError:
            return "unknown", None
    name = getattr(key, "name", None)
    if isinstance(name, str):
        lowered = name.lower()
        mod = _PYNPUT_MODS.get(lowered)
        if mod is not None:
            return "mod", mod
        mapped = _PYNPUT_KEYS.get(lowered)
        if mapped is not None:
            return "key", mapped
        match = _FKEY_RE.fullmatch(lowered)
        if match and 1 <= int(match.group(1)) <= 24:
            return "key", f"f{int(match.group(1))}"
        return "unknown", None
    char = getattr(key, "char", None)
    if isinstance(char, str) and len(char) == 1:
        try:
            return "key", _canonical_key(char)
        except ValueError:
            return "unknown", None
    vk = getattr(key, "vk", None)
    if isinstance(vk, int):
        name = _vk_to_name(vk)
        if name is not None:
            return "key", name
    return "unknown", None


def _vk_to_name(vk: int) -> str | None:
    """Map a Windows virtual-key code to a canonical key name."""
    if 0x41 <= vk <= 0x5A:  # A-Z
        return chr(vk).lower()
    if 0x30 <= vk <= 0x39:  # 0-9
        return chr(vk)
    if 0x70 <= vk <= 0x87:  # F1-F24
        return f"f{vk - 0x70 + 1}"
    return _VK_TO_KEY.get(vk)


_MOD_VK_NAMES = (
    (0x10, "shift"),
    (0x11, "ctrl"),
    (0x12, "alt"),
    (0x5B, "win"),
    (0x5C, "win"),
)


def _physical_modifiers(get_state=None) -> frozenset:
    """Read physically-held modifiers via GetAsyncKeyState (Windows-only).

    ``get_state`` is injected for tests; the default resolves
    ``user32.GetAsyncKeyState`` lazily and returns an empty set off-Windows.
    """
    if get_state is None:
        try:
            get_state = ctypes.windll.user32.GetAsyncKeyState
        except (AttributeError, OSError):
            return frozenset()
    try:
        return frozenset(
            name for vk, name in _MOD_VK_NAMES if get_state(vk) & 0x8000
        )
    except Exception:
        return frozenset()


_MODIFIER_VKS = frozenset({0x10, 0x11, 0x12, 0x5B, 0x5C})
_INJECTED_MASK = 0x10 | 0x02  # LLKHF_INJECTED | LLKHF_LOWER_IL_INJECTED


class _ChordSuppressor:
    """Decides which low-level key events pynput must swallow.

    Pure decision logic (unit-tested): suppress a chord's key-down when its
    modifiers are physically held, plus the matching key-up. Bare modifier
    keys and a bare cancel key are never suppressed. The key-up latch is
    keyed by virtual-key code so pairing survives modifier release and
    autorepeat, and latches expire so a lost key-up cannot wedge a chord.
    """

    _UP_MSGS = frozenset({0x101, 0x105})  # WM_KEYUP, WM_SYSKEYUP
    _LATCH_TTL_S = 60.0

    def __init__(self, table, clock=None) -> None:
        self._table = table
        self._clock = clock or time.monotonic
        self._suppressed: dict[int, float] = {}

    def _expire(self) -> None:
        now = self._clock()
        stale = [
            vk for vk, at in self._suppressed.items() if now - at > self._LATCH_TTL_S
        ]
        for vk in stale:
            del self._suppressed[vk]

    def is_latched(self, vk: int) -> bool:
        self._expire()
        return vk in self._suppressed

    def note_up(self, vk: int) -> bool:
        """Drop the key-up latch; True when one was held."""
        self._expire()
        return self._suppressed.pop(vk, None) is not None

    def should_suppress(self, vk: int, msg: int, mods) -> bool:
        is_up = msg in self._UP_MSGS
        if is_up:
            return self.note_up(vk)
        if self.is_latched(vk):
            return True  # autorepeat: keep swallowing, no re-dispatch
        name = _vk_to_name(vk)
        if name is None:
            return False
        if vk in _MODIFIER_VKS:
            return False  # never swallow bare modifiers
        for bound_mods, bound_key, kind, _any_mod in self._table:
            if bound_key != name:
                continue
            if kind == _KIND_CANCEL and not bound_mods:
                continue  # bare Escape must keep working system-wide
            if bound_mods == mods:
                self._suppressed[vk] = self._clock()
                return True
        return False


def _make_hook_filter(suppressor, mod_reader=None, **hooks):
    """Build a pynput ``win32_event_filter`` for chords + injected keys.

    ``mod_reader`` returns physically-held modifiers (default reads
    GetAsyncKeyState). Optional hooks wire deliberate dispatch: ``press``
    ``(name, mods)`` and ``release`` ``(name)`` mirror the listener
    callbacks, and ``listener_box`` maps ``"listener"`` to the live
    listener for ``suppress_event()``.

    Contract (pynput 1.8.2 ``keyboard/_win32.py``): the filter must be
    passed as the ``win32_event_filter`` kwarg (a bare ``event_filter``
    kwarg is dropped). Returning False only hides the event from the
    listener callbacks — system-wide suppression requires raising via
    ``listener.suppress_event()``, which propagates through pynput's
    hook handler. Suppressed events never reach the callbacks, so the
    filter dispatches them itself; anything it does not swallow returns
    True and flows through the normal path exactly once.
    """
    press = hooks.get("press")
    release = hooks.get("release")
    listener_box = hooks.get("listener_box")

    def _swallow() -> bool:
        if listener_box is not None:
            listener = listener_box.get("listener")
            suppress = getattr(listener, "suppress_event", None)
            if callable(suppress):
                # Real pynput raises SuppressException: swallowed
                # system-wide, never posted to the callbacks.
                suppress()
        # Already dispatched (or nothing to dispatch): hide from the
        # listener callbacks so the action fires exactly once.
        return False

    def _filter(msg, data) -> bool:
        try:
            flags = int(data.flags)
        except Exception:
            return True
        if flags & _INJECTED_MASK:
            return False  # injected: hidden from Flow, system delivery kept
        try:
            vk = int(data.vkCode)
        except Exception:
            return True
        if vk in _MODIFIER_VKS:
            return True  # never swallow bare modifiers
        name = _vk_to_name(vk)
        if name is None:
            return True
        try:
            mods = mod_reader() if mod_reader else _physical_modifiers()
        except Exception:
            mods = frozenset()
        try:
            is_up = int(msg) in _ChordSuppressor._UP_MSGS
        except Exception:
            return True
        # NB: _swallow() stays outside the guarded sections below: a
        # real listener's suppress_event() raises to swallow the event
        # system-wide, and that exception must propagate to pynput.
        try:
            latched = suppressor.is_latched(vk)
        except Exception:
            return True
        if is_up:
            if not latched:
                return True
            try:
                suppressor.note_up(vk)
                if release is not None:
                    release(name)
            except Exception:
                pass
            return _swallow()
        if latched:
            return _swallow()  # autorepeat: swallow, no re-dispatch
        try:
            swallow = suppressor.should_suppress(vk, int(msg), mods)
        except Exception:
            return True
        if not swallow:
            return True
        if press is not None:
            try:
                press(name, mods)
            except Exception:
                pass
        return _swallow()

    return _filter


def _default_listener_factory(
    on_press: Callable[[Any], None],
    on_release: Callable[[Any], None],
    event_filter=None,
) -> Any:
    """Build a ``pynput.keyboard.Listener``. Import is lazy (Windows-only).

    The filter rides the ``win32_event_filter`` kwarg — the only name
    pynput's win32 backend reads (``Listener._options['event_filter']``).
    """
    try:
        from pynput.keyboard import Listener
    except ImportError as exc:
        raise RuntimeError(
            "Windows hotkeys need the 'pynput' package "
            "(pip install -r packaging/windows/requirements-windows.txt)"
        ) from exc
    kwargs: dict = {}
    if event_filter is not None:
        kwargs["win32_event_filter"] = event_filter
    return Listener(on_press=on_press, on_release=on_release, **kwargs)


class WindowsBackend(HotkeyBackend):
    """Global hotkeys on Windows via a key-listener thread (pynput).

    Same :class:`~flow.hotkey_base.HotkeyBackend` shape as ``X11Backend``:
    ``start(settings, dispatch)`` begins listening, the listener thread
    calls ``dispatch`` with :class:`~flow.hotkey_base.Action` values, and
    ``stop()`` releases everything. Double-tap PTT-down within
    ``PTT_DOUBLE_TAP_S`` dispatches HANDSFREE_TOGGLE; Escape=CANCEL.

    ``listener_factory``, ``clock`` and ``mod_reader`` are injectable
    seams for tests: the factory receives ``(on_press, on_release,
    event_filter)`` and must return an object with ``start()`` / ``stop()``
    (like ``pynput``'s Listener, whose real class also provides
    ``suppress_event()``); ``mod_reader`` returns physically-held
    modifiers (default reads GetAsyncKeyState on Windows, nothing elsewhere).
    """

    def __init__(
        self,
        listener_factory: Callable[..., Any] | None = None,
        clock: Callable[[], float] | None = None,
        mod_reader: Callable[[], frozenset] | None = None,
    ) -> None:
        self._factory = listener_factory or _default_listener_factory
        self._clock = clock or time.monotonic
        self._mod_reader = mod_reader
        self._listener: Any | None = None
        # Indirect listener handle for the hook filter (created before
        # the listener exists); used only for suppress_event().
        self._listener_ref: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._dispatch: Callable[[Action], None] | None = None
        self._table: list[tuple[frozenset[str], str, str, bool]] = []
        self._mods: set[str] = set()
        self._held: set[tuple[str, str | None]] = set()
        self._last_ptt_down: float | None = None
        self._suppress_ptt_up = False
        self._armed_by_key: dict[str, str] = {}
        self._suppressor: _ChordSuppressor | None = None

    def start(
        self, settings: Settings, dispatch: Callable[[Action], None]
    ) -> None:
        with self._lock:
            if self._listener is not None:
                raise RuntimeError("WindowsBackend is already running")
            self._dispatch = dispatch
            try:
                self._table = self._compile_bindings(settings)
            except ValueError as exc:
                self._dispatch = None
                raise RuntimeError(
                    f"Windows hotkey backend failed: {exc}"
                ) from exc
            self._mods.clear()
            self._held.clear()
            self._last_ptt_down = None
            self._suppress_ptt_up = False
            self._armed_by_key.clear()
            self._suppressor = _ChordSuppressor(self._table)
            if self._mod_reader is None and is_windows():
                self._mod_reader = _physical_modifiers
            event_filter = _make_hook_filter(
                self._suppressor,
                self._mod_reader,
                press=self._press_event,
                release=self._release_event,
                listener_box=self._listener_ref,
            )
            try:
                listener = self._factory(
                    self._on_press, self._on_release, event_filter
                )
                listener.start()
            except Exception as exc:
                self._listener = None
                self._dispatch = None
                raise RuntimeError(
                    f"Windows hotkey backend failed: {exc}"
                ) from exc
            self._listener = listener
            self._listener_ref["listener"] = listener

    def stop(self) -> None:
        with self._lock:
            listener, self._listener = self._listener, None
            self._dispatch = None
        if listener is not None:
            try:
                listener.stop()
            except Exception:
                log.exception("Windows hotkey listener stop failed")

    @property
    def running(self) -> bool:
        return self._listener is not None

    def _emit(self, action: Action) -> None:
        cb = self._dispatch
        if cb is None:
            return
        try:
            cb(action)
        except Exception:
            log.exception("hotkey dispatch failed for %s", action)

    @staticmethod
    def _compile_bindings(
        settings: Settings,
    ) -> list[tuple[frozenset[str], str, str, bool]]:
        """Return (modifiers, key, kind, any_modifier) rows.

        Any-modifier matching applies only to a bare cancel binding
        (``Escape`` cancels with anything held); an explicitly modified
        cancel chord (``Ctrl+Q``) requires its configured modifiers.
        """
        rows: list[tuple[frozenset[str], str, str, bool]] = []
        mapping = (
            (settings.ptt_shortcut, _KIND_PTT, False),
            (settings.handsfree_shortcut, _KIND_HANDSFREE, False),
            (settings.command_shortcut, _KIND_COMMAND, False),
            (settings.paste_last_shortcut, _KIND_PASTE, False),
            (settings.copy_last_shortcut, _KIND_COPY, False),
            (settings.cancel_key, _KIND_CANCEL, True),
        )
        for spec, kind, cancel in mapping:
            for modifiers, key in parse_bindings(spec):
                any_mod = cancel and not modifiers
                rows.append((modifiers, key, kind, any_mod))
        return rows

    def _on_press(self, key: Any) -> None:
        kind, name = normalize_listener_key(key)
        if kind == "unknown" or name is None:
            return
        with self._lock:
            if kind == "mod":
                self._mods.add(name)
                return
            if self._mod_reader is not None:
                # Heal stuck modifiers (Win+L/UAC/RDP swallow key-ups).
                try:
                    self._mods = set(self._mod_reader())
                except Exception:
                    pass
            mods = frozenset(self._mods)
        self._press_event(name, mods)

    def _press_event(self, name: str, mods: frozenset) -> Action | None:
        """Shared key-press path for callbacks and the hook filter.

        The filter calls this for suppressed chords (which never reach
        the callbacks); returns the emitted Action, if any.
        """
        with self._lock:
            event = ("key", name)
            if event in self._held:
                return None  # autorepeat: pynput re-fires on_press
            self._held.add(event)
            matched = self._match_kind(name, frozenset(mods))
        if matched is None:
            return None
        action = self._dispatch_kind(matched, True)
        # Arm THIS key so its release dispatches the same kind even if
        # the user lets go of the modifier first or bindings share keys.
        if action in (Action.PTT_DOWN, Action.COMMAND_DOWN):
            with self._lock:
                self._armed_by_key[name] = matched
        return action

    def _on_release(self, key: Any) -> None:
        kind, name = normalize_listener_key(key)
        if kind == "unknown" or name is None:
            return
        if kind == "mod":
            with self._lock:
                self._mods.discard(name)
            return
        self._release_event(name)

    def _release_event(self, name: str) -> Action | None:
        """Shared key-release path for callbacks and the hook filter."""
        with self._lock:
            self._held.discard(("key", name))
            # Release dispatches only the kind armed by THIS key's press.
            # A lost PTT_UP would wedge an utterance in RECORDING, while
            # a stray release must stay silent.
            matched = self._armed_by_key.pop(name, None)
        if matched is not None:
            return self._dispatch_kind(matched, False)
        return None

    def _match_row(
        self, key: str, mods: frozenset[str]
    ) -> tuple[frozenset[str], str, str, bool] | None:
        """Return the winning table row, or None when nothing matches.

        A bare cancel binding wins over every other kind on its key;
        a modified cancel chord only matches its exact modifiers.
        """
        for row in self._table:
            bound_mods, bound_key, kind, any_mod = row
            if kind != _KIND_CANCEL or bound_key != key:
                continue
            if any_mod or bound_mods == mods:
                return row
        for row in self._table:
            bound_mods, bound_key, kind, any_mod = row
            if bound_key != key:
                continue
            if any_mod or bound_mods == mods:
                return row
        return None

    def _match_kind(
        self, key: str, mods: frozenset[str]
    ) -> str | None:
        # Cancel (any-mod) wins so Escape still fires with modifiers held.
        row = self._match_row(key, mods)
        return row[2] if row is not None else None

    def _dispatch_kind(self, kind: str, is_press: bool) -> Action | None:
        """Dispatch *kind* and return the emitted Action (None if silent)."""
        if kind == _KIND_CANCEL:
            if is_press:
                self._emit(Action.CANCEL)
                return Action.CANCEL
            return None
        if kind == _KIND_PTT:
            now = self._clock()
            if is_press:
                action, self._last_ptt_down = resolve_ptt_down(
                    self._last_ptt_down, now
                )
                self._suppress_ptt_up = action is Action.HANDSFREE_TOGGLE
                self._emit(action)
                return action
            if self._suppress_ptt_up:
                self._suppress_ptt_up = False
                return None
            self._emit(Action.PTT_UP)
            return Action.PTT_UP
        if kind == _KIND_HANDSFREE:
            if is_press:
                self._emit(Action.HANDSFREE_TOGGLE)
                return Action.HANDSFREE_TOGGLE
            return None
        if kind == _KIND_COMMAND:
            action = Action.COMMAND_DOWN if is_press else Action.COMMAND_UP
            self._emit(action)
            return action
        if kind == _KIND_PASTE:
            if is_press:
                self._emit(Action.PASTE_LAST)
                return Action.PASTE_LAST
            return None
        if kind == _KIND_COPY:
            if is_press:
                self._emit(Action.COPY_LAST)
                return Action.COPY_LAST
            return None
        return None  # pragma: no cover - table only holds known kinds


# ---------------------------------------------------------------------------
# SendInput typer
# ---------------------------------------------------------------------------

# Virtual-key codes for press_keys chords (Xlib-style ``Ctrl+BackSpace``).
_VK_MODIFIERS: dict[str, int] = {
    "ctrl": 0x11,  # VK_CONTROL
    "control": 0x11,
    "shift": 0x10,  # VK_SHIFT
    "alt": 0x12,  # VK_MENU
    "win": 0x5B,  # VK_LWIN
    "super": 0x5B,
    "meta": 0x5B,
}

_VK_NAMED: dict[str, int] = {
    "escape": 0x1B,
    "esc": 0x1B,
    "enter": 0x0D,
    "return": 0x0D,
    "tab": 0x09,
    "space": 0x20,
    "backspace": 0x08,
    "bksp": 0x08,
    "delete": 0x2E,
    "del": 0x2E,
    "insert": 0x2D,
    "ins": 0x2D,
    "home": 0x24,
    "end": 0x23,
    "page_up": 0x21,
    "pgup": 0x21,
    "page_down": 0x22,
    "pgdn": 0x22,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
}

# OEM virtual-key codes for US-layout punctuation (single-char keyspecs).
_VK_OEM: dict[str, int] = {
    ";": 0xBA,
    "=": 0xBB,
    ",": 0xBC,
    "-": 0xBD,
    ".": 0xBE,
    "/": 0xBF,
    "`": 0xC0,
    "[": 0xDB,
    "\\": 0xDC,
    "]": 0xDD,
    "'": 0xDE,
}


def _vk_for_token(token: str) -> int:
    """Map a non-modifier keyspec token to a virtual-key code."""
    lowered = token.lower()
    if lowered in _VK_NAMED:
        return _VK_NAMED[lowered]
    match = _FKEY_RE.fullmatch(token)
    if match and 1 <= int(match.group(1)) <= 24:
        return 0x70 + int(match.group(1)) - 1  # VK_F1..VK_F24
    if len(token) == 1:
        upper = token.upper()
        if "A" <= upper <= "Z" or "0" <= upper <= "9":
            return ord(upper)
        if token in _VK_OEM:
            return _VK_OEM[token]
    raise ValueError(f"unknown key {token!r}")


def parse_keyspec(keyspec: str) -> tuple[tuple[int, ...], int]:
    """Parse Xlib-style ``Ctrl+BackSpace`` into ``(modifier_vks, vk)``.

    Same contract shape as :func:`flow.type_xlib.parse_keyspec` but with
    Windows virtual-key codes. Raises ``ValueError`` for empty specs,
    empty tokens, modifier-only chords, duplicate modifiers, extra keys,
    and unknown keys.
    """
    if keyspec is None or not str(keyspec).strip():
        raise ValueError("empty keyspec")
    tokens = [part.strip() for part in str(keyspec).split("+")]
    if any(token == "" for token in tokens):
        raise ValueError(f"invalid keyspec {keyspec!r}: empty token")

    mods: list[int] = []
    seen: set[int] = set()
    vk: int | None = None
    for token in tokens:
        mod = _VK_MODIFIERS.get(token.lower())
        if mod is not None:
            if mod in seen:
                raise ValueError(
                    f"invalid keyspec {keyspec!r}: duplicate modifier {token!r}"
                )
            seen.add(mod)
            mods.append(mod)
            continue
        if vk is not None:
            raise ValueError(f"invalid keyspec {keyspec!r}: extra key {token!r}")
        vk = _vk_for_token(token)
    if vk is None:
        raise ValueError(f"invalid keyspec {keyspec!r}: modifier-only")
    return tuple(mods), vk


def plan_unicode_events(text: str) -> list[tuple[str, int]]:
    """Plan ``SendInput`` Unicode key events for *text* (pure, testable).

    Returns ``("unicode_down"/"unicode_up", utf16_code_unit)`` entries,
    two per UTF-16 code unit (surrogate pairs for non-BMP characters).
    ``"\\n"`` maps to the Enter virtual key instead of a Unicode newline.
    """
    events: list[tuple[str, int]] = []
    for char in text:
        if char == "\n":
            events.append(("vk_down", 0x0D))
            events.append(("vk_up", 0x0D))
            continue
        encoded = char.encode("utf-16-le")
        for index in range(0, len(encoded), 2):
            code_unit = encoded[index] | (encoded[index + 1] << 8)
            events.append(("unicode_down", code_unit))
            events.append(("unicode_up", code_unit))
    return events


def plan_keyspec_events(keyspec: str) -> list[tuple[str, int]]:
    """Plan press/release events for a keyspec (pure, testable).

    Returns ``("vk_down"/"vk_up", vk_code)`` entries: modifiers down, key
    down/up, modifiers up in reverse order. Raises ``ValueError`` for
    invalid keyspecs.
    """
    mods, vk = parse_keyspec(keyspec)
    events: list[tuple[str, int]] = []
    for mod in mods:
        events.append(("vk_down", mod))
    events.append(("vk_down", vk))
    events.append(("vk_up", vk))
    for mod in reversed(mods):
        events.append(("vk_up", mod))
    return events


# Win32 SendInput structures (module level so tests assert the ABI).
# Explicitly-sized ints keep the layout identical on every host:
# sizeof(INPUT) == 40 on 64-bit, 28 on 32-bit (MSDN INPUT).


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_int32),
        ("dy", ctypes.c_int32),
        ("mouseData", ctypes.c_uint32),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_uint16),
        ("wScan", ctypes.c_uint16),
        ("dwFlags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_uint32),
        ("wParamL", ctypes.c_uint16),
        ("wParamH", ctypes.c_uint16),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_uint32), ("u", _INPUT_UNION)]


INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

_MODIFIER_VKS = (0x10, 0x11, 0x12, 0x5B, 0x5C)  # Shift/Ctrl/Alt/LWin/RWin


def _wait_for_modifiers_released(user32, timeout_s: float = 0.15) -> None:
    """Best-effort wait until no modifier is physically held.

    Injecting text while Alt/Win is still down turns keystrokes into menu
    accelerators or OS shortcuts. ``user32`` is injected for tests.
    """
    get_state = getattr(user32, "GetAsyncKeyState", None)
    if get_state is None:
        return
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < deadline:
        try:
            held = any(get_state(vk) & 0x8000 for vk in _MODIFIER_VKS)
        except Exception:
            return
        if not held:
            return
        time.sleep(0.01)


def _send_events_via_sendinput(events: list[tuple[str, int]]) -> bool:
    """Deliver planned events with Win32 ``SendInput``. Windows-only."""
    try:
        user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False
    user32.SendInput.argtypes = [
        ctypes.c_uint,
        ctypes.POINTER(INPUT),
        ctypes.c_int,
    ]
    user32.SendInput.restype = ctypes.c_uint

    _wait_for_modifiers_released(user32)

    inputs = (INPUT * len(events))()
    for index, (kind, code) in enumerate(events):
        flags = 0
        vk, scan = 0, 0
        if kind == "unicode_down":
            flags = KEYEVENTF_UNICODE
            scan = code
        elif kind == "unicode_up":
            flags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
            scan = code
        elif kind == "vk_down":
            vk = code
        elif kind == "vk_up":
            vk = code
            flags = KEYEVENTF_KEYUP
        else:  # pragma: no cover - planners never emit anything else
            return False
        inputs[index].type = INPUT_KEYBOARD
        inputs[index].u.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    try:
        sent = user32.SendInput(len(events), inputs, ctypes.sizeof(INPUT))
    except (OSError, ValueError):
        return False
    return int(sent) == len(events)


class WinSendInputTyper(TyperBackend):
    """Type Unicode text into the focused app via Win32 ``SendInput``.

    Same :class:`~flow.typer_base.TyperBackend` shape as the X11 typers.
    ``sender`` is an injectable seam for tests: it receives a planned
    event list (see :func:`plan_unicode_events` / :func:`plan_keyspec_events`)
    and returns True on success. The default sender calls ``SendInput``.
    """

    name = "winsendinput"

    def __init__(
        self, sender: Callable[[list[tuple[str, int]]], bool] | None = None
    ) -> None:
        self._sender = sender or _send_events_via_sendinput

    @classmethod
    def available(cls) -> bool:
        if not is_windows():
            return False
        try:
            import ctypes

            _ = ctypes.windll.user32  # type: ignore[attr-defined] # probe: AttributeError means unavailable
        except (AttributeError, ImportError, OSError):
            return False
        return True

    def type_text(self, text: str) -> bool:
        if text is None:
            return False
        if text == "":
            return True
        try:
            events = plan_unicode_events(text)
            return bool(self._sender(events))
        except Exception:
            log.exception("SendInput typing failed")
            return False

    def press_keys(self, keyspec: str) -> bool:
        try:
            events = plan_keyspec_events(keyspec)
        except (ValueError, AttributeError):
            return False
        try:
            return bool(self._sender(events))
        except Exception:
            log.exception("SendInput press_keys failed for %r", keyspec)
            return False


def copy_to_clipboard(text: str, _api: Any | None = None) -> bool:
    """Copy *text* to the Windows clipboard (CF_UNICODETEXT).

    ``_api`` is an injectable seam for tests (an object with a
    ``run(text) -> bool`` method); the default implementation uses
    ``ctypes.windll`` and returns False off-Windows or when the clipboard
    cannot be opened (e.g. locked by another app — callers may retry).
    """
    if _api is None:
        if not is_windows():
            return False
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
        except (AttributeError, ImportError, OSError):
            return False

        GMEM_MOVEABLE = 0x0002
        CF_UNICODETEXT = 13

        # Pointer/handle signatures: without these, ctypes assumes c_int
        # and truncates 64-bit handles on x64.
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.argtypes = [ctypes.c_void_p]
        user32.OpenClipboard.restype = ctypes.c_bool
        user32.EmptyClipboard.restype = ctypes.c_bool
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.CloseClipboard.restype = ctypes.c_bool

        class _DefaultApi:
            def run(self, payload: str) -> bool:
                if not user32.OpenClipboard(None):
                    return False
                try:
                    user32.EmptyClipboard()
                    data = (payload + "\0").encode("utf-16-le")
                    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
                    if not handle:
                        return False
                    locked = kernel32.GlobalLock(handle)
                    if not locked:
                        kernel32.GlobalFree(handle)
                        return False
                    try:
                        ctypes.memmove(locked, data, len(data))
                    finally:
                        kernel32.GlobalUnlock(handle)
                    # The clipboard owns the handle after a successful call.
                    if not user32.SetClipboardData(CF_UNICODETEXT, handle):
                        kernel32.GlobalFree(handle)
                        return False
                    return True
                finally:
                    user32.CloseClipboard()

        _api = _DefaultApi()
    try:
        return bool(_api.run(text))
    except Exception:
        log.exception("Windows clipboard copy failed")
        return False


# ---------------------------------------------------------------------------
# %APPDATA% directories
# ---------------------------------------------------------------------------


def app_dirs(
    appdata: str | None = None,
    localappdata: str | None = None,
) -> dict[str, str]:
    """Return Windows home directories for settings, data, and cache.

    ``appdata`` / ``localappdata`` override ``%APPDATA%`` /
    ``%LOCALAPPDATA%`` (tests pass temp dirs). Falls back to ``~`` when
    the variables are missing so the helpers stay total.
    """
    roaming = appdata or os.environ.get("APPDATA") or os.path.expanduser("~")
    local = (
        localappdata
        or os.environ.get("LOCALAPPDATA")
        or os.environ.get("APPDATA")
        or os.path.expanduser("~")
    )
    config_dir = os.path.join(roaming, APP_NAME)
    data_dir = os.path.join(local, APP_NAME)
    cache_dir = os.path.join(data_dir, "cache")
    return {
        "config_dir": config_dir,
        "data_dir": data_dir,
        "cache_dir": cache_dir,
        "settings_path": os.path.join(config_dir, "settings.json"),
        "history_path": os.path.join(data_dir, "history.jsonl"),
        "notes_path": os.path.join(data_dir, "notes.json"),
        "lock_path": os.path.join(cache_dir, "flowd.lock"),
    }


# ---------------------------------------------------------------------------
# Start-at-login via HKCU Run (no console window, no .bat encoding traps)
# ---------------------------------------------------------------------------

_RUN_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "flow-linux"


def _get_winreg():
    """Return the stdlib ``winreg`` module, or None off-Windows."""
    try:
        import winreg

        return winreg
    except ImportError:
        return None


def run_command(python_exe: str) -> str:
    """Return the Run-value command that starts flowd windowlessly."""
    lowered = python_exe.lower()
    if lowered.endswith("python.exe") and not lowered.endswith("pythonw.exe"):
        python_exe = python_exe[: -len("python.exe")] + "pythonw.exe"
    return f'"{python_exe}" -m flow.flowd'


def startup_dir(appdata: str | None = None) -> str:
    """Return the per-user Startup folder (legacy .bat cleanup)."""
    roaming = appdata or os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(
        roaming, "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
    )


def launcher_path(appdata: str | None = None) -> str:
    """Return the legacy Startup .bat path (removed on migrate/disable)."""
    return os.path.join(startup_dir(appdata), STARTUP_LAUNCHER_NAME)


def autostart_is_enabled() -> bool | None:
    """True when start-at-login is on; None when indeterminable."""
    reg = _get_winreg()
    if reg is None:
        return None
    try:
        with reg.OpenKey(reg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            reg.QueryValueEx(key, _RUN_VALUE)
            return True
    except FileNotFoundError:
        pass
    except OSError:
        return None
    try:
        return os.path.isfile(launcher_path())
    except OSError:
        return None


def _remove_run_value(reg) -> None:
    try:
        with reg.OpenKey(
            reg.HKEY_CURRENT_USER, _RUN_KEY, 0, reg.KEY_SET_VALUE
        ) as key:
            reg.DeleteValue(key, _RUN_VALUE)
    except OSError:
        pass


def _remove_legacy_bat() -> None:
    try:
        path = launcher_path()
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def autostart_set_enabled(
    on: bool,
    python_exe: str | None = None,
    app_dir: str | None = None,
) -> bool:
    """Enable/disable start-at-login. ``False`` on failure, never raises.

    Enabling writes an HKCU Run value pointing at ``pythonw`` (no console
    window). A legacy Startup-folder ``.bat`` is removed as a migration.
    ``app_dir`` is accepted for API compatibility and ignored: Run values
    need no working directory (all flowd paths are absolute).
    """
    reg = _get_winreg()
    if reg is None:
        return False
    try:
        if not on:
            _remove_run_value(reg)
            _remove_legacy_bat()
            return True
        if not python_exe:
            return False
        with reg.OpenKey(
            reg.HKEY_CURRENT_USER, _RUN_KEY, 0, reg.KEY_SET_VALUE
        ) as key:
            reg.SetValueEx(
                key, _RUN_VALUE, 0, reg.REG_SZ, run_command(python_exe)
            )
        _remove_legacy_bat()
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Single-instance lock
# ---------------------------------------------------------------------------


def take_instance_lock(path: str | None = None) -> Any | None:
    """Non-blocking single-instance lock. Returns open file or None if held.

    On Windows the handle is locked with ``msvcrt.locking`` (releases on
    process death, so a stale lock is impossible). Off-Windows the file is
    created and returned unlocked as a documented dev/test fallback —
    single-instance is not enforced there.
    """
    resolved = path or app_dirs()["lock_path"]
    try:
        os.makedirs(os.path.dirname(resolved), exist_ok=True)
        fh = open(resolved, "w")
    except OSError:
        return None
    try:
        import msvcrt
    except ImportError:
        return fh  # dev fallback: no enforcement off-Windows
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except (OSError, IOError):
        try:
            fh.close()
        except OSError:
            pass
        return None
    return fh


HOTKEY_BACKENDS["windows"] = WindowsBackend
TYPER_BACKENDS["winsendinput"] = WinSendInputTyper
