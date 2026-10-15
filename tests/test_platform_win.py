"""Windows platform backends: pure-logic + mocked tests (pass on Linux).

Covers :mod:`flow.platform.windows`. No Windows API is touched at import;
every live path is an injected seam (``listener_factory``, ``sender``,
``_api``) driven by fakes here. Tests that need a real Windows host are
marked to skip off-Windows.
"""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

from flow.config import Settings
from flow.hotkey_base import HOTKEY_BACKENDS, Action
from flow.platform import windows as win
from flow.typer_base import TYPER_BACKENDS

needs_windows = pytest.mark.skipif(
    sys.platform != "win32", reason="needs a real Windows host"
)


def test_import_has_no_windows_api() -> None:
    assert "ctypes.windll" not in sys.modules
    assert "msvcrt" not in sys.modules
    assert "pynput" not in sys.modules
    assert win.is_windows() == (sys.platform == "win32")


def test_registry() -> None:
    assert HOTKEY_BACKENDS["windows"] is win.WindowsBackend
    assert TYPER_BACKENDS["winsendinput"] is win.WinSendInputTyper


PARSE_CASES = [
    ("Ctrl+Win+d", (frozenset({"ctrl", "win"}), "d")),
    ("Control+Super+h", (frozenset({"ctrl", "win"}), "h")),
    ("Alt+W", (frozenset({"alt"}), "w")),
    ("Alt+E", (frozenset({"alt"}), "e")),
    ("Meta+G", (frozenset({"win"}), "g")),
    ("Meta+Space", (frozenset({"win"}), "space")),
    ("Shift+Alt+z", (frozenset({"shift", "alt"}), "z")),
    ("Escape", (frozenset(), "escape")),
    ("Esc", (frozenset(), "escape")),
    ("F5", (frozenset(), "f5")),
    ("f12", (frozenset(), "f12")),
    ("Ctrl+F24", (frozenset({"ctrl"}), "f24")),
    ("Ctrl+5", (frozenset({"ctrl"}), "5")),
    ("Ctrl+Tab", (frozenset({"ctrl"}), "tab")),
]


@pytest.mark.parametrize("spec, expected", PARSE_CASES)
def test_parse_shortcut_table(spec: str, expected: tuple) -> None:
    assert win.parse_shortcut(spec) == expected


REJECT_CASES = [
    "",
    "   ",
    "w",  # bare letter
    "A",  # bare letter
    "Ctrl",  # modifier-only
    "Ctrl+Shift",  # modifier-only
    "Ctrl+Ctrl+d",  # duplicate modifier
    "Ctrl+d+e",  # extra key
    "Button1",  # mouse
    "mouse1",  # mouse
    "Ctrl+NoSuchKey",  # unknown key
    "Ctrl+,d",  # empty token
    "Ctrl++d",  # empty token
    "Ctrl+d,Alt+e",  # parse_shortcut takes a single binding
    "F25",  # out of range
    "F0",  # out of range
]


@pytest.mark.parametrize("spec", REJECT_CASES)
def test_parse_shortcut_rejects(spec: str) -> None:
    with pytest.raises(ValueError):
        win.parse_shortcut(spec)


def test_parse_bindings() -> None:
    assert win.parse_bindings("Alt+W, Alt+E") == [
        (frozenset({"alt"}), "w"),
        (frozenset({"alt"}), "e"),
    ]
    with pytest.raises(ValueError):
        win.parse_bindings("Alt+W,  ,Alt+E")
    with pytest.raises(ValueError):
        win.parse_bindings("")


def test_resolve_ptt_down_double_tap() -> None:
    resolve = win.resolve_ptt_down
    assert win.PTT_DOUBLE_TAP_S == pytest.approx(0.350)
    action, remembered = resolve(None, 100.0)
    assert action is Action.PTT_DOWN
    assert remembered == 100.0
    action, remembered = resolve(100.0, 100.0 + 0.349)
    assert action is Action.HANDSFREE_TOGGLE
    assert remembered is None
    action, remembered = resolve(100.0, 100.0 + 0.351)
    assert action is Action.PTT_DOWN
    assert remembered == 100.0 + 0.351


