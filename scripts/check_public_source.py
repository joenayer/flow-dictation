#!/usr/bin/env python3
"""Reject common accidental disclosures in tracked source and commit metadata."""
from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "android/gradle/wrapper/gradle-wrapper.jar"
WRAPPER_SHA256 = "cb0da6751c2b753a16ac168bb354870ebb1e162e9083f116729cec9c781156b8"
PRIVATE_SUFFIXES = {".apk", ".aar", ".onnx", ".flac", ".wav", ".zip", ".db", ".sqlite", ".jks", ".keystore", ".pem", ".p12", ".key", ".log"}
EMAIL = re.compile(r"\b[A-Za-z0-9_.+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
SECRETS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
)
LOCAL_USER = re.compile(r"(?:[A-Za-z]:[/\\]Users[/\\]|" + "/" + "home" + "/" + r")([^\s\"'`/\\]+)[/\\]", re.I)
EXAMPLE_USERS = {"runner", "user", "username", "example", "test", "testuser"}


def allowed_email_domain(domain: str) -> bool:
    domain = domain.lower()
    return domain in {"example.com", "example.net", "example.org", "users.noreply.github.com"} or domain.endswith((".example", ".test", ".invalid"))


def allowed_contact(address: str) -> bool:
    address = address.lower()
    if address == "noreply@github.com":
        return True
    match = EMAIL.fullmatch(address)
    return bool(match and allowed_email_domain(match.group(1)))


def scan_file(name: str, data: bytes) -> list[str]:
    """Return redacted categories only; never include matched private values."""
    path = PurePosixPath(name)
    if any(part.startswith((".scratch", ".env")) or part in {".codex", ".t3"} for part in path.parts) or name.startswith("docs/prompts/"):
        return ["local/private file path"]
    if path.suffix.lower() in PRIVATE_SUFFIXES:
        return ["generated, private, or unreviewed binary file"]
    if name == WRAPPER:
        return [] if hashlib.sha256(data).hexdigest() == WRAPPER_SHA256 else ["unverified Gradle wrapper"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["unreviewed binary file"]
    if "\x00" in text:
        return ["unreviewed binary file"]
    problems = []
    if any(pattern.search(text) for pattern in SECRETS):
        problems.append("credential-shaped content")
    if any(not allowed_contact(match.group(0)) for match in EMAIL.finditer(text)):
        problems.append("non-example contact address")
    if any(match.group(1).lower() not in EXAMPLE_USERS for match in LOCAL_USER.finditer(text)):
        problems.append("named local user path")
    return problems


def git_output(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=root)


def check_repository(root: Path) -> tuple[list[str], int, int]:
    """Inspect exact staged blobs and every blob in reachable commit trees."""
    index_records = git_output(root, "ls-files", "--stage", "-z").split(b"\0")
    staged: list[tuple[str, str]] = []
    issues: list[str] = []
    for record in index_records:
        if not record:
            continue
        header, raw_name = record.split(b"\t", 1)
        mode, oid, stage = header.decode("ascii").split()
        name = raw_name.decode("utf-8", errors="replace")
        if stage != "0":
            issues.append(f"{name}: unresolved index entry")
            continue
        if mode == "120000":
            issues.append(f"{name}: unreviewed symlink")
            continue
        if mode == "160000":
            issues.append(f"{name}: unreviewed submodule")
            continue
        if mode not in {"100644", "100755"}:
            issues.append(f"{name}: unreviewed file type")
            continue
        staged.append((name, oid))

    for name, oid in staged:
        for category in scan_file(name, git_output(root, "cat-file", "blob", oid)):
            issues.append(f"{name}: {category}")

    commit_records = git_output(root, "log", "--all", "--format=%H%x1f%an%x1f%ae%x1f%cn%x1f%ce%x00")
    commits = 0
    commit_ids: list[str] = []
    for record in commit_records.split(b"\0"):
        record = record.strip(b"\n")
        if not record:
            continue
        fields = record.decode("utf-8", errors="replace").split("\x1f")
        if len(fields) != 5:
            issues.append("history: unreadable commit metadata")
            continue
        commit, author_name, author_email, committer_name, committer_email = fields
        commits += 1
        commit_ids.append(commit)
        allowed_names = {"flow maintainer", "github"}
        if author_name.lower() not in allowed_names or committer_name.lower() not in allowed_names:
            issues.append(f"commit {commit[:12]}: non-generic identity metadata")
        if any(not (address.lower().endswith("@users.noreply.github.com") or address.lower() == "noreply@github.com") for address in (author_email, committer_email)):
            issues.append(f"commit {commit[:12]}: non-noreply contact metadata")
        for category in scan_file("commit-message.txt", git_output(root, "show", "-s", "--format=%B", commit)):
            issues.append(f"commit {commit[:12]} message: {category}")

    seen: set[tuple[str, str]] = set()
    for commit in commit_ids:
        entries = git_output(root, "ls-tree", "-rz", "--full-tree", "-r", commit).split(b"\0")
        for entry in entries:
            if not entry:
                continue
            header, raw_name = entry.split(b"\t", 1)
            mode, object_type, oid = header.decode("ascii").split()
            name = raw_name.decode("utf-8", errors="replace")
            if mode == "120000":
                issues.append(f"{name}: unreviewed symlink")
                continue
            if mode == "160000" or object_type == "commit":
                issues.append(f"{name}: unreviewed submodule")
                continue
            if mode not in {"100644", "100755"} or object_type != "blob":
                issues.append(f"{name}: unreviewed file type")
                continue
            key = (oid, name)
            if key in seen:
                continue
            seen.add(key)
            for category in scan_file(name, git_output(root, "cat-file", "blob", oid)):
                issues.append(f"{name}: {category}")
    return issues, len(staged), commits


def main(root: Path = ROOT) -> int:
    issues, files, commits = check_repository(root)
    if issues:
        print("\n".join(issues))
        return 1
    if not files:
        return 1
    print(f"Public-source checks passed: {files} staged files, {commits} reachable commits. Independent review is still required before publication.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
