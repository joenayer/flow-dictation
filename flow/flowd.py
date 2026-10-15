"""flowd: local Wispr Flow-style dictation service (integrator-owned).

Hot loop: global PTT event -> pill=recording -> 16 kHz capture -> release
-> warm-model batch transcribe -> cleanup -> type at cursor -> history.
Esc cancels. Double-tap PTT toggles hands-free (VAD auto-stop).

Modes:
  flowd               run the service (Qt pill + tray + hotkeys)
  flowd --smoke --fixture WAV --expect SUBSTR
                      headless offline check: transcribe WAV, require SUBSTR
"""

from __future__ import annotations

import argparse
import logging
import os
import queue
import signal
import sys
import threading

from flow.audio import default_capture
from flow.audio_base import AudioCapture
from flow.cleanup import clean
from flow.commands import handle_command
from flow.config import Settings, load_settings, save_settings
from flow.events import EventBus, SessionState
from flow.history import TranscriptStore
from flow.hotkey_base import HOTKEY_BACKENDS, Action

# Side-effect imports: register engines, hotkey backends, typers.
import flow.hotkey_wayland  # noqa: F401

if sys.platform != "win32":  # W6: xlib is Linux-only; win32 has no X11
    import flow.hotkey_x11  # noqa: F401

if sys.platform == "win32":  # Windows backends ("windows"/"winsendinput")
    import flow.platform.windows  # noqa: F401
import flow.stt_moonshine  # noqa: F401
import flow.stt_parakeet  # noqa: F401
from flow.stt_base import ENGINES, STTEngine
from flow.typer_base import TyperBackend
from flow.vad import VADGate

import flow.type_select as type_select  # noqa: E402

log = logging.getLogger("flowd")


def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_models_dir(models_dir: str) -> str:
    if os.path.isabs(models_dir):
        return models_dir
    return os.path.join(repo_root(), models_dir)


def select_hotkey_name(session_type: str) -> str:
    """Pure backend pick: Wayland sessions use the portal stub, else X11."""
    if session_type.strip().lower() == "wayland":
        return "wayland"
    return "x11"