NORMALIZE_CASES = [
    ("w", ("key", "w")),
    ("W", ("key", "w")),
    ("Escape", ("key", "escape")),
    ("F5", ("key", "f5")),
    ("ctrl", ("mod", "ctrl")),
    ("Shift", ("mod", "shift")),
    ("", ("unknown", None)),
    ("NoSuchKey", ("unknown", None)),
    (SimpleNamespace(name="ctrl_l"), ("mod", "ctrl")),
    (SimpleNamespace(name="shift_r"), ("mod", "shift")),
    (SimpleNamespace(name="alt_gr"), ("mod", "alt")),
    (SimpleNamespace(name="cmd"), ("mod", "win")),
    (SimpleNamespace(name="cmd_l"), ("mod", "win")),
    (SimpleNamespace(name="esc"), ("key", "escape")),
    (SimpleNamespace(name="space"), ("key", "space")),
    (SimpleNamespace(name="enter"), ("key", "enter")),
    (SimpleNamespace(name="f12"), ("key", "f12")),
    (SimpleNamespace(name="media_play_pause"), ("unknown", None)),
    (SimpleNamespace(char="w", vk=87), ("key", "w")),
    (SimpleNamespace(char=None, vk=0x41), ("key", "a")),
    (SimpleNamespace(char=None, vk=0x35), ("key", "5")),
    (SimpleNamespace(char=None, vk=0x74), ("key", "f5")),  # VK_F5
    (SimpleNamespace(char=None, vk=0x1B), ("key", "escape")),
    (SimpleNamespace(char=None, vk=0x0D), ("key", "enter")),
    (SimpleNamespace(char=None, vk=None), ("unknown", None)),
    (SimpleNamespace(), ("unknown", None)),
    (None, ("unknown", None)),
]


@pytest.mark.parametrize("key, expected", NORMALIZE_CASES)
def test_normalize_listener_key(key, expected: tuple) -> None:
    assert win.normalize_listener_key(key) == expected


class FakeListener:
    """Test double with the pynput Listener start/stop shape."""

    def __init__(self, on_press, on_release, event_filter=None) -> None:
        self.on_press = on_press
        self.on_release = on_release
        self.event_filter = event_filter
        self.started = False
        self.stopped = False

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def tap(self, key) -> None:
        self.on_press(key)
        self.on_release(key)


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def backend():
    """A started WindowsBackend with fake listener + clock."""
    created: dict = {}
    clock = FakeClock()

    def factory(on_press, on_release, event_filter=None):
        created["listener"] = FakeListener(on_press, on_release)
        return created["listener"]

    actions: list[Action] = []
    backend = win.WindowsBackend(listener_factory=factory, clock=clock)
    backend.start(Settings(), actions.append)
    assert created["listener"].started is True
    yield backend, created["listener"], clock, actions
    backend.stop()
    assert created["listener"].stopped is True


def test_start_invalid_shortcut_raises_runtime_error() -> None:
    """Binding errors surface as RuntimeError (flowd's contract)."""
    backend = win.WindowsBackend(
        listener_factory=lambda p, r, f=None: FakeListener(p, r, f)
    )
    bad = Settings(ptt_shortcut="Ctrl+NoSuchKey")
    with pytest.raises(RuntimeError, match="hotkey backend failed"):
        backend.start(bad, lambda action: None)
    assert backend.running is False


def chord(listener: FakeListener, *keys) -> None:
    """Press mods+key in order, release in reverse (like a real chord)."""
    for key in keys:
        listener.on_press(key)
    for key in reversed(keys):
        listener.on_release(key)


def test_backend_hold_to_talk(backend) -> None:
    _, listener, clock, actions = backend
    listener.on_press("alt")
    listener.on_press("w")
    assert actions == [Action.PTT_DOWN]
    clock.advance(1.0)
    listener.on_release("w")
    listener.on_release("alt")
    assert actions == [Action.PTT_DOWN, Action.PTT_UP]


def test_backend_release_matches_without_mods(backend) -> None:
    # Letting go of the modifier first must not wedge the utterance.
    _, listener, clock, actions = backend
    listener.on_press("alt")
    listener.on_press("w")
    listener.on_release("alt")  # modifier released before the key
    clock.advance(1.0)
    listener.on_release("w")
    assert actions == [Action.PTT_DOWN, Action.PTT_UP]


def test_backend_double_tap_handsfree(backend) -> None:
    _, listener, clock, actions = backend
    chord(listener, "alt", "w")
    clock.advance(0.2)
    chord(listener, "alt", "w")
    assert actions == [
        Action.PTT_DOWN,
        Action.PTT_UP,
        Action.HANDSFREE_TOGGLE,
    ]


