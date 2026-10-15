"""Clipboard fallback typer: copy text so the user can paste manually."""

from __future__ import annotations

import shutil
import subprocess

from flow.typer_base import TYPER_BACKENDS, TyperBackend

_TIMEOUT_S = 10
COPIED_MESSAGE = "copied, paste manually"


def _copy_with(cmd: list[str], text: str) -> bool:
    try:
        proc = subprocess.run(
            cmd,
            input=text,
            text=True,
            capture_output=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


class ClipboardTyper(TyperBackend):
    """Copy text with xclip or xsel. Does not type into the focused app.

    Success means a copy actually happened (the "copied, paste manually" path).
    """

    name = "clipboard"
    message = COPIED_MESSAGE

    @classmethod
    def available(cls) -> bool:
        return shutil.which("xclip") is not None or shutil.which("xsel") is not None

    def type_text(self, text: str) -> bool:
        xclip = shutil.which("xclip")
        if xclip is not None and _copy_with(
            [xclip, "-selection", "clipboard"], text
        ):
            return True
        xsel = shutil.which("xsel")
        if xsel is not None and _copy_with(
            [xsel, "--clipboard", "--input"], text
        ):
            return True
        return False


TYPER_BACKENDS["clipboard"] = ClipboardTyper
