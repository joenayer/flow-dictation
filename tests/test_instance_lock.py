"""Single-instance lock: second holder must fail, release must free it."""

import os

import pytest

from flow.flowd import take_instance_lock

pytestmark = pytest.mark.skipif(
    not hasattr(os, "fork"), reason="POSIX fcntl locks only"
)


def test_second_lock_fails_while_first_held(tmp_path):
    path = str(tmp_path / "flowd.lock")
    first = take_instance_lock(path)
    assert first is not None
    try:
        assert take_instance_lock(path) is None
    finally:
        first.close()


def test_lock_released_on_close(tmp_path):
    path = str(tmp_path / "flowd.lock")
    first = take_instance_lock(path)
    assert first is not None
    first.close()
    second = take_instance_lock(path)
    assert second is not None
    second.close()