def test_backend_slow_second_press_is_ptt(backend) -> None:
    _, listener, clock, actions = backend
    chord(listener, "alt", "w")
    clock.advance(1.0)
    chord(listener, "alt", "w")
    assert actions == [
        Action.PTT_DOWN,
        Action.PTT_UP,
        Action.PTT_DOWN,
        Action.PTT_UP,
    ]


def test_backend_autorepeat_suppressed(backend) -> None:
    _, listener, clock, actions = backend
    listener.on_press("alt")
    listener.on_press("w")
    listener.on_press("w")  # held-key repeat: no second PTT_DOWN
    listener.on_press("w")
    clock.advance(1.0)
    listener.on_release("w")
    listener.on_release("alt")
    assert actions == [Action.PTT_DOWN, Action.PTT_UP]


def test_backend_command_paste_copy_cancel(backend) -> None:
    _, listener, _clock, actions = backend
    # Default command/paste/copy chords (Alt+G/B/C on every platform).
    chord(listener, "alt", "g")
    chord(listener, "alt", "b")
    chord(listener, "alt", "c")
    listener.tap("escape")
    # Hands-free tap binding (Alt+E).
    listener.on_press("alt")
    listener.on_press("e")
    listener.on_release("e")
    listener.on_release("alt")
    assert actions == [
        Action.COMMAND_DOWN,
        Action.COMMAND_UP,
        Action.PASTE_LAST,
        Action.COPY_LAST,
        Action.CANCEL,
        Action.HANDSFREE_TOGGLE,
    ]


def test_backend_cancel_wins_with_mods_held(backend) -> None:
    _, listener, _clock, actions = backend
    listener.on_press("ctrl")
    listener.on_press("escape")
    listener.on_release("escape")
    listener.on_release("ctrl")
    assert actions == [Action.CANCEL]


def test_backend_wrong_mods_ignored(backend) -> None:
    _, listener, _clock, actions = backend
    chord(listener, "ctrl", "w")  # PTT is Alt+W, not Ctrl+W
    listener.tap("q")  # unbound key entirely
    assert actions == []


def test_backend_unknown_keys_ignored(backend) -> None:
    _, listener, _clock, actions = backend
    listener.on_press(SimpleNamespace(name="media_play_pause"))
    listener.on_release(SimpleNamespace(name="media_play_pause"))
    listener.on_press(None)
    assert actions == []


def test_backend_double_start_and_dispatch_errors() -> None:
    created: dict = {}

    def factory(on_press, on_release, event_filter=None):
        created["listener"] = FakeListener(on_press, on_release)
        return created["listener"]

    def boom(_action: Action) -> None:
        raise RuntimeError("listener blew up")

    backend = win.WindowsBackend(listener_factory=factory)
    backend.start(Settings(), boom)
    with pytest.raises(RuntimeError):
        backend.start(Settings(), boom)
    # Dispatch exceptions are swallowed (logged), never raised to pynput.
    created["listener"].tap("escape")
    backend.stop()
    assert backend.running is False


def test_backend_factory_failure() -> None:
    def factory(on_press, on_release, event_filter=None):
        raise ImportError("no pynput here")

    backend = win.WindowsBackend(listener_factory=factory)
    with pytest.raises(RuntimeError, match="Windows hotkey backend failed"):
        backend.start(Settings(), lambda action: None)
    assert backend.running is False


@needs_windows
def test_backend_live_pynput_listener() -> None:
    """Live check (Windows only): a real pynput Listener starts/stops."""
    from pynput.keyboard import Controller

    actions: list[Action] = []
    backend = win.WindowsBackend()
    backend.start(Settings(), actions.append)
    try:
        assert backend.running is True
        Controller().tap("q")  # unbound key: expect silence, not errors
    finally:
        backend.stop()
    assert actions == []


KEYSPEC_CASES = [
    ("Ctrl+BackSpace", ((0x11,), 0x08)),
    ("Control+Bksp", ((0x11,), 0x08)),
    ("Ctrl+Z", ((0x11,), 0x5A)),
    ("Ctrl+A", ((0x11,), 0x41)),
    ("Ctrl+Shift+Z", ((0x11, 0x10), 0x5A)),
    ("Alt+F4", ((0x12,), 0x73)),
    ("Win+R", ((0x5B,), 0x52)),
    ("F5", ((), 0x74)),
    ("Escape", ((), 0x1B)),
    ("Enter", ((), 0x0D)),
    ("Delete", ((), 0x2E)),
    ("Ctrl+;", ((0x11,), 0xBA)),
]


