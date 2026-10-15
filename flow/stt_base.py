"""STT engine interface (unit 1 contract)."""

from __future__ import annotations

import abc
import dataclasses

import numpy as np


@dataclasses.dataclass
class Transcription:
    text: str
    duration_s: float
    engine: str


class STTEngine(abc.ABC):
    name: str

    @abc.abstractmethod
    def load(self, models_dir: str, threads: int = 8) -> None:
        """Load (and warm up) the model. Raises RuntimeError if unavailable."""

    @abc.abstractmethod
    def transcribe(self, samples: np.ndarray) -> Transcription:
        """Transcribe int16 mono 16 kHz samples. Must be offline-safe."""

    @abc.abstractmethod
    def unload(self) -> None:
        """Release model resources."""


ENGINES: dict[str, type[STTEngine]] = {}
