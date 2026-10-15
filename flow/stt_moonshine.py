"""Moonshine base-en STT via sherpa-onnx (CPU int8)."""

from __future__ import annotations

import os

import numpy as np

from flow.dictionary import recognizer_hotwords_kwargs
from flow.stt_base import ENGINES, STTEngine, Transcription

SAMPLE_RATE = 16000
_SUBDIR = "moonshine-base-en-int8"
_FILES = (
    "preprocess.onnx",
    "encode.int8.onnx",
    "uncached_decode.int8.onnx",
    "cached_decode.int8.onnx",
    "tokens.txt",
)


def _as_float32_mono(samples: np.ndarray) -> np.ndarray:
    arr = np.asarray(samples).reshape(-1)
    if arr.dtype == np.int16:
        return arr.astype(np.float32) / 32768.0
    return arr.astype(np.float32)


def _require_files(root: str) -> dict[str, str]:
    paths = {name: os.path.join(root, name) for name in _FILES}
    missing = [p for p in paths.values() if not os.path.isfile(p)]
    if missing:
        raise RuntimeError(
            "Moonshine base-en int8 model files missing. Run scripts/fetch_models.sh.\n"
            f"Expected under {root}/: {', '.join(_FILES)}\n"
            f"Missing: {missing}"
        )
    return paths


class MoonshineEngine(STTEngine):
    """sherpa-onnx OfflineRecognizer.from_moonshine, CPU provider."""

    name = "moonshine"

    def __init__(self) -> None:
        self._recognizer = None

    def load(self, models_dir: str, threads: int = 8) -> None:
        if self._recognizer is not None:
            return
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise RuntimeError(
                "sherpa-onnx is not installed; use the project venv."
            ) from exc
        root = os.path.join(models_dir, _SUBDIR)
        paths = _require_files(root)
        # from_moonshine (sherpa-onnx 1.13.8) has no hotwords_file param;
        # recognizer_hotwords_kwargs is a no-op unless a later sherpa adds it.
        factory = sherpa_onnx.OfflineRecognizer.from_moonshine
        hw = recognizer_hotwords_kwargs(models_dir, factory)
        kwargs = dict(
            preprocessor=paths["preprocess.onnx"],
            encoder=paths["encode.int8.onnx"],
            uncached_decoder=paths["uncached_decode.int8.onnx"],
            cached_decoder=paths["cached_decode.int8.onnx"],
            tokens=paths["tokens.txt"],
            num_threads=threads,
            decoding_method="greedy_search",
            provider="cpu",
        )
        kwargs.update(hw)
        try:
            self._recognizer = factory(**kwargs)
        except Exception as exc:
            if hw.get("hotwords_file"):
                raise RuntimeError(
                    "hotwords file is malformed or not usable: "
                    f"{hw['hotwords_file']}: {exc}"
                ) from exc
            raise
        silence = np.zeros(SAMPLE_RATE, dtype=np.int16)
        self.transcribe(silence)

    def transcribe(self, samples: np.ndarray) -> Transcription:
        if self._recognizer is None:
            raise RuntimeError("MoonshineEngine.load() was not called")
        audio = _as_float32_mono(samples)
        stream = self._recognizer.create_stream()
        stream.accept_waveform(SAMPLE_RATE, audio)
        self._recognizer.decode_stream(stream)
        text = ""
        result = getattr(stream, "result", None)
        if result is not None:
            text = (getattr(result, "text", None) or "").strip()
        duration_s = float(np.asarray(samples).reshape(-1).size) / SAMPLE_RATE
        return Transcription(text=text, duration_s=duration_s, engine=self.name)

    def unload(self) -> None:
        self._recognizer = None


ENGINES["moonshine"] = MoonshineEngine
