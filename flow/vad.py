"""Voice-activity gate for hands-free auto-stop."""

from __future__ import annotations

import os

import numpy as np

SAMPLE_RATE = 16000
_SILERO_NAME = "silero_vad.onnx"


class VADGate:
    """Speech/silence gate over int16 mono 16 kHz chunks (hands-free auto-stop).

    Backend
    -------
    If ``{models_dir}/silero_vad.onnx`` exists and ``sherpa_onnx`` loads it,
    uses sherpa-onnx Silero VAD (``backend == "sherpa"``). Otherwise uses an
    energy-threshold fallback on RMS of int16 samples (``backend == "energy"``).

    Parameters
    ----------
    models_dir:
        Directory that may contain ``silero_vad.onnx``.
    sample_rate:
        Must be 16000 (model + capture contract).
    energy_threshold:
        RMS (int16 units) above which the energy backend counts a chunk as
        speech. Ignored by the sherpa backend.
    hangover_ms:
        After speech has been observed, this much consecutive silence makes
        ``should_auto_stop()`` return True.

    Methods
    -------
    feed(chunk) -> bool
        Accept int16 mono samples; return whether speech is currently active.
    is_speech() -> bool
        Latest speech decision.
    should_auto_stop() -> bool
        True once speech has been seen and hangover silence has elapsed.
    reset() -> None
        Clear utterance state (call at the start of a new recording).
    """

    def __init__(
        self,
        models_dir: str = "models",
        sample_rate: int = SAMPLE_RATE,
        energy_threshold: float = 500.0,
        hangover_ms: float = 400.0,
    ) -> None:
        if sample_rate != SAMPLE_RATE:
            raise ValueError(f"VADGate requires {SAMPLE_RATE} Hz, got {sample_rate}")
        self.sample_rate = sample_rate
        self.energy_threshold = float(energy_threshold)
        self.hangover_ms = float(hangover_ms)
        self.backend = "energy"
        self._vad = None
        self._window = 512
        self._pending = np.zeros(0, dtype=np.float32)
        self._speech = False
        self._seen_speech = False
        self._silence_ms = 0.0

        model_path = os.path.join(models_dir, _SILERO_NAME)
        if os.path.isfile(model_path):
            self._try_sherpa(model_path)

    def _try_sherpa(self, model_path: str) -> None:
        try:
            import sherpa_onnx
        except ImportError:
            return
        try:
            config = sherpa_onnx.VadModelConfig()
            config.silero_vad.model = model_path
            config.silero_vad.threshold = 0.5
            config.silero_vad.min_silence_duration = max(0.1, self.hangover_ms / 1000.0)
            config.silero_vad.min_speech_duration = 0.1
            config.sample_rate = self.sample_rate
            vad = sherpa_onnx.VoiceActivityDetector(config, buffer_size_in_seconds=60)
            window = int(getattr(config.silero_vad, "window_size", 512) or 512)
        except Exception:
            return
        self._vad = vad
        self._window = max(window, 1)
        self.backend = "sherpa"

    def feed(self, chunk: np.ndarray) -> bool:
        """Accept int16 mono samples; return whether speech is currently active."""
        samples = np.asarray(chunk).reshape(-1)
        if samples.size == 0:
            return self._speech
        if samples.dtype != np.int16:
            samples = samples.astype(np.int16)

        if self._vad is not None:
            speech = self._feed_sherpa(samples)
        else:
            speech = self._feed_energy(samples)
        self._update_hangover(speech, samples.size)
        return self._speech

    def _feed_energy(self, samples: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        return rms >= self.energy_threshold

    def _feed_sherpa(self, samples: np.ndarray) -> bool:
        f32 = samples.astype(np.float32) / 32768.0
        self._pending = np.concatenate([self._pending, f32])
        speech = self._speech
        while self._pending.size >= self._window:
            win = self._pending[: self._window]
            self._pending = self._pending[self._window :]
            self._vad.accept_waveform(win)
            speech = bool(self._vad.is_speech_detected())
        return speech

    def _update_hangover(self, speech: bool, n_samples: int) -> None:
        self._speech = speech
        dt_ms = 1000.0 * n_samples / self.sample_rate
        if speech:
            self._seen_speech = True
            self._silence_ms = 0.0
        else:
            self._silence_ms += dt_ms

    def is_speech(self) -> bool:
        return self._speech

    def should_auto_stop(self) -> bool:
        return self._seen_speech and self._silence_ms >= self.hangover_ms

    def reset(self) -> None:
        self._speech = False
        self._seen_speech = False
        self._silence_ms = 0.0
        self._pending = np.zeros(0, dtype=np.float32)
        if self._vad is not None:
            try:
                self._vad.reset()
            except Exception:
                pass
