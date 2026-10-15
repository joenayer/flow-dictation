"""DictionaryStore, DictionaryDialog, and STT hotwords wiring."""

from __future__ import annotations

import inspect
import os
from pathlib import Path

import numpy as np
import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from flow.dictionary import (  # noqa: E402
    DEFAULT_HOTWORDS_SCORE,
    DictionaryStore,
    normalize_phrase,
    parse_hotwords_file,
    recognizer_hotwords_kwargs,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "phrase,ok",
    [
        ("hello", True),
        ("Hello World", True),
        ("O'Brien", True),
        ("well-known", True),
        ("don't", True),
        ("a b c d e", True),
        ("  spaced   out  ", True),
        ("a b c d e f", False),
        ("hello123", False),
        ("hello_world", False),
        ("hello,world", False),
        ("", False),
        ("   ", False),
        ("-leading", False),
        ("trailing-", False),
        ("foo--bar", False),
    ],
)
def test_normalize_phrase(phrase: str, ok: bool) -> None:
    got = normalize_phrase(phrase)
    if ok:
        assert got is not None
        assert 1 <= len(got.split()) <= 5
    else:
        assert got is None


def test_add_remove_and_duplicates(tmp_path: Path) -> None:
    store = DictionaryStore(str(tmp_path / "hotwords.txt"))
    assert store.words() == []
    assert store.add("hello") is True
    assert store.add("  hello  ") is False
    assert store.add("hello world") is True
    assert store.add("hello123") is False
    assert store.words() == ["hello", "hello world"]
    assert store.remove("hello") is True
    assert store.remove("hello") is False
    assert store.words() == ["hello world"]


def test_persist_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "hotwords.txt"
    store = DictionaryStore(str(path))
    assert store.add("hello")
    assert store.add("O'Brien")
    assert store.add("well-known")
    assert store.add("hello world")
    store.save()
    text = path.read_text(encoding="utf-8")
    assert text.splitlines() == ["hello", "O'Brien", "well-known", "hello world"]
    assert text.endswith("\n")

    reloaded = DictionaryStore(str(path))
    assert reloaded.words() == ["hello", "O'Brien", "well-known", "hello world"]
    assert reloaded.remove("O'Brien")
    reloaded.save()
    again = DictionaryStore(str(path))
    assert again.words() == ["hello", "well-known", "hello world"]


def test_load_strips_optional_sherpa_score(tmp_path: Path) -> None:
    path = tmp_path / "hotwords.txt"
    path.write_text("HELLO WORLD :2.0\nFOREVER\n", encoding="utf-8")
    store = DictionaryStore(str(path))
    assert store.words() == ["HELLO WORLD", "FOREVER"]


