"""Wayland hotkey backend stub (v1 gap)."""

from __future__ import annotations

from collections.abc import Callable

from .config import Settings
from .hotkey_base import HOTKEY_BACKENDS, Action, HotkeyBackend


class WaylandBackend(HotkeyBackend):
    """Placeholder until xdg-desktop-portal GlobalShortcuts is wired."""

    def start(
        self, settings: Settings, dispatch: Callable[[Action], None]
    ) -> None:
        raise RuntimeError(
            "Wayland global hotkeys are not implemented in v1; "
            "xdg-desktop-portal GlobalShortcuts is the planned backend"
        )

    def stop(self) -> None:
        return None


HOTKEY_BACKENDS["wayland"] = WaylandBackend