class FlowService:
    """Owns capture/transcribe/type state. Qt-agnostic; UI polls pump()."""

    def __init__(
        self, settings: Settings, history_path: str | None = None
    ) -> None:
        self.settings = settings
        self.bus = EventBus()
        self.state = SessionState.IDLE
        self._queue: queue.Queue = queue.Queue()
        self._capture: AudioCapture | None = None
        self._engine: STTEngine | None = None
        self._typer: TyperBackend | None = None
        self._typers: list[TyperBackend] = []
        self._history = TranscriptStore(path=history_path)
        self._vad: VADGate | None = None
        self._handsfree = False
        self._command_mode = False
        self._cancelled = False
        self._vad_stop_requested = False
        self._worker: threading.Thread | None = None
        # Guards engine pointer + busy transitions so an engine reload
        # can never commit while a transcription worker is being
        # launched (worker launch and reload commit are atomic peers).
        self._session_lock = threading.Lock()
        # Which accepted start owns the recording: "ptt" | "handsfree" |
        # "command". Releases pair to the owner; other modes' releases
        # are ignored instead of stealing the session.
        self._record_owner: str | None = None
        # Scratchpad sessions own their capture: global stop keys only
        # signal the loop instead of launching a second transcription.
        self._scratchpad_active = False
        self._scratchpad_stop = False
        self._record_window: int | None = None  # focus guard (None = skip)
        # Last scratchpad_dictate failure, cleared per call; None means the
        # last falsy result was a plain user cancel (or success).
        self.last_dictate_error: str | None = None

    # -- wiring ---------------------------------------------------------
    def setup(self) -> None:
        models_dir = resolve_models_dir(self.settings.models_dir)
        engine_cls = ENGINES.get(self.settings.engine)
        if engine_cls is None:
            raise RuntimeError(
                f"unknown engine {self.settings.engine!r} "
                f"(have: {sorted(ENGINES)})"
            )
        self._engine = engine_cls()
        self._engine.load(models_dir, threads=self.settings.stt_threads)
        self._typer = type_select.select_typer()
        self._typers = type_select.select_typers()
        if self._typer is None:
            # Clipboard-only mode (minimal Wayland without xdotool/xlib/
            # wtype/xclip): dictation still works via the Qt clipboard
            # fallback in _type_text; only key-press commands are lost.
            log.warning("no typer backend available; clipboard-only mode")
        self._vad = VADGate(models_dir=models_dir)
        log.info(
            "engine=%s typer=%s vad=%s",
            self.settings.engine,
            type_select.select_typer_name(),
            self._vad.backend,
        )

    def busy(self) -> bool:
        """True while recording or transcribing (engine swap unsafe)."""
        with self._session_lock:
            return self._busy_locked()

    def _busy_locked(self) -> bool:
        return self.state != SessionState.IDLE

    def reload_engine(self) -> None:
        """Load the configured engine, swap it in on success.

        Refuses while busy so a worker can never touch a cleared engine;
        the old engine is kept when the new one fails to load. The slow
        load runs outside the lock, but the commit re-checks busyness
        atomically with the swap: a session started mid-load aborts the
        swap instead of unloading an engine a worker is using.
        """
        if self.busy():
            raise RuntimeError("cannot switch engine while dictating")
        models_dir = resolve_models_dir(self.settings.models_dir)
        engine_cls = ENGINES.get(self.settings.engine)
        if engine_cls is None:
            raise RuntimeError(f"unknown engine {self.settings.engine!r}")
        new_engine = engine_cls()
        new_engine.load(models_dir, threads=self.settings.stt_threads)
        with self._session_lock:
            if self._busy_locked():
                aborted = True
                old = None
            else:
                aborted = False
                old, self._engine = self._engine, new_engine
        if aborted:
            try:
                new_engine.unload()
            except Exception:  # noqa: BLE001 - best effort
                pass
            raise RuntimeError("cannot switch engine while dictating")
        if old is not None:
            try:
                old.unload()
            except Exception:  # noqa: BLE001 - best effort
                pass

    def scratchpad_dictate(self, timeout_s: float = 60.0) -> str | None:
        """Blocking record-until-silence for the scratchpad. Returns cleaned
        text or None. Pumps Qt events while waiting so the window stays
        alive; failures are recorded on ``last_dictate_error`` (None means
        the user cancelled) so the UI can explain them."""
        import time

        from PySide6.QtCore import QCoreApplication  # service context only

        assert self._engine is not None and self._vad is not None
        self.last_dictate_error = None
        if self.state != SessionState.IDLE or self._capture is not None:
            return None  # reentry guard: one capture at a time
        try:
            capture = default_capture()
        except RuntimeError as exc:
            self.last_dictate_error = f"Could not open microphone: {exc}"
            return None
        self._vad.reset()
        assert self._vad is not None

        def _feed(chunk) -> None:  # noqa: ANN001 - audio callback
            assert self._vad is not None
            self._vad.feed(chunk)
            self._on_chunk_level(chunk)

        try:
            capture.start(_feed)
        except RuntimeError as exc:
            self.last_dictate_error = f"Could not start recording: {exc}"
            return None
        self._capture = capture  # Esc cancels via _cancel()
        self._scratchpad_active = True
        self._scratchpad_stop = False
        self._cancelled = False
        self._set_state(SessionState.RECORDING)
        start = time.monotonic()
        samples = None
        try:
            while time.monotonic() - start < timeout_s:
                QCoreApplication.processEvents()
                if self.state != SessionState.RECORDING:
                    break  # cancelled via Esc
                if self._scratchpad_stop:
                    break  # stop key: transcribe once, to the note
                if self._vad.should_auto_stop():
                    break
                time.sleep(0.05)
        finally:
            # Exactly one finalization: _cancel() may already have
            # stopped and detached the capture — never re-stop it.
            if self._capture is capture:
                try:
                    samples = capture.stop()
                except Exception as exc:  # noqa: BLE001 - never leave open
                    samples = None
                    self.last_dictate_error = f"Microphone error: {exc}"
                self._capture = None
            else:
                samples = None
            self._scratchpad_active = False
        if self._cancelled:
            self._cancelled = False
            self._set_state(SessionState.IDLE)
            return None
        if samples is None:
            self._set_state(SessionState.IDLE)
            return None
        if samples.size < 4000:
            self._set_state(SessionState.IDLE)
            self.last_dictate_error = "No speech detected — hold a little longer"
            return None
        # Transcribe off the GUI thread while pumping events, so the window
        # stays responsive and Esc still cancels a slow transcription.
        # The engine is captured atomically with the PROCESSING
        # transition so a concurrent reload commit cannot unload it
        # underneath the worker.
        with self._session_lock:
            engine = self._engine
            self.state = SessionState.PROCESSING
        self.bus.emit("state", SessionState.PROCESSING)
        outcome: dict = {}

        def _transcribe() -> None:
            try:
                assert engine is not None
                outcome["text"] = engine.transcribe(samples).text or ""
            except Exception as exc:  # noqa: BLE001 - reported below
                outcome["error"] = exc

        worker = threading.Thread(target=_transcribe, daemon=True)
        worker.start()
        while worker.is_alive():
            QCoreApplication.processEvents()
            time.sleep(0.01)
        worker.join()
        self._set_state(SessionState.IDLE)
        if self._cancelled:
            self._cancelled = False
            return None
        if "error" in outcome:
            self.last_dictate_error = f"Transcription failed: {outcome['error']}"
            return None
        text = clean(outcome.get("text", "").strip(), self.settings)
        if not text:
            self.last_dictate_error = "No speech recognized"
            return None
        return text

    # -- hotkey dispatch (called from backend thread) --------------------
    def dispatch(self, action: Action) -> None:
        self._queue.put(("action", action))

    def pump(self) -> None:
        """Drain queue. Call on the main/Qt thread (e.g. QTimer tick)."""
        if self._vad_stop_requested and self.state == SessionState.RECORDING:
            self._vad_stop_requested = False
            self._finish_utterance()
        while True:
            try:
                kind, payload = self._queue.get_nowait()
            except queue.Empty:
                return
            if kind == "action":
                log.info("event action=%s", payload)
            elif kind == "transcript":
                log.info("event transcript=%r", payload[0][:60])
            else:
                log.info("event kind=%s", kind)
            if kind == "action":
                self._handle_action(payload)
            elif kind == "transcript":
                self._handle_transcript(*payload)
            elif kind == "error":
                self.bus.emit("error", payload)

    # -- actions ---------------------------------------------------------
    def _set_state(self, state: SessionState) -> None:
        self.state = state
        self.bus.emit("state", state)

    def _handle_action(self, action: Action) -> None:
        if action == Action.CANCEL:
            self._cancel()
        elif action == Action.PTT_DOWN:
            self._start_recording(handsfree=False, command=False)
        elif action == Action.PTT_UP:
            self._release_owned("ptt")
        elif action == Action.HANDSFREE_TOGGLE:
            if self._scratchpad_active:
                # Route to the owning workflow: stop transcribes once,
                # into the note — never via a second global worker.
                if self.state == SessionState.RECORDING:
                    self._scratchpad_stop = True
            elif self.state == SessionState.RECORDING:
                if self._record_owner == "handsfree":
                    self._finish_utterance()
                # else: owned by another mode; a foreign toggle must not
                # steal the session.
            elif self.state == SessionState.IDLE:
                self._start_recording(handsfree=True, command=False)
        elif action == Action.COMMAND_DOWN:
            self._start_recording(handsfree=False, command=True)
        elif action == Action.COMMAND_UP:
            self._release_owned("command")
        elif action == Action.PASTE_LAST:
            self._paste_last()
        elif action == Action.COPY_LAST:
            self._copy_last()

    def _release_owned(self, owner: str) -> None:
        """Finish a recording owned by *owner* (or stop the scratchpad).

        Releases pair to the accepted start that owns the session: a
        release for a rejected start or another mode is ignored instead
        of ending an unrelated recording.
        """
        if self.state != SessionState.RECORDING:
            return
        if self._scratchpad_active:
            self._scratchpad_stop = True
        elif self._record_owner == owner:
            self._finish_utterance()

    def _start_recording(self, handsfree: bool, command: bool) -> None:
        if self.state != SessionState.IDLE:
            return
        owner = "command" if command else ("handsfree" if handsfree else "ptt")
        self._record_window = _active_window()
        try:
            capture = default_capture()
        except RuntimeError as exc:
            self.bus.emit("error", str(exc))
            return
        self._handsfree = handsfree
        self._command_mode = command
        self._cancelled = False
        self._vad_stop_requested = False
        assert self._vad is not None
        self._vad.reset()
        try:
            capture.start(self._on_chunk)
        except RuntimeError as exc:
            # Backend open/start failures arrive translated (audio.py):
            # report loudly, hold no capture, stay idle.
            self.bus.emit("error", str(exc))
            return
        self._capture = capture
        self._record_owner = owner
        self._set_state(SessionState.RECORDING)

    def _on_chunk_level(self, chunk) -> None:
        try:
            n = len(chunk)
            rms = (sum(int(x) * int(x) for x in chunk) / max(1, n)) ** 0.5
        except Exception:
            rms = 0.0
        self.bus.emit("level", rms)

    def _on_chunk(self, chunk) -> None:
        # Capture thread: only observe; pump() acts (avoids stop-from-self).
        self._on_chunk_level(chunk)
        if self._handsfree and self._vad is not None:
            self._vad.feed(chunk)
            if self._vad.should_auto_stop():
                self._vad_stop_requested = True

    def _finish_utterance(self) -> None:
        # The engine is captured atomically with the PROCESSING
        # transition so a concurrent reload commit cannot unload it
        # underneath the worker.
        with self._session_lock:
            capture, self._capture = self._capture, None
            if capture is None or self.state != SessionState.RECORDING:
                return
            engine = self._engine
            mode = "command" if self._command_mode else "dictation"
            self.state = SessionState.PROCESSING
            self._record_owner = None
        try:
            samples = capture.stop()
        except Exception as exc:  # noqa: BLE001 - never break the loop
            self.bus.emit("error", f"capture stop failed: {exc}")
            self._set_state(SessionState.IDLE)
            return
        if samples.size < 4000:  # <0.25s: blip, not speech; skip
            self._set_state(SessionState.IDLE)
            return
        self.bus.emit("state", SessionState.PROCESSING)
        self._worker = threading.Thread(
            target=self._transcribe_worker,
            args=(samples, mode, engine),
            daemon=True,
        )
        self._worker.start()

    def _transcribe_worker(self, samples, mode: str, engine) -> None:
        try:
            assert engine is not None
            result = engine.transcribe(samples)
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            self._queue.put(("error", f"transcribe failed: {exc}"))
            self._queue.put(("transcript", ("", mode)))
            return
        self._queue.put(("transcript", (result.text, mode)))

    def _handle_transcript(self, text: str, mode: str) -> None:
        cancelled, self._cancelled = self._cancelled, False
        self._set_state(SessionState.IDLE)
        if cancelled:
            return
        text = (text or "").strip()
        if not text:
            return
        if mode == "command":
            result = handle_command(text, self.settings)
            if result.handled and result.keys:
                if self._typer is not None and self._typer.press_keys(
                    result.keys
                ):
                    self.bus.emit("command", result.keys)
                elif self._typer is None:
                    self.bus.emit(
                        "error",
                        "key commands need a typer backend "
                        "(clipboard-only mode)",
                    )
                else:
                    self.bus.emit("error", f"keys not supported: {result.keys}")
            elif result.handled and result.message:
                self._type_text(result.message)
                self.bus.emit("command", result.message)
            else:
                self.bus.emit("error", f"unhandled command: {text!r}")
            return
        cleaned = clean(text, self.settings)
        if not cleaned:
            return
        try:
            self._history.append(cleaned)
        except OSError as exc:
            # History loss must not kill the utterance: the pump has no
            # guard, so report loudly and keep typing.
            log.warning("history append failed: %s", exc)
            self.bus.emit("error", "Could not save to history — disk full?")
        if self._focus_moved():
            # Destination changed mid-utterance: hold for review instead of
            # typing into the wrong window. The Dictate page shows the text
            # with an explicit Insert action.
            self._record_window = None
            self.bus.emit("transcript", cleaned)
            self.bus.emit(
                "insert", ("held", "Focus changed — review, then Insert")
            )
            return
        self._record_window = None
        self._type_text(cleaned)
        self.bus.emit("transcript", cleaned)

    def _focus_moved(self) -> bool:
        """True only when both focus endpoints are known and differ."""
        if self._record_window is None:
            return False
        now = _active_window()
        return now is not None and now != self._record_window

    def insert_text(self, text: str) -> None:
        """Type user-reviewed text now (Dictate Insert button).

        Explicit user action: no focus guard, no history append (already
        recorded when transcribed).
        """
        cleaned = (text or "").strip()
        if self.state != SessionState.IDLE or not cleaned:
            return
        self._type_text(cleaned)

    def _type_text(self, text: str) -> None:
        typers = self._typers or (
            [self._typer] if self._typer is not None else []
        )
        for typer in typers:
            try:
                if typer.type_text(text):
                    self.bus.emit(
                        "insert", ("typed", type(typer).__name__)
                    )
                    return
            except Exception as exc:  # noqa: BLE001 - try next backend
                log.warning("typer %s failed: %s", type(typer).__name__, exc)
        # No text field (or every typer failed): save to clipboard like
        # Wispr Flow does, and notify loudly so nothing is silently lost.
        if qt_copy_to_clipboard(text):
            self.bus.emit("error", "No text field — copied to clipboard")
            self.bus.emit("notify", ("flow-linux", "Dictation copied"))
            self.bus.emit("insert", ("copied", "no text field"))
        else:
            self.bus.emit("error", "typing failed and clipboard unavailable")
            self.bus.emit("insert", ("failed", "typing and clipboard failed"))

    def _paste_last(self) -> None:
        text = self._history.last()
        if text:
            self._type_text(text)

    def _copy_last(self) -> None:
        text = self._history.last()
        if not text:
            return
        if not qt_copy_to_clipboard(text):
            self.bus.emit("error", "copy failed: clipboard unavailable")

    def _cancel(self) -> None:
        self._record_window = None
        if self.state == SessionState.RECORDING and self._capture is not None:
            # Mark first: the scratchpad loop checks this after its
            # finalization, so a recorded-then-cancelled session reports
            # a plain cancel instead of transcribing anyway. Every
            # session start resets the flag, so it never leaks.
            self._cancelled = True
            try:
                self._capture.stop()
            except Exception:  # noqa: BLE001 - best effort
                pass
            self._capture = None
            self._record_owner = None
            self._set_state(SessionState.IDLE)
        elif self.state == SessionState.PROCESSING:
            self._cancelled = True