@pytest.mark.parametrize("spec, expected", KEYSPEC_CASES)
def test_parse_keyspec_table(spec: str, expected: tuple) -> None:
    assert win.parse_keyspec(spec) == expected


KEYSPEC_REJECTS = ["", "   ", "Ctrl", "Ctrl+Shift", "Ctrl+Ctrl+Z",
                   "Ctrl+Z+A", "Ctrl+NoSuchKey", "Ctrl++Z"]


@pytest.mark.parametrize("spec", KEYSPEC_REJECTS)
def test_parse_keyspec_rejects(spec: str) -> None:
    with pytest.raises(ValueError):
        win.parse_keyspec(spec)


def test_plan_unicode_events_ascii() -> None:
    assert win.plan_unicode_events("A!") == [
        ("unicode_down", 0x41),
        ("unicode_up", 0x41),
        ("unicode_down", 0x21),
        ("unicode_up", 0x21),
    ]


def test_plan_unicode_events_newline_is_enter() -> None:
    assert win.plan_unicode_events("\n") == [("vk_down", 0x0D), ("vk_up", 0x0D)]


def test_plan_unicode_events_surrogate_pair() -> None:
    # U+1F600 GRINNING FACE -> UTF-16 surrogate pair D83D DE00.
    assert win.plan_unicode_events("\U0001F600") == [
        ("unicode_down", 0xD83D),
        ("unicode_up", 0xD83D),
        ("unicode_down", 0xDE00),
        ("unicode_up", 0xDE00),
    ]


def test_plan_keyspec_events_order() -> None:
    assert win.plan_keyspec_events("Ctrl+Shift+Z") == [
        ("vk_down", 0x11),
        ("vk_down", 0x10),
        ("vk_down", 0x5A),
        ("vk_up", 0x5A),
        ("vk_up", 0x10),
        ("vk_up", 0x11),
    ]
    with pytest.raises(ValueError):
        win.plan_keyspec_events("Ctrl")


class FakeSender:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[list[tuple[str, int]]] = []

    def __call__(self, events: list[tuple[str, int]]) -> bool:
        self.calls.append(list(events))
        return self.result


def test_typer_unavailable_off_windows() -> None:
    if sys.platform == "win32":
        pytest.skip("Windows-only assertion inverted")
    assert win.WinSendInputTyper.available() is False


def test_typer_type_text_uses_sender() -> None:
    sender = FakeSender()
    typer = win.WinSendInputTyper(sender=sender)
    assert typer.type_text("Hi") is True
    assert sender.calls == [[
        ("unicode_down", ord("H")),
        ("unicode_up", ord("H")),
        ("unicode_down", ord("i")),
        ("unicode_up", ord("i")),
    ]]


def test_typer_type_text_empty_and_none() -> None:
    sender = FakeSender()
    typer = win.WinSendInputTyper(sender=sender)
    assert typer.type_text("") is True
    assert sender.calls == []  # no-op: no SendInput round trip
    assert typer.type_text(None) is False  # type: ignore[arg-type]


def test_typer_sender_failure_and_exception() -> None:
    assert win.WinSendInputTyper(sender=FakeSender(False)).type_text("x") is False

    def boom(_events) -> bool:
        raise OSError("SendInput blocked")

    assert win.WinSendInputTyper(sender=boom).type_text("x") is False


def test_typer_press_keys() -> None:
    sender = FakeSender()
    typer = win.WinSendInputTyper(sender=sender)
    assert typer.press_keys("Ctrl+BackSpace") is True
    assert sender.calls == [[
        ("vk_down", 0x11),
        ("vk_down", 0x08),
        ("vk_up", 0x08),
        ("vk_up", 0x11),
    ]]
    assert typer.press_keys("Ctrl") is False
    assert typer.press_keys("") is False
    assert len(sender.calls) == 1  # invalid specs never reach SendInput


@needs_windows
def test_typer_live_available() -> None:
    assert win.WinSendInputTyper.available() is True


class FakeClipboardApi:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.seen: list[str] = []

    def run(self, text: str) -> bool:
        self.seen.append(text)
        return self.result


def test_copy_to_clipboard_with_fake_api() -> None:
    api = FakeClipboardApi()
    assert win.copy_to_clipboard("hello", _api=api) is True
    assert api.seen == ["hello"]
    assert win.copy_to_clipboard("x", _api=FakeClipboardApi(False)) is False

    class Boom:
        def run(self, text: str) -> bool:
            raise OSError("locked")

    assert win.copy_to_clipboard("x", _api=Boom()) is False


