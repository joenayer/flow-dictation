"""FlowService unit tests with fakes: engine swap, typer fallthrough, copy."""

import pytest

from flow.config import Settings
from flow.events import SessionState
from flow.flowd import FlowService


class FakeEngine:
    """STT engine double; fail_load makes load() raise."""

    instances: list = []
    fail_load = False

    def __init__(self) -> None:
        self.loaded = False
        self.unloaded = False
        FakeEngine.instances.append(self)

    def load(self, models_dir, threads=1) -> None:
        if FakeEngine.fail_load:
            raise RuntimeError("boom")
        self.loaded = True

    def unload(self) -> None:
        self.unloaded = True


class FakeTyper:
    def __init__(self, ok: bool) -> None:
        self.ok = ok
        self.calls: list = []

    def type_text(self, text: str) -> bool:
        self.calls.append(text)
        return self.ok


@pytest.fixture
def service(tmp_path):
    FakeEngine.instances.clear()
    FakeEngine.fail_load = False
    return FlowService(
        Settings(), history_path=str(tmp_path / "history.jsonl")
    )


def test_reload_refuses_while_recording(service) -> None:
    service._set_state(SessionState.RECORDING)
    with pytest.raises(RuntimeError, match="while dictating"):
        service.reload_engine()


def test_reload_refuses_while_processing(service) -> None:
    service._set_state(SessionState.PROCESSING)
    with pytest.raises(RuntimeError, match="while dictating"):
        service.reload_engine()


def test_reload_keeps_old_engine_when_load_fails(service, monkeypatch) -> None:
    from flow.flowd import ENGINES

    monkeypatch.setitem(ENGINES, "fake", FakeEngine)
    old = FakeEngine()
    service._engine = old
    service.settings.engine = "fake"
    FakeEngine.fail_load = True
    with pytest.raises(RuntimeError, match="boom"):
        service.reload_engine()
    assert service._engine is old
    assert old.unloaded is False


def test_reload_swaps_on_success(service, monkeypatch) -> None:
    from flow.flowd import ENGINES

    monkeypatch.setitem(ENGINES, "fake", FakeEngine)
    old = FakeEngine()
    service._engine = old
    service.settings.engine = "fake"
    service.reload_engine()
    assert service._engine is not old
    assert service._engine.loaded is True
    assert old.unloaded is True


