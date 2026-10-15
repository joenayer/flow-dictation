"""User-systemd autostart for the flow-linux.service unit.

``is_enabled`` / ``set_enabled`` never raise when ``systemctl`` is missing:
they return ``None`` / ``False``. ``set_enabled`` never passes ``--now``.
"""

from __future__ import annotations

import subprocess

UNIT = "flow-linux.service"

_TIMEOUT_S = 10
_ENABLED_STATES = frozenset({"enabled", "enabled-runtime"})


def _run(argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run *argv*; return ``None`` if ``systemctl`` is missing."""
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return None
    except (OSError, subprocess.TimeoutExpired):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")


def _parse_is_enabled(stdout: str) -> bool:
    token = (stdout or "").strip().split()
    if not token:
        return False
    return token[0] in _ENABLED_STATES


def is_enabled() -> bool | None:
    """Return whether the user unit is enabled, or ``None`` if no systemctl."""
    proc = _run(["systemctl", "--user", "is-enabled", UNIT])
    if proc is None:
        return None
    return _parse_is_enabled(proc.stdout)


def set_enabled(on: bool) -> bool:
    """Enable or disable the user unit (no ``--now``). ``False`` on failure."""
    action = "enable" if on else "disable"
    proc = _run(["systemctl", "--user", action, UNIT])
    if proc is None:
        return False
    return proc.returncode == 0
