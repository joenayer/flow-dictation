"""Global hotkey interface (unit 1 contract)."""

from __future__ import annotations

import abc
import enum
from collections.abc import Callable

from .config import Settings


class Action(enum.Enum):
    PTT_DOWN = "ptt_down"
    PTT_UP = "ptt_up"
    HANDSFREE_TOGGLE = "handsfree_toggle"
    COMMAND_DOWN = "command_down"
    COMMAND_UP = "command_up"
    PASTE_LAST = "paste_last"
    COPY_LAST = "copy_last"
    CANCEL = "cancel"


class HotkeyBackend(abc.ABC):
    @abc.abstractmethod
    def start(
        self, settings: Settings, dispatch: Callable[[Action], None]
    ) -> None:
        """Grab shortcuts; call dispatch on each action. Double-tap PTT
        (two downs within ~350 ms) dispatches HANDSFREE_TOGGLE."""

    @abc.abstractmethod
    def stop(self) -> None:
        """Release all grabs."""

    def set_cancel_armed(self, armed: bool) -> None:  # noqa: B027 - concrete no-op default, not abstract
        """Arm/disarm the any-modifier cancel grab (default: no-op).

        Backends that steal a bare key (X11 grabs Escape with
        AnyModifier) override this so flowd arms the grab only while
        recording or processing; idle apps keep their Escape key.
        """


HOTKEY_BACKENDS: dict[str, type[HotkeyBackend]] = {}
