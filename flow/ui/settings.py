"""Settings dialog: shortcut editors, engine combo, autostart, history snapshot."""

from __future__ import annotations

import sys
import threading
from collections.abc import Callable
from dataclasses import fields as dc_fields

try:
    from Xlib import X, XK

    from ..hotkey_x11 import parse_shortcut as _x11_parse_shortcut

    _HAS_X11 = True
except ImportError:  # Windows installs omit xlib; validation uses its parser
    _HAS_X11 = False
    X = None  # type: ignore[assignment]
    XK = None  # type: ignore[assignment]

from ..config import Settings

_MAX_KEYS = 3
_MAX_BINDINGS = 4
if _HAS_X11:
    _RESERVED_KEYSYMS = {
        XK.XK_c: "Ctrl+C",
        XK.XK_v: "Ctrl+V",
        XK.XK_x: "Ctrl+X",
        XK.XK_z: "Ctrl+Z",
        XK.XK_a: "Ctrl+A",
    }
else:
    _RESERVED_KEYSYMS = {}


def _parse_binding(binding: str):
    """Parse with the platform backend (raises ValueError when invalid)."""
    if sys.platform == "win32":
        from ..platform.windows import parse_shortcut as _wparse

        return _wparse(binding)
    if not _HAS_X11:  # pragma: no cover - broken install
        raise ValueError("shortcut parsing unavailable (xlib missing)")
    return _x11_parse_shortcut(binding)

_SHORTCUT_FIELDS: tuple[tuple[str, str], ...] = (
    ("ptt_shortcut", "Push-to-talk"),
    ("handsfree_shortcut", "Hands-free"),
    ("command_shortcut", "Command"),
    ("paste_last_shortcut", "Paste last"),
    ("copy_last_shortcut", "Copy last"),
    ("cancel_key", "Cancel"),
)

_ENGINES = ("parakeet", "moonshine")

try:
    from PySide6.QtCore import QEvent, QObject, Qt, Signal
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )

    _HAS_QT = True
except ImportError:  # pragma: no cover - optional for pure validation tests
    _HAS_QT = False
    QDialog = object  # type: ignore[misc, assignment]
    QWidget = object  # type: ignore[misc, assignment]


def _reserved_reason(binding: str) -> str | None:
    if not _HAS_X11 or sys.platform == "win32":
        return None  # reserved set is X11-app-specific
    modmask, keysym = _x11_parse_shortcut(binding)
    core = modmask & ~X.ShiftMask
    if keysym in _RESERVED_KEYSYMS and core == X.ControlMask:
        name = _RESERVED_KEYSYMS[keysym]
        return f"reserved shortcut ({name}; Ctrl+C/V/X/Z/A are reserved)"
    return None


def validate_shortcut(s: str) -> tuple[bool, str]:
    """Return ``(ok, reason)`` for a shortcut or comma-separated bindings.

    Rules: at most 3 keys per binding, at most 4 bindings, no unmodified
    letters, no reserved Ctrl+C/V/X/Z/A. Mouse buttons are rejected by
    ``parse_shortcut``.
    """
    if s is None or not str(s).strip():
        return False, "empty shortcut"
    raw = [part.strip() for part in str(s).split(",")]
    if any(part == "" for part in raw):
        return False, "empty binding"
    if len(raw) > _MAX_BINDINGS:
        return False, f"at most {_MAX_BINDINGS} bindings per action"
    for binding in raw:
        tokens = [token.strip() for token in binding.split("+")]
        if any(token == "" for token in tokens):
            return False, f"invalid shortcut {binding!r}: empty token"
        if len(tokens) > _MAX_KEYS:
            return False, f"at most {_MAX_KEYS} keys per shortcut"
        try:
            _parse_binding(binding)
        except ValueError as exc:
            return False, str(exc)
        reserved = _reserved_reason(binding)
        if reserved:
            return False, reserved
    return True, ""


