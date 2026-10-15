#!/usr/bin/env python3
"""Offline admin-script safety checks. All CLI/crypto operations are mocked."""
import os
from pathlib import Path
import subprocess
import tempfile

SCRIPT = Path(__file__).with_name("setup-preview-signing.sh")
PIN = "a" * 64
MOCK = r'''#!/usr/bin/env python3
import os, sys
from pathlib import Path
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
case = os.environ["SIGNING_CASE"]
with open(os.environ["SIGNING_LOG"], "a") as log:
    log.write(tool + " " + " ".join(args[:2]) + "\n")
if tool == "gh":
    if args[0] == "api":
        endpoint = next(a for a in args if a.startswith("repos/"))
        if endpoint.endswith("public-key"):
            if case == "public403":
                print("gh: Resource not accessible (HTTP 403)", file=sys.stderr)
                sys.exit(1)
            print("{}")
        elif "/variables/" in endpoint:
            if case in ("pin403", "pin500"):
                print("gh: unavailable (HTTP " + ("403" if case == "pin403" else "500") + ")", file=sys.stderr)
                sys.exit(1)
            if case in ("initial", "partial", "secrets403"):
                print("gh: Not Found (HTTP 404)", file=sys.stderr)
                sys.exit(1)
            print("a" * 64)
        elif endpoint.endswith("/secrets"):
            if case == "secrets403":
                print("gh: unavailable (HTTP 403)", file=sys.stderr)
                sys.exit(1)
            if case in ("partial", "retry"):
                print("FLOW_PREVIEW_KEYSTORE_BASE64")
        else:
            sys.exit(90)
    elif args[0] in ("secret", "variable"):
        sys.stdin.read()
    else:
        sys.exit(91)
elif tool == "keytool":
    if "-genkeypair" in args:
        Path(args[args.index("-keystore") + 1]).write_text("MOCK KEY, NOT CRYPTOGRAPHIC")
    elif "-exportcert" in args:
        print("mock certificate bytes")
    else:
        sys.exit(92)
elif tool == "openssl":
    if args[0] == "rand":
        print("mock-password-not-a-secret")
    elif args[0] == "x509":
        sys.stdin.read()
        print("sha256 Fingerprint=" + ("b" if case == "mismatch" else "a") * 64)
    else:
        sys.exit(93)
'''


def check(case, existing=False, expected_success=False):
    with tempfile.TemporaryDirectory(prefix="flow-signing-fixture-") as temp:
        directory = Path(temp)
        bin_dir = directory / "bin"
        bin_dir.mkdir()
        for tool in ("gh", "keytool", "openssl"):
            executable = bin_dir / tool
            executable.write_text(MOCK)
            executable.chmod(0o700)
        backup = directory / "private"
        if existing:
            backup.mkdir()
            for name, value in {
                "preview.jks": "MOCK KEY, NOT CRYPTOGRAPHIC",
                "repository": "fixture/repo\n",
                "store-password": "mock-store-password",
                "key-password": "mock-key-password",
            }.items():
                (backup / name).write_text(value)
        log = directory / "calls"
        env = os.environ.copy()
        env.update(PATH=str(bin_dir) + os.pathsep + env["PATH"],
                   SIGNING_CASE=case, SIGNING_LOG=str(log))
        result = subprocess.run(["bash", str(SCRIPT), "fixture/repo", str(backup)],
                                env=env, capture_output=True, text=True)
        calls = log.read_text()
        writes = [line for line in calls.splitlines()
                  if line.startswith(("gh secret set", "gh variable set"))]
        assert (result.returncode == 0) == expected_success, (case, result.stderr)
        if expected_success:
            assert len(writes) == 5, (case, calls)
            assert (backup / "certificate-sha256").read_text().strip() == PIN
            assert backup.stat().st_mode & 0o777 == 0o700
            assert all(p.stat().st_mode & 0o777 == 0o600 for p in backup.iterdir())
        else:
            assert not writes, (case, calls)
            assert "keytool -genkeypair" not in calls, (case, calls)
            if not existing:
                assert not backup.exists(), (case, calls)
        if existing:
            assert "keytool -genkeypair" not in calls, (case, calls)
        print(f"Signing safety fixture passed: {case}")


if __name__ == "__main__":
    for scenario in ("public403", "pin403", "pin500", "secrets403", "missing", "partial"):
        check(scenario)
    check("mismatch", existing=True)
    check("retry", existing=True, expected_success=True)
    check("initial", expected_success=True)
