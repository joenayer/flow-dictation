"""Default shortcuts must stay finger-friendly: max 2 keys, all valid."""

import pytest

from flow.config import Settings
from flow.ui.settings import validate_shortcut

_SHORTCUT_FIELDS = (
    "ptt_shortcut",
    "handsfree_shortcut",
    "command_shortcut",
    "paste_last_shortcut",
    "copy_last_shortcut",
    "cancel_key",
)


def _key_count(binding: str) -> int:
    return len([t for t in binding.split("+") if t.strip()])


def test_defaults_are_valid():
    settings = Settings()
    for field in _SHORTCUT_FIELDS:
        ok, reason = validate_shortcut(getattr(settings, field))
        assert ok, f"{field}={getattr(settings, field)!r} invalid: {reason}"


def test_ptt_default_is_two_key_combo():
    # Product decision: hold-to-talk is a 2-key chord (single keys and
    # 3-key chords were both rejected by the user).
    assert _key_count(Settings().ptt_shortcut) == 2


def test_defaults_use_at_most_two_keys():
    settings = Settings()
    for field in _SHORTCUT_FIELDS:
        for binding in getattr(settings, field).split(","):
            assert _key_count(binding) <= 2, f"{field}={binding!r} needs 3+ keys"


def test_fresh_defaults_use_two_key_alt_chords(tmp_path):
    # Product decision: first-run bindings live in 2-key Alt space on
    # every platform (no Win/Super chords that steal OS shortcuts).
    from flow import config

    settings = config.load_settings(str(tmp_path / "missing.json"))
    for field in _SHORTCUT_FIELDS:
        for binding in getattr(settings, field).split(","):
            assert _key_count(binding) <= 2, f"{field}={binding!r} needs 3+ keys"
            if field == "cancel_key":
                continue
            tokens = [t.strip().lower() for t in binding.split("+")]
            assert "alt" in tokens, f"{field}={binding!r} is not an Alt chord"
            assert not ({"win", "meta", "super", "mod4"} & set(tokens)), field


def test_corrupt_settings_preserved_aside_and_defaulted(tmp_path):
    from flow import config

    path = tmp_path / "settings.json"
    path.write_text("{oops not json", encoding="utf-8")
    settings = config.load_settings(str(path))
    assert settings == config.Settings()
    assert (tmp_path / "settings.json.corrupt").read_text(
        encoding="utf-8"
    ) == "{oops not json"


def test_non_dict_settings_defaulted(tmp_path):
    from flow import config

    path = tmp_path / "settings.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert config.load_settings(str(path)) == config.Settings()


def test_windows_defaults_avoid_win_key(monkeypatch, tmp_path):
    from flow import config

    monkeypatch.setattr("os.name", "nt")
    settings = config.load_settings(str(tmp_path / "missing.json"))
    for field in _SHORTCUT_FIELDS:
        for binding in getattr(settings, field).split(","):
            tokens = [t.strip().lower() for t in binding.split("+")]
            assert not ({"win", "meta", "super", "mod4"} & set(tokens)), field
            assert _key_count(binding) <= 2, f"{field}={binding!r} needs 3+ keys"
            ok, reason = validate_shortcut(binding)
            assert ok, f"{field}={binding!r} invalid: {reason}"


def test_wrong_typed_settings_quarantined_and_defaulted(tmp_path):
    from flow import config

    path = tmp_path / "settings.json"
    path.write_text('{"engine": [], "models_dir": null}', encoding="utf-8")
    settings = config.load_settings(str(path))
    assert settings == config.Settings()
    assert (tmp_path / "settings.json.corrupt").is_file()


def test_invalid_enum_and_numbers_rejected(tmp_path):
    from flow import config

    for bad in (
        '{"engine": "whisper"}',
        '{"stt_threads": 0}',
        '{"stt_threads": true}',
        '{"sample_rate": 8000}',
        '{"cleanup_fillers": "yes"}',
        '{"ptt_shortcut": ""}',
    ):
        path = tmp_path / "settings.json"
        path.write_text(bad, encoding="utf-8")
        assert config.load_settings(str(path)) == config.Settings()
        path.unlink(missing_ok=True)


def test_save_failure_preserves_previous_file(tmp_path, monkeypatch):
    from flow import config

    path = tmp_path / "settings.json"
    config.save_settings(
        config.Settings(ptt_shortcut="Alt+Z"), str(path)
    )
    before = path.read_bytes()

    def _boom(*args, **kwargs):
        raise OSError("injected ENOSPC")

    monkeypatch.setattr(config.tempfile, "mkstemp", _boom)
    with pytest.raises(OSError, match="ENOSPC"):
        config.save_settings(
            config.Settings(ptt_shortcut="Alt+Q"), str(path)
        )
    assert path.read_bytes() == before
    assert config.load_settings(str(path)).ptt_shortcut == "Alt+Z"
    assert list(tmp_path.iterdir()) == [path]  # no stray temp files