_CANON_MODS = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "ctl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "option": "alt",
    "mod1": "alt",
    "super": "super",
    "win": "super",
    "windows": "super",
    "cmd": "super",
    "meta": "super",
    "mod4": "super",
}


def canonical_binding(binding: str) -> str:
    """Lexical normal form for duplicate detection (same platform)."""
    mods: list[str] = []
    key: str | None = None
    for token in str(binding).split("+"):
        name = token.strip().lower()
        if not name:
            continue
        mod = _CANON_MODS.get(name)
        if mod is not None:
            mods.append(mod)
        else:
            key = name
    return "+".join(sorted(mods) + ([key] if key else []))


def _parsed_is_bare(parsed) -> bool:
    """True when a parsed binding has no modifiers (either backend)."""
    mods, _key = parsed
    if isinstance(mods, int):  # X11 (modmask, keysym)
        return mods == 0
    return len(mods) == 0  # Windows (frozenset, key)


def find_conflicts(values: dict[str, str]) -> dict[str, str]:
    """Map each shortcut field to a conflict message (empty when clean).

    Only parsed-valid bindings participate; invalid ones are reported by
    ``validate_shortcut`` instead. Comparison uses the backend parser's
    canonical result, so alias spellings (Alt+Enter vs Alt+Return) still
    collide. A bare cancel key additionally shadows any binding on the
    same key, matching the backends' any-modifier cancel rule.
    """
    parsed_fields: list[tuple[str, str, str, object]] = []
    for field, title in _SHORTCUT_FIELDS:
        for binding in str(values.get(field, "")).split(","):
            binding = binding.strip()
            if not binding:
                continue
            try:
                parsed = _parse_binding(binding)
            except ValueError:
                continue
            parsed_fields.append((field, title, binding, parsed))
    bare_cancel_keys = {
        parsed[1]
        for field, _t, _b, parsed in parsed_fields
        if field == "cancel_key" and _parsed_is_bare(parsed)
    }
    seen: dict[object, str] = {}
    conflicts: dict[str, str] = {}
    for field, title, binding, parsed in parsed_fields:
        if parsed in seen:
            conflicts[field] = f"same keys as {seen[parsed]} ({binding})"
        else:
            seen[parsed] = title
        if (
            field != "cancel_key"
            and parsed[1] in bare_cancel_keys
            and field not in conflicts
        ):
            conflicts[field] = f"same key as Cancel ({binding})"
    return conflicts


def _qt_key_name(key: int) -> str | None:
    """Map a Qt key code to a ``parse_shortcut``-compatible key token."""
    if Qt.Key.Key_A.value <= key <= Qt.Key.Key_Z.value:
        return chr(key)
    if Qt.Key.Key_0.value <= key <= Qt.Key.Key_9.value:
        return chr(key)
    if Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F35.value:
        return f"F{key - Qt.Key.Key_F1.value + 1}"
    names = {
        Qt.Key.Key_Space.value: "Space",
        Qt.Key.Key_Tab.value: "Tab",
        Qt.Key.Key_Backtab.value: "Tab",
        Qt.Key.Key_Return.value: "Return",
        Qt.Key.Key_Enter.value: "Return",
        Qt.Key.Key_Backspace.value: "BackSpace",
        Qt.Key.Key_Delete.value: "Delete",
        Qt.Key.Key_Insert.value: "Insert",
        Qt.Key.Key_Home.value: "Home",
        Qt.Key.Key_End.value: "End",
        Qt.Key.Key_PageUp.value: "Page_Up",
        Qt.Key.Key_PageDown.value: "Page_Down",
        Qt.Key.Key_Up.value: "Up",
        Qt.Key.Key_Down.value: "Down",
        Qt.Key.Key_Left.value: "Left",
        Qt.Key.Key_Right.value: "Right",
    }
    return names.get(key)


