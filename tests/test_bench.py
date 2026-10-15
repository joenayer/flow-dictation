"""Benchmark plumbing tests with synthetic sine WAVs (no STT models)."""

from __future__ import annotations

import time
import wave
from pathlib import Path

import numpy as np
import pytest

from flow.stt_base import ENGINES, STTEngine, Transcription

from bench.bench import (
    TRANSCRIBE_GATE_MS,
    TYPE_RESERVE_MS,
    fixture_paths,
    load_fixture_wav,
    main,
    measure_release_to_typed,
)

SAMPLE_RATE = 16000


def _write_sine_wav(path: Path, *, seconds: float = 0.2, nchannels: int = 1, rate: int = SAMPLE_RATE) -> None:
    n = int(seconds * rate)
    t = np.arange(n, dtype=np.float64) / rate
    mono = (0.2 * np.sin(2 * np.pi * 440.0 * t) * 32767.0).astype(np.int16)
    if nchannels == 1:
        pcm = mono
    else:
        pcm = np.column_stack([mono, np.zeros_like(mono)]).reshape(-1)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(nchannels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(pcm.tobytes())


class _FakeFast(STTEngine):
    name = "fake_fast"

    def load(self, models_dir: str, threads: int = 8) -> None:
        return None

    def transcribe(self, samples: np.ndarray) -> Transcription:
        n = int(np.asarray(samples).reshape(-1).size)
        return Transcription(text="ok", duration_s=n / 16000.0, engine=self.name)

    def unload(self) -> None:
        return None


class _FakeSlow(STTEngine):
    name = "fake_slow"

    def load(self, models_dir: str, threads: int = 8) -> None:
        return None

    def transcribe(self, samples: np.ndarray) -> Transcription:
        time.sleep(0.05)
        n = int(np.asarray(samples).reshape(-1).size)
        return Transcription(text="slow", duration_s=n / 16000.0, engine=self.name)

    def unload(self) -> None:
        return None


def test_load_fixture_wav_mono_sine(tmp_path):
    path = tmp_path / "sine.wav"
    _write_sine_wav(path, seconds=0.25)
    samples = load_fixture_wav(str(path))
    assert samples.dtype == np.int16
    assert samples.ndim == 1
    assert samples.size == int(0.25 * SAMPLE_RATE)
    assert int(np.max(np.abs(samples))) > 100


def test_load_fixture_wav_stereo_downmix(tmp_path):
    path = tmp_path / "stereo.wav"
    _write_sine_wav(path, seconds=0.1, nchannels=2)
    samples = load_fixture_wav(str(path))
    assert samples.ndim == 1
    assert samples.size == int(0.1 * SAMPLE_RATE)
    assert int(np.max(np.abs(samples))) > 100


def test_load_fixture_wav_resamples_to_16k(tmp_path):
    path = tmp_path / "8k.wav"
    _write_sine_wav(path, seconds=0.2, rate=8000)
    samples = load_fixture_wav(str(path))
    assert samples.size == pytest.approx(0.2 * SAMPLE_RATE, rel=0.02)


def test_measure_release_to_typed_fake_engine():
    ENGINES["fake_fast"] = _FakeFast
    try:
        samples = np.zeros(1600, dtype=np.int16)
        row = measure_release_to_typed("fake_fast", samples)
        assert "transcribe_ms" in row
        assert row["transcribe_ms"] >= 0
        assert row["type_reserve_ms"] == TYPE_RESERVE_MS
        assert row["total_ms"] == pytest.approx(row["transcribe_ms"] + TYPE_RESERVE_MS)
        assert row["engine"] == "fake_fast"
        assert row["text"] == "ok"
        assert row["duration_s"] == pytest.approx(0.1)
    finally:
        ENGINES.pop("fake_fast", None)


def test_list_fixtures(tmp_path):
    _write_sine_wav(tmp_path / "a.wav")
    _write_sine_wav(tmp_path / "b.wav")
    paths = fixture_paths(tmp_path)
    assert [p.name for p in paths] == ["a.wav", "b.wav"]
    rc = main(["--list", "--fixtures", str(tmp_path)])
    assert rc == 0


def test_gate_pass_fast_fake(tmp_path):
    ENGINES["fake_fast"] = _FakeFast
    try:
        _write_sine_wav(tmp_path / "a.wav")
        rc = main(["--gate", "--engine", "fake_fast", "--fixtures", str(tmp_path)])
        assert rc == 0
    finally:
        ENGINES.pop("fake_fast", None)


def test_gate_fail_slow_fake(tmp_path, monkeypatch):
    import bench.bench as bench_mod

    monkeypatch.setattr(bench_mod, "TRANSCRIBE_GATE_MS", 1.0)
    ENGINES["fake_slow"] = _FakeSlow
    try:
        _write_sine_wav(tmp_path / "a.wav")
        rc = main(["--gate", "--engine", "fake_slow", "--fixtures", str(tmp_path)])
        assert rc == 1
    finally:
        ENGINES.pop("fake_slow", None)


def test_gate_constant_documents_typing_reserve():
    assert TRANSCRIBE_GATE_MS == 700.0
    assert TYPE_RESERVE_MS == 100.0
    assert TRANSCRIBE_GATE_MS + TYPE_RESERVE_MS == 800.0
