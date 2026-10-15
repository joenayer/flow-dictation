"""Offscreen QApplication smoke tests for HistoryWindow."""

from __future__ import annotations

import importlib.util
import os
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 not installed",
)
pytest.importorskip("PySide6", reason="PySide6 not installed")

from PySide6.QtWidgets import QApplication  # noqa: E402

from flow.ui.history_window import HistoryWindow, format_row  # noqa: E402


class FakeStore:
    """Minimal in-memory stand-in for TranscriptStore."""

    def __init__(self, entries: list[dict] | None = None) -> None:
        self.entries = list(entries or [])

    def all(self) -> list[dict]:
        return list(self.entries)

    def search(self, query: str) -> list[dict]:
        needle = query.casefold()
        return [e for e in self.entries if needle in str(e.get("text") or "").casefold()]


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["flow-linux-history"])
    return app


def _entries() -> list[dict]:
    return [
        {"id": "3", "ts": 1_700_000_060.0, "text": "charlie last"},
        {"id": "2", "ts": None, "text": "bravo unknown"},
        {"id": "1", "ts": 1_700_000_000.0, "text": "alpha utterance"},
    ]


def test_construct_rows_and_unknown_time(qapp: QApplication) -> None:
    copied: list[str] = []
    window = HistoryWindow(FakeStore(_entries()), copy_fn=copied.append)
    assert window._list.count() == 3
    assert window._list.item(0).text() == format_row(_entries()[0])
    assert window._list.item(1).text().startswith("unknown time — ")
    assert "bravo unknown" in window._list.item(1).text()
    expected_stamp = datetime.fromtimestamp(1_700_000_000.0).strftime(
        "%Y-%m-%d %H:%M"
    )
    assert window._list.item(2).text() == f"{expected_stamp} — alpha utterance"
    assert copied == []


def test_search_filter_and_copy(qapp: QApplication) -> None:
    copied: list[str] = []
    store = FakeStore(_entries())
    window = HistoryWindow(store, copy_fn=copied.append)

    window._search.setText("ALPHA")
    assert window._list.count() == 1
    assert "alpha utterance" in window._list.item(0).text()

    window._list.setCurrentRow(0)
    window._copy_btn.click()
    assert copied == ["alpha utterance"]

    window._search.setText("")
    assert window._list.count() == 3
    window._list.setCurrentRow(0)
    window._list.itemDoubleClicked.emit(window._list.item(0))
    assert copied == ["alpha utterance", "charlie last"]

    window._copy_btn.click()
    assert copied[-1] == "charlie last"


def test_refresh_reloads_store(qapp: QApplication) -> None:
    copied: list[str] = []
    store = FakeStore(_entries())
    window = HistoryWindow(store, copy_fn=copied.append)
    assert window._list.count() == 3
    store.entries.insert(0, {"id": "4", "ts": 1_700_000_120.0, "text": "delta new"})
    window._refresh_btn.click()
    assert window._list.count() == 4
    assert "delta new" in window._list.item(0).text()


def test_detail_shows_full_text_of_selection(qapp: QApplication) -> None:
    long_text = "wonderful " * 40 + "UNIQUE ENDING"
    store = FakeStore(
        [{"id": "9", "ts": 1_700_000_200.0, "text": long_text}]
    )
    window = HistoryWindow(store, copy_fn=lambda text: None)
    try:
        # Newest entry preselected: full text readable without copying.
        assert window._list.currentRow() == 0
        assert "UNIQUE ENDING" in window._detail.toPlainText()
        assert window._detail.toPlainText() == long_text
        assert window._detail.isReadOnly()
        window._search.setText("zzz-no-match")
        assert window._detail.toPlainText() == ""
    finally:
        window.close()