def test_copy_to_clipboard_default_off_windows() -> None:
    if sys.platform == "win32":
        pytest.skip("Windows-only assertion inverted")
    assert win.copy_to_clipboard("hello") is False


def test_app_dirs_layout(tmp_path) -> None:
    roaming = str(tmp_path / "Roaming")
    local = str(tmp_path / "Local")
    dirs = win.app_dirs(appdata=roaming, localappdata=local)
    assert dirs["config_dir"] == os.path.join(roaming, "flow-linux")
    assert dirs["data_dir"] == os.path.join(local, "flow-linux")
    assert dirs["cache_dir"] == os.path.join(local, "flow-linux", "cache")
    assert dirs["settings_path"].endswith("settings.json")
    assert dirs["history_path"].endswith("history.jsonl")
    assert dirs["notes_path"].endswith("notes.json")
    assert dirs["lock_path"].endswith("flowd.lock")


class FakeWinreg:
    """Dict-backed winreg double."""

    HKEY_CURRENT_USER = "HKCU"
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict = {}

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *exc) -> bool:
            return False

    def OpenKey(self, hive, path, reserved=0, access=0):
        return FakeWinreg._Key()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return (self.values[name], self.REG_SZ)

    def SetValueEx(self, key, name, reserved, typ, value) -> None:
        self.values[name] = value

    def DeleteValue(self, key, name) -> None:
        self.values.pop(name, None)


def test_run_command_prefers_pythonw() -> None:
    assert win.run_command("C:\\app\\.venv\\Scripts\\python.exe") == (
        '"C:\\app\\.venv\\Scripts\\pythonw.exe" -m flow.flowd'
    )
    assert win.run_command("/usr/bin/python3") == (
        '"/usr/bin/python3" -m flow.flowd'
    )


def test_startup_legacy_paths(tmp_path) -> None:
    appdata = str(tmp_path / "Roaming")
    assert win.startup_dir(appdata).endswith(
        os.path.join("Microsoft", "Windows", "Start Menu", "Programs", "Startup")
    )
    assert win.launcher_path(appdata).endswith("flow-linux.bat")


def test_autostart_registry_roundtrip(monkeypatch) -> None:
    reg = FakeWinreg()
    monkeypatch.setattr(win, "_get_winreg", lambda: reg)
    assert win.autostart_is_enabled() is False
    # Enabling without an interpreter fails cleanly.
    assert win.autostart_set_enabled(True) is False
    assert win.autostart_set_enabled(
        True, "C:\\app\\.venv\\Scripts\\python.exe"
    ) is True
    assert win.autostart_is_enabled() is True
    assert reg.values["flow-linux"].endswith('pythonw.exe" -m flow.flowd')
    assert win.autostart_set_enabled(False) is True
    assert win.autostart_is_enabled() is False
    # Disabling twice is still success.
    assert win.autostart_set_enabled(False) is True


def test_autostart_off_windows_is_indeterminate(monkeypatch) -> None:
    monkeypatch.setattr(win, "_get_winreg", lambda: None)
    assert win.autostart_is_enabled() is None
    assert win.autostart_set_enabled(True, "python.exe") is False


def test_autostart_migrates_legacy_bat(tmp_path, monkeypatch) -> None:
    reg = FakeWinreg()
    monkeypatch.setattr(win, "_get_winreg", lambda: reg)
    bat = tmp_path / "flow-linux.bat"
    bat.write_text("@echo off\r\n")
    monkeypatch.setattr(win, "launcher_path", lambda appdata=None: str(bat))
    assert win.autostart_is_enabled() is True  # legacy .bat counts
    assert win.autostart_set_enabled(True, "C:\\py\\python.exe") is True
    assert not bat.exists()  # migrated away
    assert win.autostart_is_enabled() is True


def test_take_instance_lock_dev_fallback(tmp_path) -> None:
    path = str(tmp_path / "cache" / "flowd.lock")
    fh = win.take_instance_lock(path)
    assert fh is not None
    assert os.path.isfile(path)
    fh.close()


# ---------------------------------------------------------------------------
# Gap coverage appended during parallel-effort review (2026-09-18).
#
# These tests exercise branches the original section left open: the Windows
# msvcrt lock path (via a stubbed msvcrt module, so it runs on Linux), the
# default SendInput sender off-Windows, APPDATA/LOCALAPPDATA fallbacks,
# stop()-before-start, and non-string typer inputs. They use only the
# existing `win` (flow.platform.windows) import and fixtures above.
# ---------------------------------------------------------------------------