def run_smoke(fixture: str, expect: str, engine_name: str) -> int:
    """Headless offline check used by scripts/e2e_offline.sh."""
    sys.path.insert(0, repo_root())
    from bench.bench import load_fixture_wav

    cls = ENGINES.get(engine_name)
    if cls is None:
        print(f"SMOKE_FAIL unknown engine {engine_name!r}")
        return 1
    engine = cls()
    try:
        engine.load(resolve_models_dir("models"), threads=8)
    except RuntimeError as exc:
        print(f"SMOKE_FAIL {exc}")
        return 1
    try:
        samples = load_fixture_wav(fixture)
        text = engine.transcribe(samples).text or ""
    except Exception as exc:  # noqa: BLE001 - smoke must report, not trace
        print(f"SMOKE_FAIL {exc}")
        return 1
    if expect.lower() in text.lower():
        print(f"SMOKE_PASS engine={engine_name} text={text!r}")
        return 0
    print(f"SMOKE_FAIL expected {expect!r} in {text!r}")
    return 1


def _active_window() -> int | None:
    """Best-effort focused window id for the insert review guard.

    X11 only; None everywhere else (guard skipped, today's behavior).
    Never raises.
    """
    if sys.platform == "win32":
        return None
    try:
        from flow.hotkey_x11 import active_window_id
    except ImportError:
        return None
    try:
        return active_window_id()
    except Exception:  # noqa: BLE001 - advisory only
        return None


