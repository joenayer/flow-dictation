"""flow platform backends (OS-specific hotkeys/typers/autostart).

Submodules are import-safe everywhere: importing them never touches
OS-only APIs (no ``ctypes.windll``, ``msvcrt``, ``pynput``, or X11 at
import time). Live OS seams are lazy and injectable for tests.

Available backends:

- :mod:`flow.platform.windows` — Windows 10/11 (pynput hotkeys,
  SendInput typer, Startup-folder autostart, ``%APPDATA%`` dirs).
"""

from __future__ import annotations
