"""Audio capture interface (unit 1 contract)."""

from __future__ import annotations

import abc
from collections.abc import Callable

import numpy as np


class AudioCapture(abc.ABC):
    sample_rate: int = 16000

    @abc.abstractmethod
    def start(self, on_chunk: Callable[[np.ndarray], None]) -> None:
        """Begin capture; deliver int16 mono 16k chunks to the callback."""

    @abc.abstractmethod
    def stop(self) -> np.ndarray:
        """Stop capture and return the full int16 mono utterance."""

    @abc.abstractmethod
    def list_inputs(self) -> list[str]:
        """Human-readable input device names (for settings UI)."""
