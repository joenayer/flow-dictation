"""Type-into-focused-app interface (unit 1 contract)."""

from __future__ import annotations

import abc


class TyperBackend(abc.ABC):
    @abc.abstractmethod
    def type_text(self, text: str) -> bool:
        """Type text into the focused app. True on success."""

    def press_keys(self, keyspec: str) -> bool:
        """Press a key chord into the focused app. True on success.

        *keyspec* is Xlib-style tokens joined by ``+`` (e.g. ``Ctrl+BackSpace``,
        ``Ctrl+Z``, ``Ctrl+A``). Backends that do not inject chords return
        False.
        """
        return False


TYPER_BACKENDS: dict[str, type[TyperBackend]] = {}