_MODIFIER_KEYS = frozenset(
    {
        Qt.Key.Key_Shift.value,
        Qt.Key.Key_Control.value,
        Qt.Key.Key_Alt.value,
        Qt.Key.Key_Meta.value,
        Qt.Key.Key_AltGr.value,
        Qt.Key.Key_CapsLock.value,
        Qt.Key.Key_NumLock.value,
        Qt.Key.Key_ScrollLock.value,
    }
    if _HAS_QT
    else set()
)


def combo_spec_from_qt(modifiers: int, key: int) -> str | None:
    """Build a ``Ctrl+Alt+X``-style spec from a Qt key event.

    Returns None when the key has no unambiguous shortcut token.
    """
    name = _qt_key_name(key)
    if name is None:
        return None
    parts: list[str] = []
    if modifiers & Qt.KeyboardModifier.ControlModifier.value:
        parts.append("Ctrl")
    if modifiers & Qt.KeyboardModifier.AltModifier.value:
        parts.append("Alt")
    if modifiers & Qt.KeyboardModifier.ShiftModifier.value:
        parts.append("Shift")
    if modifiers & Qt.KeyboardModifier.MetaModifier.value:
        parts.append("Super")
    parts.append(name)
    return "+".join(parts)


class SettingsWidget(QWidget):
    """Settings form (shortcut editors + engine + autostart + history).

    Embeddable in the main window; ``SettingsDialog`` wraps it for
    standalone use. Each shortcut row has a Record button that captures
    the next key combination via a keyboard grab (an X11 keyboard grab
    under the hood on X11) with ``validate_shortcut`` applied.
    """

    _autostart_done = Signal(bool, bool) if _HAS_QT else None  # wanted, ok
    _validated = Signal(str) if _HAS_QT else None  # joined reasons ("" ok)

    def __init__(
        self,
        settings: Settings | None = None,
        history: list[str] | None = None,
        *,
        on_refresh_history: Callable[[], list[str]] | None = None,
        initial_autostart: bool = False,
        on_autostart_toggle: Callable[[bool], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        if not _HAS_QT:
            raise RuntimeError("PySide6 is required for SettingsWidget")
        super().__init__(parent)
        self._autostart_done.connect(self._finish_autostart_toggle)
        self._on_refresh_history = on_refresh_history
        self._on_autostart_toggle = on_autostart_toggle
        self._settings = settings or Settings()
        self._history = list(history or [])
        self._editors: dict[str, QLineEdit] = {}
        self._capture_btns: dict[str, QPushButton] = {}
        self._capturing: str | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        shortcuts_title = QLabel("Keyboard shortcuts")
        shortcuts_title.setProperty("role", "section")
        root.addWidget(shortcuts_title)

        form = QFormLayout()
        form.setSpacing(8)
        for field, title in _SHORTCUT_FIELDS:
            row = QHBoxLayout()
            row.setSpacing(8)
            editor = QLineEdit(getattr(self._settings, field))
            editor.setPlaceholderText("e.g. Alt+W")
            editor.textChanged.connect(self._revalidate)
            # Keep full height under layout starvation: squeezed text
            # controls paint smeared text (the history list below absorbs
            # shortage instead — it scrolls).
            editor.setMinimumHeight(editor.sizeHint().height())
            self._editors[field] = editor
            row.addWidget(editor, 1)
            record = QPushButton("Record")
            record.setMinimumHeight(record.sizeHint().height())
            record.setToolTip(f"Click, then press the keys for {title}")
            record.clicked.connect(
                lambda _checked=False, f=field: self._toggle_capture(f)
            )
            self._capture_btns[field] = record
            row.addWidget(record)
            form.addRow(title, row)
        root.addLayout(form)

        capture_hint = QLabel(
            "Tip: click Record, then press the key combination. "
            "Plain Esc cancels; type “Escape” manually to bind it."
        )
        capture_hint.setProperty("role", "hint")
        capture_hint.setWordWrap(True)
        root.addWidget(capture_hint)

        engine_title = QLabel("Speech engine")
        engine_title.setProperty("role", "section")
        root.addWidget(engine_title)

        self._engine = QComboBox()
        self._engine.addItems(list(_ENGINES))
        current = self._settings.engine if self._settings.engine in _ENGINES else _ENGINES[0]
        self._engine.setCurrentText(current)
        root.addWidget(self._engine)

        self._autostart = QCheckBox("Start at login")
        self._autostart.setChecked(bool(initial_autostart))
        self._autostart.toggled.connect(self._emit_autostart_toggle)
        root.addWidget(self._autostart)

        hist_header = QHBoxLayout()
        hist_title = QLabel("Recent dictation")
        hist_title.setProperty("role", "section")
        hist_header.addWidget(hist_title)
        hist_header.addStretch(1)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_history)
        hist_header.addWidget(refresh_btn)
        root.addLayout(hist_header)

        self._history_list = QListWidget()
        self._history_list.addItems(self._history)
        root.addWidget(self._history_list)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setProperty("role", "error")
        root.addWidget(self._error)
        if not self._history and on_refresh_history is not None:
            # No snapshot provided: fill the list instead of opening empty.
            self._refresh_history()
        self._revalidate()

    # -- values / validation ------------------------------------------
    def values(self) -> Settings:
        data = {f.name: getattr(self._settings, f.name) for f in dc_fields(Settings)}
        for field, editor in self._editors.items():
            data[field] = editor.text().strip()
        data["engine"] = self._engine.currentText()
        return Settings(**data)

    def is_valid(self) -> bool:
        return not self._error.text()

    def _emit_autostart_toggle(self, checked: bool) -> None:
        if self._on_autostart_toggle is None:
            return
        # systemctl/registry work runs off the UI thread; on failure the
        # checkbox reverts and the error label explains (L8).
        wanted = bool(checked)
        self._autostart.setEnabled(False)

        def _work() -> None:
            try:
                result = self._on_autostart_toggle(wanted)
            except Exception:  # noqa: BLE001 - surfaced as toggle failure
                result = False
            # None (unknown backend) counts as applied; only False reverts.
            self._autostart_done.emit(wanted, result is not False)

        threading.Thread(target=_work, daemon=True).start()

    def _finish_autostart_toggle(self, wanted: bool, ok: bool) -> None:
        self._autostart.setEnabled(True)
        if ok:
            return
        self._autostart.blockSignals(True)
        self._autostart.setChecked(not wanted)
        self._autostart.blockSignals(False)
        self._report_error(
            "Start at login could not be "
            + ("enabled" if wanted else "disabled")
            + " — is systemctl available?"
        )

    def _refresh_history(self) -> None:
        if self._on_refresh_history is not None:
            snapshot = self._on_refresh_history() or []
            self._history = list(snapshot)
        self._history_list.clear()
        self._history_list.addItems(self._history)

    def _revalidate(self) -> None:
        reasons: list[str] = []
        for field, title in _SHORTCUT_FIELDS:
            ok, reason = validate_shortcut(self._editors[field].text())
            if not ok:
                reasons.append(f"{title}: {reason}")
        if not reasons:
            values = {
                field: self._editors[field].text()
                for field, _ in _SHORTCUT_FIELDS
            }
            titles = dict(_SHORTCUT_FIELDS)
            for field, message in find_conflicts(values).items():
                reasons.append(f"{titles[field]}: conflicts — {message}")
        self._error.setText("\n".join(reasons))
        if _HAS_QT:
            self._validated.emit("\n".join(reasons))
        save_btn = getattr(self, "_save_btn", None)
        if save_btn is not None:
            save_btn.setEnabled(not reasons)

    # -- click-to-record capture --------------------------------------
    def _toggle_capture(self, field: str) -> None:
        if self._capturing == field:
            self._cancel_capture()
        else:
            self._start_capture(field)

    def _start_capture(self, field: str) -> None:
        self._cancel_capture()
        self._capturing = field
        btn = self._capture_btns[field]
        btn.setText("Press keys…")
        btn.setProperty("recording", True)
        btn.style().unpolish(btn)
        btn.style().polish(btn)
        btn.installEventFilter(self)
        try:
            btn.grabKeyboard()
        except Exception:  # noqa: BLE001 - grab is best effort offscreen
            pass
        btn.setFocus()

    def _finish_capture(self) -> None:
        field = self._capturing
        self._capturing = None
        if field is None:
            return
        btn = self._capture_btns[field]
        btn.removeEventFilter(self)
        try:
            btn.releaseKeyboard()
        except Exception:  # noqa: BLE001 - best effort
            pass
        btn.setText("Record")
        btn.setProperty("recording", False)
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _cancel_capture(self) -> None:
        self._finish_capture()

    def _report_error(self, text: str) -> None:
        self._error.setText(text)
        if _HAS_QT:
            self._validated.emit(text)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt API
        if self._capturing is not None and event.type() == QEvent.Type.KeyPress:
            key = event.key()
            if key in _MODIFIER_KEYS:
                return True
            field = self._capturing
            title = dict(_SHORTCUT_FIELDS).get(field, field)
            if key == Qt.Key.Key_Escape.value and not (
                event.modifiers()
                & (
                    Qt.KeyboardModifier.ControlModifier
                    | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier
                )
            ):
                self._cancel_capture()
                return True
            spec = combo_spec_from_qt(event.modifiers().value, key)
            if spec is None:
                self._finish_capture()
                self._report_error(
                    f"{title}: could not read that key combination"
                )
                return True
            ok, reason = validate_shortcut(spec)
            if not ok:
                self._finish_capture()
                self._report_error(f"{title}: {spec} — {reason}")
                return True
            self._finish_capture()
            self._editors[field].setText(spec)
            return True
        return super().eventFilter(watched, event)


class SettingsDialog(QDialog):
    """Shortcut editors, engine picker, start-at-login, and a history snapshot."""

    def __init__(
        self,
        settings: Settings | None = None,
        history: list[str] | None = None,
        *,
        on_save: Callable[[Settings], None] | None = None,
        on_refresh_history: Callable[[], list[str]] | None = None,
        initial_autostart: bool = False,
        on_autostart_toggle: Callable[[bool], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        if not _HAS_QT:
            raise RuntimeError("PySide6 is required for SettingsDialog")
        super().__init__(parent)
        self._on_save = on_save

        from .theme import window_icon

        self.setWindowTitle("flow-linux settings")
        self.setModal(True)
        self.setWindowIcon(window_icon())
        self.setProperty("flowWindow", True)
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(10)

        heading = QLabel("Settings")
        heading.setProperty("role", "title")
        root.addWidget(heading)

        self._form = SettingsWidget(
            settings,
            history,
            on_refresh_history=on_refresh_history,
            initial_autostart=initial_autostart,
            on_autostart_toggle=on_autostart_toggle,
            parent=self,
        )
        root.addWidget(self._form, 1)
        # Backward-compatible attribute aliases (see SettingsWidget).
        self._settings = self._form._settings
        self._history = self._form._history
        self._editors = self._form._editors
        self._capture_btns = self._form._capture_btns
        self._engine = self._form._engine
        self._autostart = self._form._autostart
        self._history_list = self._form._history_list
        self._error = self._form._error

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        self._save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        if self._save_btn is not None:
            self._save_btn.setProperty("primary", True)
        self._form._save_btn = self._save_btn  # type: ignore[attr-defined]
        root.addWidget(buttons)
        self._revalidate()

    def values(self) -> Settings:
        return self._form.values()

    def _emit_autostart_toggle(self, checked: bool) -> None:
        self._form._emit_autostart_toggle(checked)

    def _refresh_history(self) -> None:
        self._form._refresh_history()
        self._history = self._form._history

    def _revalidate(self) -> None:
        self._form._revalidate()

    def _save(self) -> None:
        self._revalidate()
        if self._save_btn is not None and not self._save_btn.isEnabled():
            return
        settings = self.values()
        self._settings = settings
        self._form._settings = settings
        if self._on_save is not None:
            self._on_save(settings)
        self.accept()
