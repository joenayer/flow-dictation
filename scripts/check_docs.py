#!/usr/bin/env python3
"""Check local file targets in tracked Markdown without making network requests."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
INLINE_LINK = re.compile(r"\[[^\]\n]*\]\((?:<([^>\n]+)>|([^\s)]+))(?:\s+\"[^\"\n]*\")?\)")


def main() -> int:
    names = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "*.md"], cwd=ROOT
    ).decode("utf-8").split("\0")
    failures: list[str] = []
    count = 0
    for name in filter(None, names):
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        # Code examples can contain illustrative Markdown that is not a link.
        visible = re.sub(
            r"(?ms)^(`{3,}|~{3,})[^\n]*\n.*?^\1[^\n]*$",
            lambda match: "\n" * match.group(0).count("\n"),
            text,
        )
        for match in INLINE_LINK.finditer(visible):
            target = match.group(1) or match.group(2)
            if urlsplit(target).scheme or target.startswith(("#", "//")):
                continue
            local = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not local:
                continue
            count += 1
            resolved = ROOT / local.lstrip("/") if local.startswith("/") else path.parent / local
            if not resolved.exists():
                line = visible.count("\n", 0, match.start()) + 1
                failures.append(f"{name}:{line}: missing local target: {target}")
    if failures:
        print("\n".join(failures))
        return 1
    print(f"Checked {count} local Markdown file links. External URLs and anchors are not checked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
