"""X11 typer backend using the xdotool binary."""

from __future__ import annotations

import shutil
import subprocess

from flow.typer_base import TYPER_BACKENDS, TyperBackend

_TIMEOUT_S = 30


class XdotoolTyper(TyperBackend):
    """Type ascii text via `xdotool type --clearmodifiers --delay 0 --`."""

    name = "xdotool"

    @classmethod
    def available(cls) -> bool:
        return shutil.which("xdotool") is not None

    def type_text(self, text: str) -> bool:
        path = shutil.which("xdotool")
        if path is None:
            return False
        if not text.isascii():
            return False
        try:
            proc = subprocess.run(
                [path, "type", "--clearmodifiers", "--delay", "0", "--", text],
                capture_output=True,
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0

    def press_keys(self, keyspec: str) -> bool:
        path = shutil.which("xdotool")
        if path is None:
            return False
        if not keyspec or not str(keyspec).strip():
            return False
        try:
            proc = subprocess.run(
                [path, "key", keyspec],
                capture_output=True,
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0


TYPER_BACKENDS["xdotool"] = XdotoolTyper
