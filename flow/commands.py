"""Command Mode v1: spoken ``hey flow`` prefix, local text-edit commands.

``handle_command`` lowercases and strips the transcript. It must start with
the trigger ``hey flow`` (case-insensitive, whole words) or it returns
``handled=False``. When ``handled=True``, flowd types
``CommandResult.message``; if ``CommandResult.keys`` is set, the integrator
presses that keyspec instead of typing the message.

Built-ins (text after the prefix):

    new line         → a newline (``\\n``)
    new paragraph    → two newlines (``\\n\\n``)
    press enter      → a newline (``\\n``)
    date             → today's date as ``YYYY-MM-DD``
    time             → current local time as ``HH:MM`` (24-hour)
    type <words>     → ``<words>`` verbatim (original case preserved)
    delete last word → press keys ``Ctrl+BackSpace``
    undo             → press keys ``Ctrl+Z``
    select all       → press keys ``Ctrl+A``
    spell <words>    → ``<words>`` with a single space between every character
    shout <words>    → ``<words>`` in uppercase
    small <words>    → ``<words>`` in lowercase

Any other remainder is unhandled. The built-in set is intentionally small.
"""

from __future__ import annotations

import dataclasses
import datetime
import re

from flow.config import Settings

_PREFIX_RE = re.compile(r"^hey\s+flow(?:\s+|$)", re.IGNORECASE)


@dataclasses.dataclass
class CommandResult:
    handled: bool
    message: str = ""
    keys: str = ""


def handle_command(transcript: str, settings: Settings) -> CommandResult:
    """Parse a spoken command. *settings* is accepted for the frozen contract."""
    _ = settings
    stripped = transcript.strip()
    match = _PREFIX_RE.match(stripped)
    if match is None:
        return CommandResult(handled=False)

    rest_raw = stripped[match.end() :].strip()
    rest = rest_raw.lower()
    if rest == "new line":
        return CommandResult(handled=True, message="\n")
    if rest == "new paragraph":
        return CommandResult(handled=True, message="\n\n")
    if rest == "press enter":
        return CommandResult(handled=True, message="\n")
    if rest == "date":
        return CommandResult(
            handled=True, message=datetime.date.today().isoformat()
        )
    if rest == "time":
        return CommandResult(
            handled=True, message=datetime.datetime.now().strftime("%H:%M")
        )
    if rest.startswith("type "):
        # "type " is five characters in any casing of "type".
        return CommandResult(handled=True, message=rest_raw[5:])
    if rest == "delete last word":
        return CommandResult(handled=True, keys="Ctrl+BackSpace")
    if rest == "undo":
        return CommandResult(handled=True, keys="Ctrl+Z")
    if rest == "select all":
        return CommandResult(handled=True, keys="Ctrl+A")
    if rest.startswith("spell "):
        return CommandResult(handled=True, message=" ".join(rest_raw[6:]))
    if rest.startswith("shout "):
        return CommandResult(handled=True, message=rest_raw[6:].upper())
    if rest.startswith("small "):
        return CommandResult(handled=True, message=rest_raw[6:].lower())
    return CommandResult(handled=False)