def test_parse_malformed_score_not_last(tmp_path: Path) -> None:
    path = tmp_path / "hotwords.txt"
    path.write_text("HELLO :2.0 WORLD\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="malformed"):
        parse_hotwords_file(str(path))


def _transducer_factory(
    encoder: str = "",
    decoder: str = "",
    joiner: str = "",
    tokens: str = "",
    hotwords_file: str = "",
    hotwords_score: float = 1.5,
    decoding_method: str = "greedy_search",
) -> None:
    return None


def _moonshine_factory(
    preprocessor: str = "",
    encoder: str = "",
    decoding_method: str = "greedy_search",
) -> None:
    return None


def test_recognizer_kwargs_transducer(tmp_path: Path) -> None:
    assert recognizer_hotwords_kwargs(str(tmp_path), _transducer_factory) == {}
    (tmp_path / "hotwords.txt").write_text("hello\n", encoding="utf-8")
    kw = recognizer_hotwords_kwargs(str(tmp_path), _transducer_factory)
    assert kw["hotwords_file"] == str(tmp_path / "hotwords.txt")
    assert kw["hotwords_score"] == DEFAULT_HOTWORDS_SCORE
    assert kw["decoding_method"] == "modified_beam_search"


def test_recognizer_kwargs_moonshine_factory_has_no_hotwords(
    tmp_path: Path,
) -> None:
    (tmp_path / "hotwords.txt").write_text("hello\n", encoding="utf-8")
    assert recognizer_hotwords_kwargs(str(tmp_path), _moonshine_factory) == {}


def test_load_signature_unchanged() -> None:
    from flow.stt_moonshine import MoonshineEngine
    from flow.stt_parakeet import ParakeetEngine

    for cls in (ParakeetEngine, MoonshineEngine):
        params = list(inspect.signature(cls.load).parameters)
        assert params == ["self", "models_dir", "threads"]


def _touch_parakeet_stubs(models_dir: Path) -> None:
    root = models_dir / "parakeet-v2-int8"
    root.mkdir()
    for name in (
        "encoder.int8.onnx",
        "decoder.int8.onnx",
        "joiner.int8.onnx",
        "tokens.txt",
    ):
        (root / name).write_bytes(b"x")


def _touch_moonshine_stubs(models_dir: Path) -> None:
    root = models_dir / "moonshine-base-en-int8"
    root.mkdir()
    for name in (
        "preprocess.onnx",
        "encode.int8.onnx",
        "uncached_decode.int8.onnx",
        "cached_decode.int8.onnx",
        "tokens.txt",
    ):
        (root / name).write_bytes(b"x")


class _FakeStream:
    result = type("R", (), {"text": ""})()

    def accept_waveform(self, sample_rate: int, audio: np.ndarray) -> None:
        return None


class _FakeRecognizer:
    def create_stream(self) -> _FakeStream:
        return _FakeStream()

    def decode_stream(self, stream: _FakeStream) -> None:
        return None


def test_parakeet_passes_hotwords_to_factory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sherpa_onnx

    from flow.stt_parakeet import ParakeetEngine

    _touch_parakeet_stubs(tmp_path)
    (tmp_path / "hotwords.txt").write_text("hello world\n", encoding="utf-8")
    captured: dict = {}
    orig = sherpa_onnx.OfflineRecognizer.from_transducer

    def fake_from_transducer(*args: object, **kwargs: object) -> _FakeRecognizer:
        captured.update(kwargs)
        return _FakeRecognizer()

    fake_from_transducer.__signature__ = inspect.signature(orig)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        sherpa_onnx.OfflineRecognizer, "from_transducer", fake_from_transducer
    )
    ParakeetEngine().load(str(tmp_path), threads=2)
    assert captured["hotwords_file"] == str(tmp_path / "hotwords.txt")
    assert captured["hotwords_score"] == DEFAULT_HOTWORDS_SCORE
    assert captured["decoding_method"] == "modified_beam_search"


