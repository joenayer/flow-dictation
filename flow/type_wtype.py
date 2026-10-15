"""Wayland typer backend using the wtype binary."""

from __future__ import annotations

import shutil
import subprocess

from flow.typer_base import TYPER_BACKENDS, TyperBackend

_TIMEOUT_S = 30


class WtypeTyper(TyperBackend):
    """Type text by piping it to `wtype` on stdin."""

    name = "wtype"

    @classmethod
    def available(cls) -> bool:
        return shutil.which("wtype") is not None

    def type_text(self, text: str) -> bool:
        path = shutil.which("wtype")
        if path is None:
            return False
        try:
            proc = subprocess.run(
                [path],
                input=text,
                text=True,
                capture_output=True,
                timeout=_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return proc.returncode == 0


TYPER_BACKENDS["wtype"] = WtypeTyper
