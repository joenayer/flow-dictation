"""flowd integration tests: pure selection helpers + smoke contract."""

import os

import pytest

from flow.flowd import repo_root, resolve_models_dir, select_hotkey_name


def test_select_hotkey_name():
    assert select_hotkey_name("x11") == "x11"
    assert select_hotkey_name("") == "x11"
    assert select_hotkey_name("Wayland") == "wayland"
    assert select_hotkey_name("wayland") == "wayland"


def test_resolve_models_dir_absolute_untouched(tmp_path):
    assert resolve_models_dir(str(tmp_path)) == str(tmp_path)


def test_resolve_models_dir_relative_goes_to_repo():
    assert resolve_models_dir("models") == os.path.join(repo_root(), "models")


def test_smoke_requires_models_or_passes():
    """Smoke with a missing fixture must fail cleanly (no traceback)."""
    from flow.flowd import run_smoke

    rc = run_smoke("/nonexistent.wav", "x", "parakeet")
    assert rc == 1


@pytest.mark.skipif(
    not os.path.isfile(
        os.path.join(repo_root(), "models", "parakeet-v2-int8", "tokens.txt")
    ),
    reason="parakeet model not downloaded",
)
def test_smoke_needs_fixture_arg():
    from flow.flowd import main

    assert main(["--smoke"]) == 1