def test_parakeet_malformed_hotwords_error(tmp_path: Path) -> None:
    from flow.stt_parakeet import ParakeetEngine

    _touch_parakeet_stubs(tmp_path)
    (tmp_path / "hotwords.txt").write_text("HELLO :2.0 WORLD\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="malformed"):
        ParakeetEngine().load(str(tmp_path))


def test_moonshine_load_ignores_unsupported_hotwords(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sherpa_onnx

    from flow.stt_moonshine import MoonshineEngine

    _touch_moonshine_stubs(tmp_path)
    (tmp_path / "hotwords.txt").write_text("hello\n", encoding="utf-8")
    captured: dict = {}
    orig = sherpa_onnx.OfflineRecognizer.from_moonshine

    def fake_from_moonshine(*args: object, **kwargs: object) -> _FakeRecognizer:
        captured.update(kwargs)
        return _FakeRecognizer()

    fake_from_moonshine.__signature__ = inspect.signature(orig)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        sherpa_onnx.OfflineRecognizer, "from_moonshine", fake_from_moonshine
    )
    MoonshineEngine().load(str(tmp_path), threads=2)
    assert "hotwords_file" not in captured


def _parakeet_ready() -> bool:
    d = ROOT / "models" / "parakeet-v2-int8"
    names = ("encoder.int8.onnx", "decoder.int8.onnx", "joiner.int8.onnx", "tokens.txt")
    return all((d / n).is_file() for n in names)


def _moonshine_ready() -> bool:
    d = ROOT / "models" / "moonshine-base-en-int8"
    names = (
        "preprocess.onnx",
        "encode.int8.onnx",
        "uncached_decode.int8.onnx",
        "cached_decode.int8.onnx",
        "tokens.txt",
    )
    return all((d / n).is_file() for n in names)


@pytest.mark.skipif(not _parakeet_ready(), reason="parakeet model files missing")
def test_parakeet_load_with_hotwords_file(tmp_path: Path) -> None:
    from flow.stt_parakeet import ParakeetEngine

    models = tmp_path / "models"
    models.mkdir()
    (models / "parakeet-v2-int8").symlink_to(ROOT / "models" / "parakeet-v2-int8")
    (models / "hotwords.txt").write_text("hello\n", encoding="utf-8")
    eng = ParakeetEngine()
    eng.load(str(models), threads=1)
    out = eng.transcribe(np.zeros(1600, dtype=np.int16))
    assert out.engine == "parakeet"
    eng.unload()


@pytest.mark.skipif(not _moonshine_ready(), reason="moonshine model files missing")
def test_moonshine_load_with_hotwords_file_present(tmp_path: Path) -> None:
    from flow.stt_moonshine import MoonshineEngine

    models = tmp_path / "models"
    models.mkdir()
    (models / "moonshine-base-en-int8").symlink_to(
        ROOT / "models" / "moonshine-base-en-int8"
    )
    (models / "hotwords.txt").write_text("hello\n", encoding="utf-8")
    eng = MoonshineEngine()
    eng.load(str(models), threads=1)
    out = eng.transcribe(np.zeros(1600, dtype=np.int16))
    assert out.engine == "moonshine"
    eng.unload()


def test_dialog_offscreen_smoke(tmp_path: Path) -> None:
    pytest.importorskip("PySide6", reason="PySide6 not installed")
    from PySide6.QtWidgets import QApplication

    from flow.ui.dictionary import DictionaryDialog

    app = QApplication.instance()
    if app is None:
        app = QApplication(["flow-linux-dictionary"])

    path = tmp_path / "hotwords.txt"
    store = DictionaryStore(str(path))
    saved: list[DictionaryStore] = []
    dlg = DictionaryDialog(store, on_save=saved.append)
    assert dlg._list.count() == 0

    dlg._edit.setText("not_valid!")
    dlg._add_btn.click()
    assert store.words() == []
    assert dlg._error.text()

    dlg._edit.setText("hello world")
    dlg._add_btn.click()
    assert store.words() == ["hello world"]
    assert dlg._list.count() == 1

    dlg._edit.setText("O'Brien")
    dlg._add_btn.click()
    assert store.words() == ["hello world", "O'Brien"]

    dlg._list.setCurrentRow(0)
    dlg._remove_btn.click()
    assert store.words() == ["O'Brien"]

    dlg._save_btn.click()
    assert saved == [store]
    assert path.read_text(encoding="utf-8").splitlines() == ["O'Brien"]


def test_malformed_file_salvages_valid_lines(tmp_path: Path) -> None:
    path = tmp_path / "hotwords.txt"
    path.write_text("IMPORTANT\nBROKEN :not-a-score\n", encoding="utf-8")
    store = DictionaryStore(str(path))
    assert store.words() == ["IMPORTANT"]
    assert store.load_error
    assert (tmp_path / "hotwords.txt.corrupt").is_file()


def test_save_after_malformed_keeps_backup_and_valid_lines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "hotwords.txt"
    original = "IMPORTANT\nBROKEN :not-a-score\n"
    path.write_text(original, encoding="utf-8")
    store = DictionaryStore(str(path))
    assert store.add("New") is True
    store.save()
    assert (tmp_path / "hotwords.txt.corrupt").read_text(
        encoding="utf-8"
    ) == original
    assert DictionaryStore(str(path)).words() == ["IMPORTANT", "New"]