def test_take_instance_lock_with_stub_msvcrt(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Windows msvcrt branch, simulated on Linux via a stub module."""
    calls: list[tuple] = []

    def fake_locking(fd: int, mode: int, nbytes: int) -> None:
        calls.append((fd, mode, nbytes))

    stub = SimpleNamespace(LK_NBLCK=1, locking=fake_locking)
    monkeypatch.setitem(sys.modules, "msvcrt", stub)
    path = str(tmp_path / "flowd.lock")
    fh = win.take_instance_lock(path)
    assert fh is not None
    fh.close()
    assert calls and calls[0][1:] == (1, 1)


def test_take_instance_lock_held_or_bad_path(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def held(fd: int, mode: int, nbytes: int) -> None:
        raise OSError("locked by another flowd")

    monkeypatch.setitem(
        sys.modules, "msvcrt", SimpleNamespace(LK_NBLCK=1, locking=held)
    )
    assert win.take_instance_lock(str(tmp_path / "flowd.lock")) is None

    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    assert win.take_instance_lock(str(blocker / "flowd.lock")) is None


def test_send_events_via_sendinput_off_windows() -> None:
    if sys.platform == "win32":
        pytest.skip("Linux-only assertion")
    assert win._send_events_via_sendinput([("unicode_down", 0x41)]) is False


def test_typer_non_string_inputs() -> None:
    sender = FakeSender()
    typer = win.WinSendInputTyper(sender=sender)
    assert typer.type_text(123) is False  # type: ignore[arg-type]
    assert typer.press_keys(None) is False  # type: ignore[arg-type]
    assert sender.calls == []


def test_backend_stop_without_start_and_raising_stop() -> None:
    backend = win.WindowsBackend(listener_factory=lambda p, r, f=None: FakeListener(p, r, f))
    backend.stop()  # never started: no-op, must not raise
    assert backend.running is False

    class RaisingStop(FakeListener):
        def stop(self) -> None:
            raise RuntimeError("listener stop exploded")

    created: dict = {}

    def factory(on_press, on_release, event_filter=None):
        created["listener"] = RaisingStop(on_press, on_release)
        return created["listener"]

    backend = win.WindowsBackend(listener_factory=factory)
    backend.start(Settings(), lambda action: None)
    backend.stop()  # stop errors are swallowed (logged)
    assert backend.running is False


def test_app_dirs_env_fallbacks(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.delenv("LOCALAPPDATA", raising=False)
    dirs = win.app_dirs()
    assert dirs["config_dir"] == os.path.join(
        str(tmp_path / "Roaming"), "flow-linux"
    )
    # LOCALAPPDATA falls back to APPDATA.
    assert dirs["data_dir"] == os.path.join(
        str(tmp_path / "Roaming"), "flow-linux"
    )

    monkeypatch.delenv("APPDATA", raising=False)
    home = os.path.expanduser("~")
    dirs = win.app_dirs()
    assert dirs["config_dir"] == os.path.join(home, "flow-linux")

    assert win.startup_dir(str(tmp_path)).endswith("Startup")


def test_input_struct_abi_size() -> None:
    """SendInput rejects a wrong cbSize: INPUT is 40/28 bytes."""
    import ctypes
    import struct

    if struct.calcsize("P") == 8:
        assert ctypes.sizeof(win.INPUT) == 40
        assert ctypes.sizeof(win.KEYBDINPUT) == 24
        assert ctypes.sizeof(win.MOUSEINPUT) == 32
    else:
        assert ctypes.sizeof(win.INPUT) == 28
        assert ctypes.sizeof(win.KEYBDINPUT) == 16
        assert ctypes.sizeof(win.MOUSEINPUT) == 24


def test_shared_key_release_pairs_with_armed_kind() -> None:
    """Alt+W + Ctrl+W: Ctrl+W release emits COMMAND_UP, not PTT."""

    def factory(on_press, on_release, event_filter=None):
        return FakeListener(on_press, on_release, event_filter)

    actions: list = []
    backend = win.WindowsBackend(listener_factory=factory)
    settings = Settings(ptt_shortcut="Alt+W", command_shortcut="Ctrl+W")
    backend.start(settings, actions.append)
    try:
        listener = backend._listener
        chord(listener, "ctrl", "w")
        assert actions == [Action.COMMAND_DOWN, Action.COMMAND_UP]
    finally:
        backend.stop()


def test_stuck_modifier_healed_by_reader() -> None:
    """A physically-released Win key stops shadowing hotkeys."""

    def factory(on_press, on_release, event_filter=None):
        return FakeListener(on_press, on_release, event_filter)

    actions: list = []
    backend = win.WindowsBackend(
        listener_factory=factory, mod_reader=lambda: frozenset({"alt"})
    )
    backend.start(Settings(ptt_shortcut="Alt+W"), actions.append)
    try:
        listener = backend._listener
        listener.on_press("win")  # stuck: release swallowed by Win+L
        chord(listener, "alt", "w")  # reader says only alt is held
        assert actions == [Action.PTT_DOWN, Action.PTT_UP]
    finally:
        backend.stop()


def test_backend_passes_event_filter_to_factory() -> None:
    seen: dict = {}

    def factory(on_press, on_release, event_filter=None):
        seen["filter"] = event_filter
        return FakeListener(on_press, on_release, event_filter)

    backend = win.WindowsBackend(listener_factory=factory)
    backend.start(Settings(), lambda action: None)
    try:
        assert callable(seen["filter"])
    finally:
        backend.stop()


def test_chord_suppressor_down_up_pair() -> None:
    table = [
        (frozenset({"alt"}), "w", "ptt", False),
        (frozenset(), "escape", "cancel", True),
    ]
    sup = win._ChordSuppressor(table)
    assert sup.should_suppress(0x57, 0x100, frozenset({"alt"})) is True
    assert sup.should_suppress(0x57, 0x101, frozenset()) is True
    assert sup.should_suppress(0x57, 0x101, frozenset()) is False


def test_chord_suppressor_ignores_bare_keys_and_mods() -> None:
    table = [(frozenset({"alt"}), "w", "ptt", False)]
    sup = win._ChordSuppressor(table)
    assert sup.should_suppress(0x57, 0x100, frozenset()) is False
    assert sup.should_suppress(0x12, 0x100, frozenset({"alt"})) is False
    assert sup.should_suppress(0x41, 0x100, frozenset({"alt"})) is False


def test_chord_suppressor_never_swallows_bare_escape() -> None:
    table = [(frozenset(), "escape", "cancel", True)]
    sup = win._ChordSuppressor(table)
    assert sup.should_suppress(0x1B, 0x100, frozenset()) is False


def test_hook_filter_drops_injected_and_chords() -> None:
    table = [(frozenset({"alt"}), "w", "ptt", False)]
    filt = win._make_hook_filter(
        win._ChordSuppressor(table), lambda: frozenset({"alt"})
    )
    injected = SimpleNamespace(flags=0x10, vkCode=0x57)
    assert filt(0x100, injected) is False
    physical = SimpleNamespace(flags=0x00, vkCode=0x57)
    assert filt(0x100, physical) is False  # chord down suppressed
    other = SimpleNamespace(flags=0x00, vkCode=0x41)
    assert filt(0x100, other) is True


def test_wait_for_modifiers_released() -> None:
    idle = SimpleNamespace(GetAsyncKeyState=lambda vk: 0)
    win._wait_for_modifiers_released(idle, timeout_s=0)
    win._wait_for_modifiers_released(object(), timeout_s=0)


def _wired_backend(settings, actions, mods_cell):
    """Backend whose factory captures the hook filter for direct driving."""
    created: dict = {}

    def factory(on_press, on_release, event_filter=None):
        created["listener"] = FakeListener(on_press, on_release, event_filter)
        return created["listener"]

    backend = win.WindowsBackend(
        listener_factory=factory,
        clock=FakeClock(),
        mod_reader=lambda: mods_cell["held"],
    )
    backend.start(settings, actions.append)
    return backend, created["listener"]


def test_modified_cancel_requires_configured_modifiers() -> None:
    def factory(on_press, on_release, event_filter=None):
        return FakeListener(on_press, on_release, event_filter)

    actions: list = []
    backend = win.WindowsBackend(listener_factory=factory, clock=FakeClock())
    backend.start(Settings(cancel_key="Ctrl+Q"), actions.append)
    try:
        listener = backend._listener
        listener.on_press("q")  # plain typing: not a cancel
        listener.on_release("q")
        assert actions == []
        chord(listener, "ctrl", "q")
        assert actions == [Action.CANCEL]
    finally:
        backend.stop()


def test_bare_escape_cancels_with_modifiers_held() -> None:
    def factory(on_press, on_release, event_filter=None):
        return FakeListener(on_press, on_release, event_filter)

    actions: list = []
    backend = win.WindowsBackend(listener_factory=factory, clock=FakeClock())
    backend.start(Settings(), actions.append)
    try:
        listener = backend._listener
        chord(listener, "alt", "escape")
        assert actions == [Action.CANCEL]
    finally:
        backend.stop()


def test_default_factory_uses_win32_event_filter_kwarg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    seen: dict = {}

    class SpyListener:
        def __init__(self, *args, **kwargs) -> None:
            seen["args"] = args
            seen["kwargs"] = kwargs

    pkg = types.ModuleType("pynput")
    mod = types.ModuleType("pynput.keyboard")
    mod.Listener = SpyListener
    monkeypatch.setitem(sys.modules, "pynput", pkg)
    monkeypatch.setitem(sys.modules, "pynput.keyboard", mod)
    filt = object()
    win._default_listener_factory(lambda k: None, lambda k: None, filt)
    assert seen["kwargs"].get("win32_event_filter") is filt
    assert "event_filter" not in seen["kwargs"]


def test_filter_dispatches_chord_once_without_suppress_support() -> None:
    actions: list = []
    mods = {"held": frozenset({"alt"})}
    backend, listener = _wired_backend(Settings(), actions, mods)
    try:
        filt = listener.event_filter
        down = SimpleNamespace(flags=0x00, vkCode=0x57)
        assert filt(0x104, down) is False  # WM_SYSKEYDOWN for Alt+W
        assert actions == [Action.PTT_DOWN]
        assert filt(0x104, down) is False  # autorepeat: no re-dispatch
        assert actions == [Action.PTT_DOWN]
        mods["held"] = frozenset()  # Alt released first: latch holds
        assert filt(0x104, down) is False
        assert actions == [Action.PTT_DOWN]
        assert filt(0x101, down) is False  # key-up still pairs
        assert actions == [Action.PTT_DOWN, Action.PTT_UP]
    finally:
        backend.stop()


def test_filter_propagates_suppress_event() -> None:
    class SuppressRaised(Exception):
        pass

    class SuppressingListener(FakeListener):
        def __init__(self, *args, **kwargs) -> None:
            super().__init__(*args, **kwargs)
            self.suppressed = 0

        def suppress_event(self) -> None:
            self.suppressed += 1
            raise SuppressRaised()

    created: dict = {}

    def factory(on_press, on_release, event_filter=None):
        created["listener"] = SuppressingListener(
            on_press, on_release, event_filter
        )
        return created["listener"]

    actions: list = []
    backend = win.WindowsBackend(
        listener_factory=factory,
        clock=FakeClock(),
        mod_reader=lambda: frozenset({"alt"}),
    )
    backend.start(Settings(), actions.append)
    try:
        filt = created["listener"].event_filter
        down = SimpleNamespace(flags=0x00, vkCode=0x57)
        with pytest.raises(SuppressRaised):
            filt(0x100, down)
        assert actions == [Action.PTT_DOWN]  # deliberately dispatched
        assert created["listener"].suppressed == 1
    finally:
        backend.stop()


def test_filter_hides_injected_input_without_dispatch() -> None:
    actions: list = []
    mods = {"held": frozenset({"alt"})}
    backend, listener = _wired_backend(Settings(), actions, mods)
    try:
        filt = listener.event_filter
        for flags in (0x10, 0x02):  # injected + lower-IL injected
            injected = SimpleNamespace(flags=flags, vkCode=0x57)
            assert filt(0x100, injected) is False
        assert actions == []
    finally:
        backend.stop()


def test_filter_passes_bare_escape_to_callbacks() -> None:
    actions: list = []
    mods = {"held": frozenset()}
    backend, listener = _wired_backend(Settings(), actions, mods)
    try:
        filt = listener.event_filter
        esc = SimpleNamespace(flags=0x00, vkCode=0x1B)
        assert filt(0x100, esc) is True  # system delivery kept
        listener.on_press("escape")  # ...but Flow still cancels
        assert actions == [Action.CANCEL]
    finally:
        backend.stop()


def test_suppressor_latch_expires() -> None:
    table = [(frozenset({"alt"}), "w", "ptt", False)]
    clock = FakeClock()
    sup = win._ChordSuppressor(table, clock=clock)
    assert sup.should_suppress(0x57, 0x100, frozenset({"alt"})) is True
    clock.advance(61.0)
    assert sup.is_latched(0x57) is False
    assert sup.should_suppress(0x57, 0x101, frozenset()) is False
