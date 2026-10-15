"""Pure autostart tests: monkeypatched subprocess plus a skipif live check."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from flow.autostart import UNIT, is_enabled, set_enabled


def _has_user_systemd() -> bool:
    if shutil.which("systemctl") is None:
        return False
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return os.path.isdir(os.path.join(runtime, "systemd"))


def _completed(argv: list[str], returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")


def test_unit_name() -> None:
    assert UNIT == "flow-linux.service"


@pytest.mark.parametrize(
    "stdout, expected",
    [
        ("enabled\n", True),
        ("enabled", True),
        ("enabled-runtime\n", True),
        ("disabled\n", False),
        ("not-found\n", False),
        ("masked\n", False),
        ("", False),
    ],
)
def test_is_enabled_parses_stdout(monkeypatch: pytest.MonkeyPatch, stdout: str, expected: bool) -> None:
    def fake_run(argv, **kwargs):
        assert argv == ["systemctl", "--user", "is-enabled", UNIT]
        assert "--now" not in argv
        return _completed(argv, 0 if expected else 1, stdout)

    monkeypatch.setattr("flow.autostart.subprocess.run", fake_run)
    assert is_enabled() is expected


def test_is_enabled_missing_systemctl(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("systemctl")

    monkeypatch.setattr("flow.autostart.subprocess.run", fake_run)
    assert is_enabled() is None


def test_is_enabled_oserror_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        raise OSError("bus")

    monkeypatch.setattr("flow.autostart.subprocess.run", fake_run)
    assert is_enabled() is False


def test_is_enabled_timeout_is_false(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, 10)

    monkeypatch.setattr("flow.autostart.subprocess.run", fake_run)
    assert is_enabled() is False


@pytest.mark.parametrize("on, action", [(True, "enable"), (False, "disable")])
def test_set_enabled_enable_disable(monkeypatch: pytest.MonkeyPatch, on: bool, action: str) -> None:
    seen: list[list[str]] = []

    def fake_run(argv, **kwargs):
        seen.append(list(argv))
        assert "--now" not in argv
        assert argv == ["systemctl", "--user", action, UNIT]
        return _completed(argv, 0)

    monkeypatch.setattr("flow.autostart.subprocess.run", fake_run)
    assert set_enabled(on) is True
    assert seen == [["systemctl", "--user", action, UNIT]]


def test_set_enabled_never_now(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        assert argv[0] == "systemctl"
        assert "--now" not in argv
        return _completed(argv, 0)

    monkeypatch.setattr("flow.autostart.subprocess.run", fake_run)
    assert set_enabled(True) is True
    assert set_enabled(False) is True


def test_set_enabled_missing_systemctl(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        raise FileNotFoundError("systemctl")

    monkeypatch.setattr("flow.autostart.subprocess.run", fake_run)
    assert set_enabled(True) is False
    assert set_enabled(False) is False


def test_set_enabled_nonzero(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        return _completed(argv, 1, "Failed")

    monkeypatch.setattr("flow.autostart.subprocess.run", fake_run)
    assert set_enabled(True) is False


def test_set_enabled_oserror(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(argv, **kwargs):
        raise OSError("bus")

    monkeypatch.setattr("flow.autostart.subprocess.run", fake_run)
    assert set_enabled(True) is False


@pytest.mark.skipif(not _has_user_systemd(), reason="needs user systemd")
def test_live_is_enabled() -> None:
    result = is_enabled()
    assert isinstance(result, bool)
