"""Offline setup checks for the Linux installer and model fetch script."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = shutil.which("bash")


@unittest.skipIf(os.name == "nt" or not BASH, "requires a POSIX shell")
class LinuxSetupTests(unittest.TestCase):
    def _write_executable(self, path: Path, contents: str) -> None:
        path.write_text(contents, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def test_installer_generates_systemd_valid_service_for_path_with_sed_specials(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flow setup ") as temp_dir:
            temp = Path(temp_dir)
            repo = temp / "flow | checkout 100% & with spaces"
            package_dir = repo / "packaging"
            package_dir.mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "packaging" / "install.sh", package_dir)
            shutil.copy2(REPO_ROOT / "packaging" / "flow-linux.service", package_dir)

            stubs = temp / "stubs"
            stubs.mkdir()
            self._write_executable(stubs / "python3", "#!/bin/sh\nexit 0\n")
            self._write_executable(
                stubs / "uv",
                '#!/bin/sh\n'
                'if [ "$1" = venv ]; then\n'
                '  mkdir -p "$2/bin"\n'
                '  printf "#!/bin/sh\\nexit 0\\n" > "$2/bin/python"\n'
                '  chmod +x "$2/bin/python"\n'
                'fi\n'
                'exit 0\n',
            )
            systemctl_log = temp / "systemctl.log"
            self._write_executable(
                stubs / "systemctl",
                '#!/bin/sh\nprintf "%s\\n" "$*" >> "$SYSTEMCTL_LOG"\n',
            )

            config_home = temp / "user config"
            env = os.environ.copy()
            env.update(
                {
                    "PATH": os.pathsep.join([str(stubs), env.get("PATH", "")]),
                    "XDG_CONFIG_HOME": str(config_home),
                    "SYSTEMCTL_LOG": str(systemctl_log),
                }
            )
            result = subprocess.run(
                [BASH, str(package_dir / "install.sh")],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

            unit_path = config_home / "systemd" / "user" / "flow-linux.service"
            unit = unit_path.read_text(encoding="utf-8")
            root = str(repo.resolve())
            escaped_root = (
                root.replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("%", "%%")
            )
            self.assertIn(
                f'ExecStart="{escaped_root.replace("$", "$$")}/.venv/bin/python" '
                "-m flow.flowd",
                unit,
            )
            self.assertIn(f"WorkingDirectory={escaped_root}", unit)
            self.assertNotIn(r"\|", unit)
            self.assertNotIn(r"\&", unit)
            self.assertNotIn("@FLOW_", unit)
            self.assertEqual(
                systemctl_log.read_text(encoding="utf-8").splitlines(),
                ["--user daemon-reload", "--user enable --now flow-linux.service"],
            )

            analyzer = shutil.which("systemd-analyze")
            if analyzer:
                verified = subprocess.run(
                    [analyzer, "verify", str(unit_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    verified.returncode,
                    0,
                    verified.stdout + verified.stderr,
                )

    def test_fetch_help_has_no_setup_side_effects(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flow fetch help ") as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            fetcher = scripts / "fetch_models.sh"
            shutil.copy2(REPO_ROOT / "scripts" / "fetch_models.sh", fetcher)

            result = subprocess.run(
                [BASH, str(fetcher), "--help"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Usage:", result.stdout)
            self.assertFalse((root / "models").exists())
            self.assertFalse((root / "bench").exists())

    def test_fetch_missing_conversion_dependencies_stops_before_downloads(self) -> None:
        with tempfile.TemporaryDirectory(prefix="flow fetch preflight ") as temp_dir:
            root = Path(temp_dir)
            scripts = root / "scripts"
            scripts.mkdir()
            fetcher = scripts / "fetch_models.sh"
            shutil.copy2(REPO_ROOT / "scripts" / "fetch_models.sh", fetcher)

            stubs = root / "stubs"
            stubs.mkdir()
            fake_python = stubs / "fake-python"
            self._write_executable(
                fake_python,
                "#!/bin/sh\n"
                'case "$2" in\n'
                "  *sys.version_info*) exit 0 ;;\n"
                '  *"import numpy, soundfile"*)\n'
                '    echo "ModuleNotFoundError: missing soundfile" >&2\n'
                "    exit 1 ;;\n"
                "  *) exit 0 ;;\n"
                "esac\n",
            )
            download_log = root / "download.log"
            for tool in ("curl", "wget"):
                self._write_executable(
                    stubs / tool,
                    f'#!/bin/sh\necho {tool} >> "$DOWNLOAD_LOG"\nexit 1\n',
                )

            env = os.environ.copy()
            env.update(
                {
                    "PATH": os.pathsep.join([str(stubs), env.get("PATH", "")]),
                    "PYTHON": str(fake_python),
                    "DOWNLOAD_LOG": str(download_log),
                }
            )
            result = subprocess.run(
                [BASH, str(fetcher)],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("needs numpy and soundfile before downloads can start", result.stderr)
            self.assertFalse((root / "models").exists())
            self.assertFalse((root / "bench").exists())
            self.assertFalse(download_log.exists())


if __name__ == "__main__":
    unittest.main()