def test_type_text_falls_through_to_next_typer(service, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(
        "flow.flowd.qt_copy_to_clipboard", lambda text: calls.append(text)
    )
    first, second = FakeTyper(False), FakeTyper(True)
    service._typer = first
    service._typers = [first, second]
    service._type_text("café")
    assert first.calls == ["café"]
    assert second.calls == ["café"]
    assert calls == []


def test_type_text_clipboard_when_all_typers_fail(service, monkeypatch) -> None:
    calls: list = []

    def fake_copy(text: str) -> bool:
        calls.append(text)
        return True

    monkeypatch.setattr("flow.flowd.qt_copy_to_clipboard", fake_copy)
    only = FakeTyper(False)
    service._typer = only
    service._typers = [only]
    service._type_text("hi")
    assert calls == ["hi"]


def test_copy_last_uses_qt_clipboard(service, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(
        "flow.flowd.qt_copy_to_clipboard", lambda text: calls.append(text)
    )
    service._history.append("hello flow")
    service._copy_last()
    assert calls == ["hello flow"]


def test_copy_last_empty_history_does_nothing(service, monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(
        "flow.flowd.qt_copy_to_clipboard", lambda text: calls.append(text)
    )
    service._copy_last()
    assert calls == []


def test_type_text_emits_typed_insert_event(service) -> None:
    seen: list = []
    service.bus.on("insert", seen.append)
    typer = FakeTyper(True)
    service._typer = typer
    service._typers = [typer]
    service._type_text("hi")
    assert seen == [("typed", "FakeTyper")]


def test_type_text_emits_copied_insert_event(service, monkeypatch) -> None:
    seen: list = []
    service.bus.on("insert", seen.append)
    monkeypatch.setattr("flow.flowd.qt_copy_to_clipboard", lambda text: True)
    only = FakeTyper(False)
    service._typer = only
    service._typers = [only]
    service._type_text("hi")
    assert seen == [("copied", "no text field")]


def test_type_text_emits_failed_insert_event(service, monkeypatch) -> None:
    seen: list = []
    service.bus.on("insert", seen.append)
    monkeypatch.setattr("flow.flowd.qt_copy_to_clipboard", lambda text: False)
    only = FakeTyper(False)
    service._typer = only
    service._typers = [only]
    service._type_text("hi")
    assert seen == [("failed", "typing and clipboard failed")]


def test_transcript_held_for_review_when_focus_moved(
    service, monkeypatch
) -> None:
    seen: list = []
    service.bus.on("insert", seen.append)
    typer = FakeTyper(True)
    service._typer = typer
    service._typers = [typer]
    service._record_window = 111
    monkeypatch.setattr("flow.flowd._active_window", lambda: 222)
    service._handle_transcript("hello review", "dictation")
    assert typer.calls == []  # not typed into the wrong window
    assert seen and seen[0][0] == "held"
    assert service._record_window is None


def test_transcript_types_when_focus_unchanged(service, monkeypatch) -> None:
    seen: list = []
    service.bus.on("insert", seen.append)
    typer = FakeTyper(True)
    service._typer = typer
    service._typers = [typer]
    service._record_window = 111
    monkeypatch.setattr("flow.flowd._active_window", lambda: 111)
    service._handle_transcript("hello there", "dictation")
    assert typer.calls == ["Hello there."]
    assert seen == [("typed", "FakeTyper")]


def test_transcript_types_when_focus_unknown(service, monkeypatch) -> None:
    typer = FakeTyper(True)
    service._typer = typer
    service._typers = [typer]
    service._record_window = 111
    monkeypatch.setattr("flow.flowd._active_window", lambda: None)
    service._handle_transcript("hello there", "dictation")
    assert typer.calls == ["Hello there."]


def test_insert_text_types_without_focus_guard(service, monkeypatch) -> None:
    seen: list = []
    service.bus.on("insert", seen.append)
    typer = FakeTyper(True)
    service._typer = typer
    service._typers = [typer]
    service._record_window = 111
    monkeypatch.setattr("flow.flowd._active_window", lambda: 999)
    service.insert_text("  reviewed words ")
    assert typer.calls == ["reviewed words"]
    assert seen == [("typed", "FakeTyper")]


def test_insert_text_ignored_while_busy_or_blank(service) -> None:
    typer = FakeTyper(True)
    service._typer = typer
    service._typers = [typer]
    service._set_state(SessionState.RECORDING)
    service.insert_text("held")
    service._set_state(SessionState.IDLE)
    service.insert_text("   ")
    assert typer.calls == []


def test_clipboard_only_mode_without_typers(service, monkeypatch) -> None:
    seen: list = []
    service.bus.on("insert", seen.append)
    monkeypatch.setattr("flow.flowd.qt_copy_to_clipboard", lambda text: True)
    service._typer = None
    service._typers = []
    service._handle_transcript("hello there", "dictation")
    assert seen == [("copied", "no text field")]


def test_transcript_continues_when_history_unwritable(
    service, monkeypatch
) -> None:
    errors: list = []
    service.bus.on("error", errors.append)
    typer = FakeTyper(True)
    service._typer = typer
    service._typers = [typer]

    def boom(text: str):
        raise OSError("disk full")

    monkeypatch.setattr(service._history, "append", boom)
    service._handle_transcript("hello there", "dictation")
    assert typer.calls == ["Hello there."]  # utterance survived
    assert errors and "history" in errors[0].lower()


def test_scratchpad_dictate_reports_capture_failure(service, monkeypatch) -> None:
    import types

    service._engine = FakeEngine()
    service._vad = types.SimpleNamespace(reset=lambda: None)

    def boom():
        raise RuntimeError("Microphone unavailable")

    monkeypatch.setattr("flow.flowd.default_capture", boom)
    assert service.scratchpad_dictate(timeout_s=0.01) is None
    assert service.last_dictate_error is not None
    assert "Microphone" in service.last_dictate_error


class FakeCapture:
    """AudioCapture double with deterministic samples."""

    def __init__(self, samples: int = 8000) -> None:
        self.samples = samples
        self.starts = 0
        self.stops = 0

    def start(self, on_chunk) -> None:
        self.starts += 1

    def stop(self):
        import numpy as np

        self.stops += 1
        return np.zeros(self.samples, dtype=np.int16)


class FakeVAD:
    def reset(self) -> None:
        pass

    def feed(self, chunk) -> None:
        pass

    def should_auto_stop(self) -> bool:
        return False


class FakeSTT:
    def __init__(self, text: str = "Hello world") -> None:
        self.text = text
        self.calls = 0

    def transcribe(self, samples):
        from types import SimpleNamespace

        self.calls += 1
        return SimpleNamespace(text=self.text)


def _live(service, monkeypatch, **kwargs):
    """Wire fakes so dispatch/pump runs end to end."""
    import flow.flowd as flowd_mod

    capture = FakeCapture(**kwargs)
    monkeypatch.setattr(flowd_mod, "default_capture", lambda: capture)
    service._vad = FakeVAD()
    stt = FakeSTT()
    service._engine = stt
    typer = FakeTyper(True)
    service._typer = typer
    service._typers = [typer]
    return capture, stt, typer


def _pump_idle(service) -> None:
    """Drain the queue, joining a worker if one was launched."""
    service.pump()
    worker = service._worker
    if worker is not None:
        worker.join(timeout=5)
        service._worker = None
        service.pump()


def test_reload_aborts_when_session_starts_mid_load(
    service, monkeypatch
) -> None:
    from flow.flowd import ENGINES

    monkeypatch.setitem(ENGINES, "fake", FakeEngine)
    old = FakeEngine()
    service._engine = old
    service.settings.engine = "fake"

    real_load = FakeEngine.load

    def flipping_load(self, models_dir, threads=1) -> None:
        real_load(self, models_dir, threads)
        # A recording won the race during the slow load.
        service._set_state(SessionState.RECORDING)

    monkeypatch.setattr(FakeEngine, "load", flipping_load)
    with pytest.raises(RuntimeError, match="while dictating"):
        service.reload_engine()
    assert service._engine is old
    assert old.unloaded is False
    assert FakeEngine.instances[-1].unloaded is True


def test_transcribe_worker_uses_captured_engine(service) -> None:
    import numpy as np

    service._engine = None  # swapped/unloaded underneath: worker unaffected
    stt = FakeSTT()
    service._transcribe_worker(
        np.zeros(8000, dtype=np.int16), "dictation", stt
    )
    assert stt.calls == 1
    kind, payload = service._queue.get_nowait()
    assert (kind, payload) == ("transcript", ("Hello world", "dictation"))


def test_foreign_release_does_not_end_recording(
    service, monkeypatch
) -> None:
    from flow.hotkey_base import Action

    capture, _stt, _typer = _live(service, monkeypatch)
    service.dispatch(Action.PTT_DOWN)
    service.pump()
    assert service.state == SessionState.RECORDING
    service.dispatch(Action.COMMAND_DOWN)  # refused: busy
    service.pump()
    service.dispatch(Action.COMMAND_UP)  # foreign release: ignored
    service.pump()
    assert service.state == SessionState.RECORDING
    assert capture.stops == 0
    service.dispatch(Action.PTT_UP)  # owner release: finishes
    _pump_idle(service)
    assert service.state == SessionState.IDLE
    assert capture.stops == 1


def test_toggle_does_not_steal_ptt_session(service, monkeypatch) -> None:
    from flow.hotkey_base import Action

    capture, _stt, _typer = _live(service, monkeypatch)
    service.dispatch(Action.PTT_DOWN)
    service.pump()
    service.dispatch(Action.HANDSFREE_TOGGLE)
    service.pump()
    assert service.state == SessionState.RECORDING
    assert capture.stops == 0
    service.dispatch(Action.PTT_UP)
    _pump_idle(service)
    assert service.state == SessionState.IDLE


def test_toggle_stops_handsfree_session(service, monkeypatch) -> None:
    from flow.hotkey_base import Action

    _capture, stt, typer = _live(service, monkeypatch)
    service.dispatch(Action.HANDSFREE_TOGGLE)
    service.pump()
    assert service.state == SessionState.RECORDING
    service.dispatch(Action.HANDSFREE_TOGGLE)
    _pump_idle(service)
    assert service.state == SessionState.IDLE
    assert stt.calls == 1
    assert typer.calls == ["Hello world."]


def test_scratchpad_stop_routed_to_note_session(
    service, monkeypatch
) -> None:
    from flow.hotkey_base import Action

    _capture, _stt, _typer = _live(service, monkeypatch)
    service._scratchpad_active = True
    service._set_state(SessionState.RECORDING)
    service._capture = FakeCapture()
    service.dispatch(Action.HANDSFREE_TOGGLE)
    service.pump()
    assert service._scratchpad_stop is True
    assert service._worker is None  # no second global transcription
    service._scratchpad_active = False
    service._set_state(SessionState.IDLE)


def test_cancel_marks_session_without_leaking(service, monkeypatch) -> None:
    from flow.hotkey_base import Action

    _capture, stt, typer = _live(service, monkeypatch)
    service.dispatch(Action.PTT_DOWN)
    service.pump()
    service.dispatch(Action.CANCEL)
    service.pump()
    assert service.state == SessionState.IDLE
    assert service._cancelled is True
    # The next utterance starts clean: the stale flag is reset and the
    # transcript is delivered, not swallowed.
    service.dispatch(Action.PTT_DOWN)
    service.pump()
    assert service._cancelled is False
    service.dispatch(Action.PTT_UP)
    _pump_idle(service)
    assert stt.calls == 1
    assert typer.calls == ["Hello world."]


def _qcore():
    from PySide6.QtCore import QCoreApplication

    app = QCoreApplication.instance()
    if app is None:
        app = QCoreApplication(["flow-linux-service-test"])
    return app


def test_scratchpad_cancel_returns_plain_cancel(
    service, monkeypatch
) -> None:
    from PySide6.QtCore import QTimer

    _qcore()
    _capture, stt, _typer = _live(service, monkeypatch)
    QTimer.singleShot(0, service._cancel)
    assert service.scratchpad_dictate(timeout_s=5) is None
    assert service.last_dictate_error is None  # plain cancel, no error
    assert stt.calls == 0
    assert service.state == SessionState.IDLE


def test_scratchpad_stop_transcribes_once_to_note(
    service, monkeypatch
) -> None:
    from PySide6.QtCore import QTimer

    from flow.hotkey_base import Action

    _qcore()
    _capture, stt, typer = _live(service, monkeypatch)
    QTimer.singleShot(
        0, lambda: service._handle_action(Action.HANDSFREE_TOGGLE)
    )
    assert service.scratchpad_dictate(timeout_s=5) == "Hello world."
    assert stt.calls == 1
    assert typer.calls == []  # note destination only, no global typing
    assert service.state == SessionState.IDLE


class FakeBackend:
    def __init__(self, fail_start: bool = False) -> None:
        self.starts: list = []
        self.stops = 0
        self.fail_start = fail_start

    def start(self, settings, dispatch) -> None:
        if self.fail_start:
            raise RuntimeError("grab failed")
        self.starts.append(settings)

    def stop(self) -> None:
        self.stops += 1


class FakePill:
    def __init__(self) -> None:
        self.messages: list = []

    def show_message(self, text: str) -> None:
        self.messages.append(text)


class FakeMain:
    def __init__(self) -> None:
        self.refreshed: list = []

    def refresh_settings(self, settings) -> None:
        self.refreshed.append(settings)


def test_apply_settings_save_failure_touches_nothing(
    service, monkeypatch, tmp_path
) -> None:
    import flow.flowd as flowd_mod
    from flow.config import Settings

    old = service.settings
    path = str(tmp_path / "settings.json")
    flowd_mod.save_settings(old, path)
    backend = FakeBackend()
    main, pill = FakeMain(), FakePill()

    def _boom(settings, path=None):
        raise OSError("injected ENOSPC")

    monkeypatch.setattr(flowd_mod, "save_settings", _boom)
    new = Settings(ptt_shortcut="Alt+Q")
    with pytest.raises(RuntimeError, match="save failed"):
        flowd_mod.apply_settings_flow(
            service,
            new,
            backend_box=[backend],
            main=main,
            pill=pill,
            settings_path=path,
        )
    assert service.settings is old
    assert backend.starts == [] and backend.stops == 0
    assert flowd_mod.load_settings(path).ptt_shortcut == "Alt+W"


def test_apply_settings_activation_failure_rolls_back(
    service, tmp_path
) -> None:
    import flow.flowd as flowd_mod
    from flow.config import Settings

    old = service.settings
    path = str(tmp_path / "settings.json")
    backend = FakeBackend(fail_start=True)
    main, pill = FakeMain(), FakePill()
    with pytest.raises(RuntimeError, match="apply failed"):
        flowd_mod.apply_settings_flow(
            service,
            Settings(ptt_shortcut="Alt+Q"),
            backend_box=[backend],
            main=main,
            pill=pill,
            settings_path=path,
        )
    assert service.settings is old
    assert flowd_mod.load_settings(path).ptt_shortcut == "Alt+W"
    assert main.refreshed == [old]
