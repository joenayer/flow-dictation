"""Audio capture factory tests (no real mic required except skipif)."""

from __future__ import annotations

import sys
import types

import numpy as np
import pytest

from flow.audio import PwRecordCapture, SounddeviceCapture, default_capture


def _have_portaudio_input() -> bool:
    try:
        import sounddevice as sd
    except Exception:
        return False
    try:
        devices = sd.query_devices()
    except Exception:
        return False
    for dev in devices:
        try:
            if int(dev.get("max_input_channels") or 0) > 0:
                return True
        except (TypeError, ValueError, AttributeError):
            continue
    return False


def test_factory_prefers_sounddevice(monkeypatch):
    fake = types.ModuleType("sounddevice")
    fake.query_devices = lambda: [{"name": "Mic", "max_input_channels": 1}]
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    cap = default_capture()
    assert isinstance(cap, SounddeviceCapture)


def test_factory_falls_back_to_pwrecord(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    cap = default_capture()
    assert isinstance(cap, PwRecordCapture)


def test_sounddevice_missing_raises_runtimeerror(monkeypatch):
    monkeypatch.setitem(sys.modules, "sounddevice", None)
    cap = SounddeviceCapture()
    with pytest.raises(RuntimeError, match="sounddevice|PortAudio"):
        cap.start(lambda _c: None)


def test_sounddevice_list_inputs_monkeypatched(monkeypatch):
    fake = types.ModuleType("sounddevice")
    fake.query_devices = lambda: [
        {"name": "Mic", "max_input_channels": 2},
        {"name": "Speaker", "max_input_channels": 0},
    ]
    monkeypatch.setitem(sys.modules, "sounddevice", fake)
    assert SounddeviceCapture().list_inputs() == ["Mic"]


def test_pwrecord_missing_binary(monkeypatch):
    import flow.audio as audio

    monkeypatch.setattr(audio.shutil, "which", lambda _name: None)
    cap = PwRecordCapture()
    with pytest.raises(RuntimeError, match="pw-record"):
        cap.start(lambda _c: None)


def test_pwrecord_list_inputs():
    assert PwRecordCapture().list_inputs() == ["default"]


@pytest.mark.skipif(not _have_portaudio_input(), reason="no PortAudio microphone")
def test_sounddevice_live_capture_short():
    cap = SounddeviceCapture()
    chunks: list[np.ndarray] = []
    cap.start(chunks.append)
    import time

    time.sleep(0.25)
    utt = cap.stop()
    assert utt.dtype == np.int16
    assert utt.ndim == 1
    assert utt.size > 0


class _PortAudioError(Exception):
    """Mirrors sounddevice.PortAudioError (inherits Exception, not RuntimeError)."""


def _fake_sounddevice(monkeypatch, stream_cls):
    fake = types.ModuleType("sounddevice")
    fake.PortAudioError = _PortAudioError
    fake.InputStream = stream_cls
    monkeypatch.setitem(sys.modules, "sounddevice", fake)


def test_sounddevice_open_failure_translated_to_runtimeerror(monkeypatch):
    def _raise(*args, **kwargs):
        raise _PortAudioError("No Default Input Device")

    _fake_sounddevice(monkeypatch, _raise)
    cap = SounddeviceCapture()
    with pytest.raises(RuntimeError, match="could not open microphone"):
        cap.start(lambda _c: None)
    assert cap._stream is None


def test_sounddevice_start_failure_closes_partial_stream(monkeypatch):
    closed = []

    class _Stream:
        def start(self):
            raise _PortAudioError("Invalid device")

        def close(self):
            closed.append(True)

    _fake_sounddevice(monkeypatch, lambda *a, **k: _Stream())
    cap = SounddeviceCapture()
    with pytest.raises(RuntimeError, match="could not start recording"):
        cap.start(lambda _c: None)
    assert closed == [True]
    assert cap._stream is None


def test_pwrecord_spawn_failure_translated_to_runtimeerror(monkeypatch):
    import flow.audio as audio_mod

    monkeypatch.setattr(audio_mod.shutil, "which", lambda _name: "/bin/pw-record")

    def _raise(*args, **kwargs):
        raise PermissionError("sandboxed")

    monkeypatch.setattr(audio_mod.subprocess, "Popen", _raise)
    with pytest.raises(RuntimeError, match="could not start pw-record"):
        PwRecordCapture().start(lambda _c: None)
