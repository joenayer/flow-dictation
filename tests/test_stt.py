"""STT engine contract tests. Real models are skipif; fake engine always runs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from flow.stt_base import ENGINES, STTEngine, Transcription

ROOT = Path(__file__).resolve().parents[1]


class FakeEngine(STTEngine):
    name = "fake"

    def __init__(self) -> None:
        self.loaded = False

    def load(self, models_dir: str, threads: int = 8) -> None:
        self.loaded = True
        self.models_dir = models_dir
        self.threads = threads

    def transcribe(self, samples: np.ndarray) -> Transcription:
        n = int(np.asarray(samples).reshape(-1).size)
        return Transcription(text="hello world", duration_s=n / 16000.0, engine=self.name)

    def unload(self) -> None:
        self.loaded = False


def _parakeet_ready() -> bool:
    d = ROOT / "models" / "parakeet-v2-int8"
    names = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
    return all((d / n).is_file() for n in names)


def _moonshine_ready() -> bool:
    d = ROOT / "models" / "moonshine-base-en-int8"
    names = (
        "preprocess.onnx",
        "encode.int8.onnx",
        "uncached_decode.int8.onnx",
        "cached_decode.int8.onnx",
        "tokens.txt",
    )
    return all((d / n).is_file() for n in names)


def test_engines_register_on_import():
    import flow.stt_moonshine  # noqa: F401
    import flow.stt_parakeet  # noqa: F401

    assert "parakeet" in ENGINES
    assert "moonshine" in ENGINES
    assert ENGINES["parakeet"].name == "parakeet"
    assert ENGINES["moonshine"].name == "moonshine"


def test_fake_engine_contract_shape():
    eng = FakeEngine()
    eng.load("/tmp", threads=4)
    assert eng.loaded is True
    samples = np.zeros(3200, dtype=np.int16)
    out = eng.transcribe(samples)
    assert isinstance(out, Transcription)
    assert out.text == "hello world"
    assert out.engine == "fake"
    assert out.duration_s == pytest.approx(0.2)
    eng.unload()
    assert eng.loaded is False


def test_parakeet_missing_files_error(tmp_path):
    from flow.stt_parakeet import ParakeetEngine

    eng = ParakeetEngine()
    with pytest.raises(RuntimeError, match="missing|fetch_models"):
        eng.load(str(tmp_path))


def test_moonshine_missing_files_error(tmp_path):
    from flow.stt_moonshine import MoonshineEngine

    eng = MoonshineEngine()
    with pytest.raises(RuntimeError, match="missing|fetch_models"):
        eng.load(str(tmp_path))


@pytest.mark.skipif(not _parakeet_ready(), reason="parakeet model files missing")
def test_parakeet_load_transcribe_silence():
    from flow.stt_parakeet import ParakeetEngine

    eng = ParakeetEngine()
    eng.load(str(ROOT / "models"))
    out = eng.transcribe(np.zeros(16000, dtype=np.int16))
    assert isinstance(out, Transcription)
    assert out.engine == "parakeet"
    assert out.duration_s == pytest.approx(1.0)
    assert isinstance(out.text, str)
    eng.unload()


@pytest.mark.skipif(not _moonshine_ready(), reason="moonshine model files missing")
def test_moonshine_load_transcribe_silence():
    from flow.stt_moonshine import MoonshineEngine

    eng = MoonshineEngine()
    eng.load(str(ROOT / "models"))
    out = eng.transcribe(np.zeros(16000, dtype=np.int16))
    assert isinstance(out, Transcription)
    assert out.engine == "moonshine"
    assert out.duration_s == pytest.approx(1.0)
    assert isinstance(out.text, str)
    eng.unload()
