"""VADGate energy-fallback tests (no Silero model required)."""

from __future__ import annotations

import numpy as np

from flow.vad import VADGate

SAMPLE_RATE = 16000


def _sine(n: int, amp: float = 0.4, freq: float = 440.0) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / SAMPLE_RATE
    return (amp * np.sin(2 * np.pi * freq * t) * 32767.0).astype(np.int16)


def test_energy_backend_when_model_missing(tmp_path):
    gate = VADGate(str(tmp_path))
    assert gate.backend == "energy"


def test_energy_silence_is_not_speech(tmp_path):
    gate = VADGate(str(tmp_path), hangover_ms=200.0)
    chunk = np.zeros(1600, dtype=np.int16)
    assert gate.feed(chunk) is False
    assert gate.is_speech() is False
    assert gate.should_auto_stop() is False


def test_energy_loud_sine_is_speech(tmp_path):
    gate = VADGate(str(tmp_path), energy_threshold=500.0, hangover_ms=200.0)
    assert gate.feed(_sine(1600)) is True
    assert gate.is_speech() is True
    assert gate.should_auto_stop() is False


def test_energy_hangover_auto_stop(tmp_path):
    gate = VADGate(str(tmp_path), energy_threshold=500.0, hangover_ms=200.0)
    gate.feed(_sine(1600))  # 100 ms speech
    silence = np.zeros(1600, dtype=np.int16)  # 100 ms
    gate.feed(silence)
    assert gate.should_auto_stop() is False
    gate.feed(silence)
    assert gate.should_auto_stop() is True


def test_reset_clears_state(tmp_path):
    gate = VADGate(str(tmp_path), hangover_ms=50.0)
    gate.feed(_sine(1600))
    gate.feed(np.zeros(1600, dtype=np.int16))
    gate.reset()
    assert gate.is_speech() is False
    assert gate.should_auto_stop() is False
    gate.feed(np.zeros(1600, dtype=np.int16))
    assert gate.should_auto_stop() is False


def test_api_documented():
    doc = VADGate.__doc__ or ""
    assert "feed" in doc
    assert "should_auto_stop" in doc
    assert "energy" in doc.lower()