def qt_copy_to_clipboard(text: str) -> bool:
    """Copy via the Qt clipboard (service context). False when unavailable."""
    try:
        from PySide6.QtGui import QGuiApplication
    except ImportError:
        return False
    if QGuiApplication.instance() is None:
        return False
    try:
        QGuiApplication.clipboard().setText(text)
    except Exception:
        return False
    return True


def take_instance_lock(path: str | None = None):
    """Non-blocking single-instance lock. Returns open file or None if held.

    fcntl locks release on process death, so a stale lock is impossible.
    """
    import fcntl

    path = path or os.path.expanduser("~/.cache/flow-linux/flowd.lock")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fh = open(path, "w")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


SHORTCUT_FIELDS = (
    "ptt_shortcut",
    "handsfree_shortcut",
    "command_shortcut",
    "paste_last_shortcut",
    "copy_last_shortcut",
    "cancel_key",
)


def apply_settings_flow(
    service: FlowService,
    new: Settings,
    *,
    backend_box: list,
    main,
    pill,
    settings_path: str | None,
) -> None:
    """Validate, persist, then activate settings; roll back on failure.

    Engine switches and shortcut re-grabs are refused while dictating.
    Persistence happens before activation, so a save failure leaves the
    running configuration untouched. If activation fails partway, the
    old working configuration (plus an already-switched engine) is
    restored on disk and in memory, and the UI is refreshed to it.
    """
    from PySide6.QtWidgets import QApplication as _QApp

    old = service.settings
    engine_changed = new.engine != old.engine
    shortcuts_changed = any(
        getattr(new, f) != getattr(old, f) for f in SHORTCUT_FIELDS
    )
    if (engine_changed or shortcuts_changed) and service.busy():
        raise RuntimeError("finish dictating before applying settings")
    try:
        save_settings(new, settings_path)
    except OSError as exc:
        raise RuntimeError(f"settings save failed: {exc}") from exc
    if engine_changed:
        pill.show_message(f"Switching to {new.engine}…")
        _QApp.processEvents()
    service.settings = new  # tentative; committed below
    engine_reloaded = False
    shortcuts_attempted = False
    try:
        if engine_changed:
            service.reload_engine()  # raises if busy/fails; old intact
            engine_reloaded = True
        if shortcuts_changed and backend_box:
            backend = backend_box[0]
            shortcuts_attempted = True
            backend.stop()
            backend.start(new, service.dispatch)
    except Exception as exc:
        if engine_reloaded:
            # Engine switch worked; only shortcuts failed. Keep the new
            # engine and restore the old shortcuts (copy without imports).
            restored = Settings(
                **{
                    f: getattr(old, f)
                    for f in Settings.__dataclass_fields__
                }
            )
            restored.engine = new.engine
        else:
            restored = old
        service.settings = restored
        try:
            save_settings(restored, settings_path)
        except OSError:
            pass
        if shortcuts_attempted and backend_box:
            backend = backend_box[0]
            try:
                backend.stop()
            except Exception:
                pass
            try:
                backend.start(old, service.dispatch)
            except Exception as start_exc:
                log.error("hotkey restore failed: %s", start_exc)
        main.refresh_settings(restored)
        pill.show_message(f"Settings failed, restored previous: {exc}")
        raise RuntimeError(f"settings apply failed: {exc}") from exc
    if engine_changed:
        pill.show_message(f"Engine: {new.engine}")
    if shortcuts_changed:
        if backend_box:
            pill.show_message("Shortcuts updated")
        else:
            pill.show_message("Shortcuts saved (hotkeys unavailable)")


