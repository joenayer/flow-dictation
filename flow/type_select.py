"""Pick the first available typer backend."""

from __future__ import annotations

import logging
import sys

from flow.typer_base import TYPER_BACKENDS, TyperBackend

log = logging.getLogger(__name__)

# Side-effect: register backends on TYPER_BACKENDS.
from flow.type_clipboard import ClipboardTyper  # noqa: F401
from flow.type_wtype import WtypeTyper  # noqa: F401
from flow.type_xdotool import XdotoolTyper  # noqa: F401
from flow.type_xlib import XlibTyper  # noqa: F401

if sys.platform == "win32":
    from flow.platform.windows import WinSendInputTyper  # noqa: F401

    PREFERRED_ORDER = ("winsendinput", "clipboard")
else:
    PREFERRED_ORDER = ("xdotool", "xlib", "wtype", "clipboard")


def _is_available(cls: type[TyperBackend]) -> bool:
    fn = getattr(cls, "available", None)
    if fn is None:
        return True
    try:
        return bool(fn())
    except TypeError:
        return bool(cls().available())  # type: ignore[misc]


def available_backend_names() -> list[str]:
    names: list[str] = []
    for name in PREFERRED_ORDER:
        cls = TYPER_BACKENDS.get(name)
        if cls is not None and _is_available(cls):
            names.append(name)
    return names


def select_typer_name() -> str | None:
    names = available_backend_names()
    return names[0] if names else None


def select_typer() -> TyperBackend | None:
    name = select_typer_name()
    if name is None:
        return None
    return TYPER_BACKENDS[name]()


def select_typers() -> list[TyperBackend]:
    """Instantiate every available backend in preference order.

    Used for typing fallthrough: if the primary backend refuses text
    (e.g. xdotool with non-ASCII), the next one is tried.
    """
    typers: list[TyperBackend] = []
    for name in available_backend_names():
        try:
            typers.append(TYPER_BACKENDS[name]())
        except Exception as exc:
            log.warning("typer %s unavailable: %s", name, exc)
    return typers
