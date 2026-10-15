"""Event bus + session state (unit 1 contract)."""

from __future__ import annotations

import enum
from collections import defaultdict
from collections.abc import Callable


class SessionState(enum.Enum):
    IDLE = "idle"
    RECORDING = "recording"
    PROCESSING = "processing"


class EventBus:
    """Tiny synchronous pub/sub. Event names: state/transcript/command/error."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable]] = defaultdict(list)

    def on(self, name: str, cb: Callable) -> None:
        self._subs[name].append(cb)

    def emit(self, name: str, *args) -> None:
        for cb in list(self._subs.get(name, [])):
            cb(*args)