def run_service() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print("flowd: PySide6 is required; use the project venv", file=sys.stderr)
        return 2
    from flow.ui.pill import QtPill
    from flow.ui.theme import apply_theme
    from flow.ui.tray import TrayIcon

    if sys.platform == "win32":
        from flow.platform.windows import app_dirs as _win_app_dirs
        from flow.platform.windows import (
            take_instance_lock as take_instance_lock_win,
        )

        _windirs = _win_app_dirs()
        _lockfh = take_instance_lock_win(_windirs["lock_path"])
    else:
        _windirs = None
        _lockfh = take_instance_lock()
    if _lockfh is None:
        print("flowd: another instance is running", file=sys.stderr)
        return 0
    settings = load_settings(
        _windirs["settings_path"] if _windirs else None
    )
    service = FlowService(
        settings,
        history_path=_windirs["history_path"] if _windirs else None,
    )
    try:
        service.setup()
    except RuntimeError as exc:
        print(f"flowd: {exc}", file=sys.stderr)
        return 2

    app = QApplication(sys.argv)
    app.setApplicationName("flow-linux")
    apply_theme(app)
    app.setQuitOnLastWindowClosed(False)  # tray app: survive window closes
    pill = QtPill()
    pill.set_state(SessionState.IDLE)  # starts hidden; idle means no bubble
    service.bus.on("state", pill.set_state)
    service.bus.on("error", pill.show_message)
    service.bus.on("level", pill.set_level)

    if sys.platform == "win32":
        import functools

        from flow.platform import windows as winplat

        autostart_enabled = winplat.autostart_is_enabled
        set_autostart = functools.partial(
            winplat.autostart_set_enabled,
            python_exe=sys.executable,
            app_dir=repo_root(),
        )
    else:
        from flow.autostart import is_enabled as autostart_enabled
        from flow.autostart import set_enabled as set_autostart
    from flow.dictionary import DictionaryStore
    from flow.history import TranscriptStore
    from flow.notes import NoteStore
    from flow.ui.main_window import FlowMainWindow

    models_dir = resolve_models_dir(service.settings.models_dir)
    dict_store = DictionaryStore(os.path.join(models_dir, "hotwords.txt"))
    note_store = NoteStore(
        path=_windirs["notes_path"] if _windirs else None
    )

    class _LiveHistoryStore:
        """Fresh disk read per call: the service appends from its own store."""

        def __init__(self, path: str | None = None) -> None:
            self._path = path

        def all(self):  # noqa: ANN001, ANN201 - duck-typed store
            return TranscriptStore(path=self._path).all()

        def search(self, query):  # noqa: ANN001, ANN201 - duck-typed store
            return TranscriptStore(path=self._path).search(query)

    history_store = _LiveHistoryStore(
        _windirs["history_path"] if _windirs else None
    )
    backend_box: list = []

    def apply_settings(new: Settings) -> None:
        apply_settings_flow(
            service,
            new,
            backend_box=backend_box,
            main=main,
            pill=pill,
            settings_path=_windirs["settings_path"] if _windirs else None,
        )

    def apply_dictionary(store) -> None:  # noqa: ANN001 - duck-typed store
        pill.show_message("Reloading engine…")
        service.reload_engine()

    main = FlowMainWindow(
        settings=service.settings,
        history_store=history_store,
        note_store=note_store,
        dict_store=dict_store,
        on_save_settings=apply_settings,
        on_save_dictionary=apply_dictionary,
        on_dictate=service.scratchpad_dictate,
        on_dictate_error=lambda: service.last_dictate_error,
        on_dictate_start=lambda: service.dispatch(Action.HANDSFREE_TOGGLE),
        on_dictate_stop=lambda: service.dispatch(Action.HANDSFREE_TOGGLE),
        on_dictate_cancel=lambda: service.dispatch(Action.CANCEL),
        on_insert_text=service.insert_text,
        on_refresh_history=lambda: [
            str(e.get("text") or "") for e in history_store.all()[:20]
        ],
        copy_fn=qt_copy_to_clipboard,
        initial_autostart=bool(autostart_enabled()),
        on_autostart_toggle=set_autostart,
    )
    service.bus.on("state", main.set_state)
    service.bus.on("level", main.set_level)
    service.bus.on("transcript", main.on_transcript)
    service.bus.on("insert", main.on_insert)
    app.aboutToQuit.connect(main.flush_drafts)  # tray quit saves drafts

    def _sync_cancel_grab(state) -> None:  # noqa: ANN001 - SessionState
        # Arm the any-modifier cancel grab only while dictating so a bare
        # Escape keeps working in other apps while flowd is idle.
        armed = state != SessionState.IDLE
        for candidate in backend_box:
            arm = getattr(candidate, "set_cancel_armed", None)
            if arm is not None:
                try:
                    arm(armed)
                except Exception:  # noqa: BLE001 - never break the bus
                    log.exception("cancel-grab sync failed")

    service.bus.on("state", _sync_cancel_grab)

    tray = TrayIcon(
        on_settings=lambda: main.show_page("settings"),
        on_quit=app.quit,
        actions=(
            ("Open flow", lambda: main.show_page("dictate")),
            ("History", lambda: main.show_page("history")),
            ("Notes", lambda: main.show_page("notes")),
            ("Dictionary", lambda: main.show_page("dictionary")),
        ),
    )
    service.bus.on("notify", lambda pair: tray.notify(pair[0], pair[1]))

    if sys.platform == "win32":
        backend_name = "windows"
    else:
        session_type = os.environ.get("XDG_SESSION_TYPE", "x11")
        backend_name = select_hotkey_name(session_type)
    backend = None
    backend_cls = HOTKEY_BACKENDS.get(backend_name)
    if backend_cls is None:
        print(f"flowd: no hotkey backend {backend_name!r}", file=sys.stderr)
    else:
        try:
            backend = backend_cls()
            backend.start(settings, service.dispatch)
        except RuntimeError as exc:
            print(f"flowd: hotkeys unavailable: {exc}", file=sys.stderr)
            backend = None
    if backend is None:
        # Stay alive: history/notes/dictionary/settings all work, and the
        # Dictate page offers click-to-dictate. (Wayland, failed grabs.)
        main.set_banner(
            "Global hotkeys unavailable — use the Dictate button below."
        )
        main.show_page("dictate")
        main.show()
    else:
        backend_box.append(backend)

    timer = QTimer()
    timer.timeout.connect(service.pump)
    timer.start(30)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    rc = app.exec()
    if backend is not None:
        backend.stop()
    return rc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="flowd", description=__doc__)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--fixture", default="")
    parser.add_argument("--expect", default="")
    parser.add_argument("--engine", default="parakeet")
    args = parser.parse_args(argv)
    if args.smoke:
        if not args.fixture or not args.expect:
            print("SMOKE_FAIL --fixture and --expect are required")
            return 1
        return run_smoke(args.fixture, args.expect, args.engine)
    return run_service()


if __name__ == "__main__":
    raise SystemExit(main())
